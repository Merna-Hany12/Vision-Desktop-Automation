from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_runtime_grounding_does_not_bypass_screenseeker_with_desktop_automation() -> None:
    source = (PROJECT_ROOT / "src" / "grounding" / "screenseeker.py").read_text(encoding="utf-8")

    assert "src.automation.desktop_items" not in source
    assert "find_desktop_item_center" not in source
    assert "find_notepad_from_reference" not in source


def test_notepad_target_is_visual_and_not_tied_to_one_filename_or_icon_colour() -> None:
    source = (PROJECT_ROOT / "src" / "main.py").read_text(encoding="utf-8")

    assert "desktop shortcut that launches Windows Notepad" in source
    assert "labeled exactly 'notepad.exe'" not in source
