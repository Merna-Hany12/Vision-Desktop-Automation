from pathlib import Path

from PIL import Image

from src.grounding.screenseeker import GroundingOutput
from src.utils import annotator


def _success_output() -> GroundingOutput:
    return GroundingOutput(
        success=True,
        screen_x=50,
        screen_y=50,
        confidence=0.9,
        search_depth=0,
        norm_bbox=[0.25, 0.25, 0.75, 0.75],
        reasoning="test",
    )


def test_annotation_preserves_existing_deliverable_screenshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(annotator, "SCREENSHOTS_DIR", tmp_path)
    primary = tmp_path / "icon_center.png"
    primary.write_bytes(b"approved screenshot")

    result = annotator.annotate_and_save(
        Image.new("RGB", (100, 100), "white"),
        _success_output(),
        [],
        "icon_center",
    )

    assert result == tmp_path / "icon_center_01.png"
    assert primary.read_bytes() == b"approved screenshot"
    assert result.is_file()
