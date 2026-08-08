"""
Screenshot capture module with multi-method fallback.
Tries mss first (fastest), then PIL.ImageGrab, then PowerShell CopyFromScreen.
Validates that captures are not blank (all-black) before accepting.
"""

import io
import os
import base64
import ctypes
import tempfile
import subprocess
from dataclasses import dataclass

# Set DPI awareness immediately to fix zoomed-in/cutoff screenshots on Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import mss
import mss.tools
from PIL import Image
import numpy as np

from src.utils.logger import logger
from src.utils.config import SCREEN_WIDTH, SCREEN_HEIGHT

# ── Set DPI awareness so we get real pixel coordinates (1920x1080, not scaled) ─
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass
class Screenshot:
    """Container for a captured screenshot."""
    image: Image.Image          # PIL Image
    base64_png: str             # Base64-encoded PNG (for Gemini API)
    width: int
    height: int
    region: dict | None = None  # Captured region (None = full desktop)


def _is_blank(img: Image.Image) -> bool:
    """Check if an image is completely blank (all black/zero pixels)."""
    arr = np.array(img)
    return arr.max() < 5  # Allow tiny noise threshold


def _capture_mss() -> Image.Image | None:
    """Try capturing with mss (fastest method)."""
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        if _is_blank(img):
            logger.warning("mss captured a BLANK image (BitBlt likely failed silently)")
            return None
        logger.debug(f"mss capture OK: {img.width}x{img.height}")
        return img
    except Exception as e:
        logger.warning(f"mss capture failed: {e}")
        return None


def _capture_imagegrab() -> Image.Image | None:
    """Try capturing with PIL.ImageGrab."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if _is_blank(img):
            logger.warning("ImageGrab captured a BLANK image")
            return None
        logger.debug(f"ImageGrab capture OK: {img.width}x{img.height}")
        return img
    except Exception as e:
        logger.warning(f"ImageGrab capture failed: {e}")
        return None


def _capture_powershell() -> Image.Image | None:
    """Capture using PowerShell + .NET System.Drawing (last resort)."""
    try:
        tmp_path = os.path.join(tempfile.gettempdir(), "_screenseeker_capture.png")
        ps_script = f"""
$code = @"
using System;
using System.Runtime.InteropServices;
public class DPI {{
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();
}}
"@
Add-Type -TypeDefinition $code -Language CSharp
[DPI]::SetProcessDPIAware()

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$w = $screen.Bounds.Width
$h = $screen.Bounds.Height
$bitmap = New-Object System.Drawing.Bitmap($w, $h)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Bounds.Location, [System.Drawing.Point]::Empty, $screen.Bounds.Size)
$bitmap.Save('{tmp_path.replace(chr(92), "/")}')
$graphics.Dispose()
$bitmap.Dispose()
Write-Output 'OK'
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            logger.warning(f"PowerShell capture failed: {result.stderr}")
            return None

        img = Image.open(tmp_path).convert("RGB")
        if _is_blank(img):
            logger.warning("PowerShell captured a BLANK image")
            return None
        logger.debug(f"PowerShell capture OK: {img.width}x{img.height}")
        return img
    except Exception as e:
        logger.warning(f"PowerShell capture failed: {e}")
        return None


def _capture_printscreen() -> Image.Image | None:
    """Capture using Win+PrintScreen (saves to Pictures/Screenshots folder).
    
    This is the most reliable method on systems where GDI BitBlt fails
    (e.g., certain GPU drivers, VS Code terminal, DPI scaling issues).
    """
    try:
        import pyautogui
        import glob
        import time
        
        pyautogui.FAILSAFE = False
        
        # Find the Screenshots folder
        ss_dirs = [
            os.path.expanduser("~/Pictures/Screenshots"),
            os.path.expanduser("~/OneDrive/Pictures/Screenshots"),
        ]
        ss_dir = None
        for d in ss_dirs:
            if os.path.isdir(d):
                ss_dir = d
                break
        
        if ss_dir is None:
            # Create the folder so Windows has somewhere to save
            ss_dir = os.path.expanduser("~/Pictures/Screenshots")
            os.makedirs(ss_dir, exist_ok=True)
        
        # Record existing files before pressing PrintScreen
        before = set(glob.glob(os.path.join(ss_dir, "*.png")))
        
        # Press Win+PrintScreen
        pyautogui.hotkey('win', 'printscreen')
        
        # Wait for the new file to appear (up to 5 seconds)
        new_file = None
        for _ in range(50):  # 50 * 0.1s = 5s max
            time.sleep(0.1)
            after = set(glob.glob(os.path.join(ss_dir, "*.png")))
            diff = after - before
            if diff:
                new_file = max(diff, key=os.path.getmtime)
                break
        
        if new_file is None:
            logger.warning("Win+PrintScreen: no new screenshot file appeared")
            return None
        
        # Small delay to let Windows finish writing the file
        time.sleep(0.3)
        
        img = Image.open(new_file).convert("RGB")
        if _is_blank(img):
            logger.warning("Win+PrintScreen captured a BLANK image")
            return None
        
        logger.debug(f"Win+PrintScreen capture OK: {img.width}x{img.height} from {new_file}")
        return img
    except Exception as e:
        logger.warning(f"Win+PrintScreen capture failed: {e}")
        return None


def capture_desktop() -> Screenshot:
    """
    Capture the full desktop as a PIL Image + base64 PNG.

    Tries four methods in order of reliability:
      1. Win+PrintScreen (most reliable on problematic GDI systems)
      2. mss (fastest, uses GDI BitBlt)
      3. PIL.ImageGrab (uses GDI, slightly different path)
      4. PowerShell + .NET CopyFromScreen (last resort)

    Validates each capture is not blank before accepting.
    """
    # Try Win+PrintScreen first (proven to work on this system)
    img = _capture_printscreen()
    if img is None:
        logger.info("Falling back to mss...")
        img = _capture_mss()
    if img is None:
        logger.info("Falling back to ImageGrab...")
        img = _capture_imagegrab()
    if img is None:
        logger.info("Falling back to PowerShell CopyFromScreen...")
        img = _capture_powershell()
    if img is None:
        raise RuntimeError(
            "ALL screenshot capture methods failed or produced blank images. "
            "Please ensure the desktop is visible and not locked."
        )

    b64 = _image_to_base64(img)
    logger.debug(f"Desktop captured: {img.width}x{img.height}")
    return Screenshot(
        image=img,
        base64_png=b64,
        width=img.width,
        height=img.height,
    )


def capture_region(
    x1: int, y1: int, x2: int, y2: int
) -> Screenshot:
    """
    Capture a specific screen region.
    Coordinates are absolute screen pixels.

    Used during recursive ScreenSeekeR search to zoom into candidate areas.
    """
    # Clamp to screen bounds
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(SCREEN_WIDTH, x2)
    y2 = min(SCREEN_HEIGHT, y2)

    region = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}

    with mss.mss() as sct:
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    b64 = _image_to_base64(img)
    logger.debug(f"Region captured: ({x1},{y1})-({x2},{y2}) → {img.width}x{img.height}")
    return Screenshot(
        image=img,
        base64_png=b64,
        width=img.width,
        height=img.height,
        region=region,
    )


def crop_region_from_image(
    image: Image.Image,
    norm_bbox: list[float],
    screen_w: int,
    screen_h: int,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """
    Crop a region from an existing PIL image using normalized coordinates.

    Args:
        image: Source PIL image (full desktop or sub-region)
        norm_bbox: [x1, y1, x2, y2] normalized to 0.0-1.0
        screen_w: Width of the source image in pixels
        screen_h: Height of the source image in pixels

    Returns:
        (cropped_image, (pixel_x1, pixel_y1, pixel_x2, pixel_y2))
    """
    x1 = int(norm_bbox[0] * screen_w)
    y1 = int(norm_bbox[1] * screen_h)
    x2 = int(norm_bbox[2] * screen_w)
    y2 = int(norm_bbox[3] * screen_h)

    # Ensure minimum crop size
    x2 = max(x2, x1 + 50)
    y2 = max(y2, y1 + 50)

    # Clamp
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(screen_w, x2)
    y2 = min(screen_h, y2)

    cropped = image.crop((x1, y1, x2, y2))
    return cropped, (x1, y1, x2, y2)


def _image_to_base64(image: Image.Image) -> str:
    """Encode PIL Image to base64 PNG string for Gemini API."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def image_to_base64_compressed(image: Image.Image, max_width: int = 1280, quality: int = 75) -> str:
    """
    Encode PIL Image to a compressed base64 JPEG string for size-limited APIs (e.g. SBG).

    Resizes to max_width if larger, then saves as JPEG at the given quality.
    A 1920x1080 screenshot (~3-5MB PNG) becomes ~150-400KB JPEG at quality=75.
    """
    img = image.copy()
    if img.width > max_width:
        ratio = max_width / img.width
        new_h = int(img.height * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def save_screenshot(image: Image.Image, path: str) -> None:
    """Save PIL Image to disk."""
    image.save(path, format="PNG")
    logger.debug(f"Screenshot saved: {path}")
