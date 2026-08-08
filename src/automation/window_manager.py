"""
Window manager — verify application state after automation actions.

Provides polling-based verification so we know actions succeeded
before proceeding to the next step.
"""

import time
import subprocess

import pyautogui

from src.utils.config import APP_LAUNCH_TIMEOUT
from src.utils.logger import logger


def wait_for_window(title_contains: str, timeout: float = APP_LAUNCH_TIMEOUT) -> bool:
    """
    Wait for a window with a matching title to appear.

    Uses PowerShell to check for windows by title without requiring
    additional dependencies like pygetwindow (which can be unreliable).

    Args:
        title_contains: Substring to match in window title
        timeout: Max seconds to wait

    Returns:
        True if window found within timeout, False otherwise
    """
    logger.info(f"Waiting for window: '{title_contains}' (timeout={timeout}s)")
    deadline = time.time() + timeout

    while time.time() < deadline:
        if _window_exists(title_contains):
            logger.info(f"Window found: '{title_contains}'")
            return True
        time.sleep(0.5)

    logger.warning(f"Timeout waiting for window: '{title_contains}'")
    return False


def wait_for_window_to_close(title_contains: str, timeout: float = 5.0) -> bool:
    """Wait for a window to disappear."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _window_exists(title_contains):
            return True
        time.sleep(0.3)
    return False


def is_notepad_open() -> bool:
    """Check if Notepad is currently open."""
    return _window_exists("Notepad")


def is_save_dialog_open() -> bool:
    """Check if a Save As dialog is currently active."""
    return _window_exists("Save As") or _window_exists("Save as")


def is_dialog_open() -> bool:
    """Check if any modal dialog is open (save, error, confirmation, etc.)."""
    dialog_titles = ["Save As", "Save as", "Overwrite", "Error", "Warning", "Confirm"]
    return any(_window_exists(title) for title in dialog_titles)


def focus_notepad() -> bool:
    """
    Bring Notepad to the foreground using PowerShell.
    Returns True if Notepad was found and focused.
    """
    script = """
    $wshell = New-Object -com WScript.Shell
    $procs = Get-Process | Where-Object {$_.MainWindowTitle -like "*Notepad*"}
    if ($procs) { $wshell.AppActivate($procs[0].Id); Write-Output "focused" }
    else { Write-Output "not_found" }
    """
    try:
        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=5
        )
        if "focused" in result.stdout:
            time.sleep(0.3)
            return True
        return False
    except Exception as e:
        logger.warning(f"focus_notepad failed: {e}")
        return False


def click_notepad_text_area() -> None:
    """
    Click inside Notepad's text area to ensure it has focus before typing.
    Clicks roughly center of screen (Notepad opens in the center by default).
    """
    # Ask the input driver for its active coordinate space instead of assuming
    # a 1920x1080 desktop.  pyautogui.size() and pyautogui.click() then always
    # use the same DPI-aware coordinate system.
    width, height = pyautogui.size()
    pyautogui.click(width // 2, height // 2)
    time.sleep(0.3)


def handle_unexpected_popup(screenshot_fn) -> bool:
    """
    Detect and dismiss unexpected popups using the Gemini grounder.

    This makes the system robust to "unknown" dialogs — a key requirement
    from the assignment: "bypass unexpected pop-ups without knowing
    what they look like in advance."

    Strategy: Take a screenshot, ask Gemini if a popup is visible,
    and if so, find and click the appropriate dismiss button.

    Args:
        screenshot_fn: Callable that returns a Screenshot object

    Returns:
        True if a popup was detected and handled, False otherwise
    """
    try:
        import requests
        from src.utils.config import SBG_BASE_URL, SBG_API_KEY, SBG_PLANNER_MODEL
        from src.grounding.prompts import POPUP_DETECTION_PROMPT
        from src.capturer.screen_capture import image_to_base64_compressed
        import json
        import re

        screenshot = screenshot_fn()
        sbg_img_b64 = image_to_base64_compressed(screenshot.image, max_width=1024, quality=80)
        
        payload = {
            "model_id": SBG_PLANNER_MODEL,
            "messages": [{"role": "user", "content": POPUP_DETECTION_PROMPT}],
            "system_prompt": "You are a UI popup detection expert.",
            "image": sbg_img_b64,
            "max_tokens": 256,
        }
        
        sbg_url = SBG_BASE_URL.rstrip("/")
        if not sbg_url.endswith("/student/chat"):
            sbg_url += "/student/chat"
            
        response = requests.post(
            sbg_url,
            headers={"Authorization": f"Bearer {SBG_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        
        raw_text = ""
        if "output_text" in data:
            raw_text = data["output_text"]
        elif "choices" in data and len(data["choices"]) > 0:
            raw_text = data["choices"][0].get("message", {}).get("content", "")
        elif "content" in data:
            raw_text = data["content"]
        text = raw_text
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return False

        data = json.loads(match.group(0))

        if not data.get("popup_detected", False):
            return False

        popup_type = data.get("popup_type", "none")
        action = data.get("action_needed", "none")
        button_desc = data.get("button_description")

        logger.warning(f"Unexpected popup detected! type={popup_type}, action={action}")

        if action == "press_enter":
            pyautogui.press("enter")
        elif action == "click_yes":
            pyautogui.press("y")
        elif action == "click_no":
            pyautogui.press("n")
        elif action == "click_ok":
            pyautogui.press("enter")
        elif action == "click_cancel":
            pyautogui.press("escape")
        elif button_desc and action not in ("none",):
            # Use ScreenSeekeR to find and click the button
            from src.grounding.screenseeker import ScreenSeekeR
            from src.automation.mouse_keyboard import single_click
            seeker = ScreenSeekeR()
            result = seeker.ground(button_desc, screenshot)
            if result.success:
                single_click(result.screen_x, result.screen_y)

        time.sleep(0.5)
        return True

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            logger.debug("Popup handler skipped: Gemini rate limited (429)")
        else:
            logger.warning(f"Popup handler error: {e}")
        # Last resort: press Escape
        pyautogui.press("escape")
        time.sleep(0.3)
        return False


def _window_exists(title_contains: str) -> bool:
    """Check if any window with the given title substring exists."""
    try:
        script = f'Get-Process | Where-Object {{$_.MainWindowTitle -like "*{title_contains}*"}} | Measure-Object | Select-Object -ExpandProperty Count'
        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True, text=True, timeout=3
        )
        count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
        return count > 0
    except Exception:
        return False
