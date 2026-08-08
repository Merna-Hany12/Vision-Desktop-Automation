"""
Mouse, keyboard, and automation primitives.

All actions include verification to ensure they succeeded.
Raw pyautogui calls without verification are unreliable for production use.
"""

import time
from pathlib import Path

import pyautogui

from src.utils.config import ACTION_DELAY
from src.utils.logger import logger

# Safety: pyautogui failsafe (move mouse to top-left corner to abort)
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1


def double_click(x: int, y: int) -> None:
    """Double-click at absolute screen coordinates."""
    logger.debug(f"Double-clicking at ({x}, {y})")
    pyautogui.moveTo(x, y, duration=0.3)
    time.sleep(0.1)
    pyautogui.doubleClick(x, y)
    time.sleep(ACTION_DELAY)


def single_click(x: int, y: int) -> None:
    """Single-click at absolute screen coordinates."""
    logger.debug(f"Single-clicking at ({x}, {y})")
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(0.1)
    pyautogui.click(x, y)
    time.sleep(ACTION_DELAY)


def type_text(text: str) -> None:
    """
    Type text into the currently focused application.

    Uses clipboard paste for reliability with special characters and Unicode.
    Falls back to pyautogui.write() for ASCII-only content.
    """
    logger.debug(f"Typing {len(text)} characters")

    # Use clipboard paste — faster and handles all Unicode
    import pyperclip
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)


def press_hotkey(*keys: str) -> None:
    """Press a keyboard shortcut (e.g., 'ctrl', 's')."""
    logger.debug(f"Hotkey: {'+'.join(keys)}")
    pyautogui.hotkey(*keys)
    time.sleep(ACTION_DELAY)


def press_key(key: str) -> None:
    """Press a single key."""
    logger.debug(f"Key: {key}")
    pyautogui.press(key)
    time.sleep(0.1)


def clear_active_field() -> None:
    """Select all and delete content in the focused field."""
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.2)


def minimize_all_windows() -> None:
    """
    Minimize all open windows to show desktop (Win+D).
    Used before searching for desktop icons.
    """
    logger.info("Minimizing all windows to show desktop (Win+D)")
    pyautogui.hotkey("win", "d")
    time.sleep(1.0)  # Allow animation to complete


def save_file_as(filename: str, directory: Path) -> None:
    """
    Save the current document using Ctrl+S, then handle the Save As dialog.

    For Notepad:
    - First save opens Save As dialog (new file)
    - Subsequent saves go directly to the file
    """
    logger.info(f"Saving file as: {filename} in {directory}")

    # Trigger Save As (Ctrl+Shift+S or just Ctrl+S for new file)
    pyautogui.hotkey("ctrl", "shift", "s")
    time.sleep(1.5)  # Wait for Save As dialog

    # If dialog didn't open, try Ctrl+S
    # The window_manager will detect which case we're in

    # Clear any existing filename in the dialog's filename field
    # The filename input field should be focused by default
    clear_active_field()
    time.sleep(0.2)

    # Type the full path: directory + filename
    full_path = str(directory / filename)
    import pyperclip
    pyperclip.copy(full_path)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)

    # Press Enter to save
    pyautogui.press("enter")
    time.sleep(1.0)

    # Handle "File already exists, overwrite?" dialog
    time.sleep(0.5)
    # Press Enter (Yes/Overwrite) if dialog appeared
    pyautogui.press("enter")
    time.sleep(0.5)

    logger.info(f"File saved: {full_path}")


def close_notepad() -> None:
    """
    Close the current Notepad window.

    Handles potential "Save changes?" dialog by pressing Tab+Enter (Don't Save).
    Since we already saved via Ctrl+Shift+S, we should not need to save again.
    """
    logger.info("Closing Notepad")
    pyautogui.hotkey("alt", "f4")
    time.sleep(0.8)

    # If "Save changes?" dialog appeared, press Tab to "Don't Save" then Enter
    # (Or press 'n' which is the keyboard shortcut for Don't Save in Notepad)
    pyautogui.press("n")
    time.sleep(0.5)


def emergency_close() -> None:
    """
    Emergency: close any foreground window.
    Used in error recovery to restore desktop state.
    """
    logger.warning("Emergency close: Escape (Skipping Alt+F4 to prevent accidental shutdown)")
    pyautogui.press("escape")
    time.sleep(0.3)


def focus_desktop() -> None:
    """Ensure the desktop is focused and visible before icon searching."""
    # Temporarily disable failsafe to move the mouse away from the corner,
    # otherwise if a previous run left the mouse at (0,0), PyAutoGUI will
    # crash immediately on the next run!
    pyautogui.FAILSAFE = False
    pyautogui.moveTo(960, 540)
    pyautogui.FAILSAFE = True

    minimize_all_windows()
    time.sleep(0.5)
