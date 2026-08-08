"""Exact desktop-item geometry via Windows UI Automation."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from src.utils.logger import logger


def find_desktop_item_center(name: str) -> tuple[int, int] | None:
    """Return the center of the visible desktop item whose label exactly matches *name*.

    UI Automation returns Windows' own bounding rectangle for the Desktop
    ListView item.  Unlike a vision-model coordinate, it is pixel-precise and
    remains correct after moving the icon or changing DPI scaling.
    """
    encoded_name = base64.b64encode(name.encode("utf-16-le")).decode("ascii")
    script = f"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$target = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{encoded_name}'))
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condition = New-Object System.Windows.Automation.AndCondition(
    (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $target)),
    (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem))
)
$matches = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
foreach ($item in $matches) {{
    $rect = $item.Current.BoundingRectangle
    if ($rect.Width -gt 0 -and $rect.Height -gt 0) {{
        [PSCustomObject]@{{x=$rect.X; y=$rect.Y; width=$rect.Width; height=$rect.Height}} | ConvertTo-Json -Compress
    }}
}}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        matches = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
        if not matches:
            return None

        # Desktop icons are generally near the top/left; that also eliminates
        # a matching item exposed by another application window.
        match = min(matches, key=lambda item: (item["y"], item["x"]))
        x = round(match["x"] + match["width"] / 2)
        y = round(match["y"] + match["height"] / 2)
        logger.info(f"UI Automation located desktop item '{name}' at ({x},{y})")
        return x, y
    except Exception as exc:
        logger.debug(f"UI Automation lookup for '{name}' unavailable: {exc}")
        return None


def find_notepad_from_reference(image: Image.Image) -> tuple[int, int] | None:
    """Locate Notepad using the project's clean, unannotated reference capture.

    This is used only when UI Automation is unavailable (for example, in a
    restricted desktop session).  The template is the actual shortcut image on
    this machine, so its match is far more precise than an LLM coordinate.
    """
    reference_path = Path(__file__).parents[2] / "debug_winprtscn.png"
    if not reference_path.is_file():
        return None

    try:
        reference = np.asarray(Image.open(reference_path).convert("RGB"))
        # In the clean reference screenshot, this box is the Notepad image
        # only: x=16..78, y=6..68.  It deliberately excludes the label.
        template = reference[6:68, 16:78]
        current = np.asarray(image.convert("RGB"))
        result = cv2.matchTemplate(
            cv2.cvtColor(current, cv2.COLOR_RGB2BGR),
            cv2.cvtColor(template, cv2.COLOR_RGB2BGR),
            cv2.TM_CCOEFF_NORMED,
        )
        _, score, _, location = cv2.minMaxLoc(result)
        if score < 0.85:
            logger.debug(f"Notepad reference match rejected: score={score:.3f}")
            return None

        x = location[0] + template.shape[1] // 2
        y = location[1] + template.shape[0] // 2
        logger.info(f"Reference match located Notepad at ({x},{y}), score={score:.3f}")
        return x, y
    except Exception as exc:
        logger.debug(f"Notepad reference matching unavailable: {exc}")
        return None
