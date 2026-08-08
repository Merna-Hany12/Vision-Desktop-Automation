"""
Screenshot annotator — draws detection results on screenshots.

Produces the 3 required deliverable screenshots:
  - icon_topleft.png
  - icon_bottomright.png
  - icon_center.png

Each annotated with:
  - Blue boxes: candidate regions proposed by planner
  - Green box: final detected element bounding box
  - Red crosshair: click point
  - Text overlay: confidence score, depth, reasoning
"""

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from src.utils.logger import logger
from src.utils.config import SCREENSHOTS_DIR
from src.grounding.screenseeker import GroundingOutput
from src.grounding.planner import CandidateRegion


def annotate_and_save(
    screenshot: Image.Image,
    grounding_output: GroundingOutput,
    candidates: list[CandidateRegion],
    save_name: str,
    label: Optional[str] = None,
) -> Path:
    """
    Draw detection results on screenshot and save to screenshots/ directory.

    Args:
        screenshot: Full desktop screenshot as PIL Image
        grounding_output: Result from ScreenSeekeR
        candidates: Candidate regions from the planner (for visualization)
        save_name: Filename without extension (e.g., "icon_topleft")
        label: Optional text to display on the image

    Returns:
        Path to saved annotated screenshot
    """
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # Convert PIL to OpenCV (RGB → BGR)
    img_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    h, w = img_cv.shape[:2]

    # ── Draw candidate regions (blue) ──────────────────────────────────────────
    for i, candidate in enumerate(candidates):
        x1 = int(candidate.bbox[0] * w)
        y1 = int(candidate.bbox[1] * h)
        x2 = int(candidate.bbox[2] * w)
        y2 = int(candidate.bbox[3] * h)
        cv2.rectangle(img_cv, (x1, y1), (x2, y2), (255, 100, 0), 2)  # Blue

        # Candidate label
        cv2.putText(
            img_cv, f"Region {i+1} ({candidate.confidence:.0%})",
            (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
            (255, 100, 0), 1, cv2.LINE_AA,
        )

    # ── Draw final detection (green bounding box) ──────────────────────────────
    if grounding_output.success and grounding_output.norm_bbox:
        bbox = grounding_output.norm_bbox
        bx1 = int(bbox[0] * w)
        by1 = int(bbox[1] * h)
        bx2 = int(bbox[2] * w)
        by2 = int(bbox[3] * h)
        cv2.rectangle(img_cv, (bx1, by1), (bx2, by2), (0, 220, 0), 3)  # Green

        # ── Red crosshair at click point ───────────────────────────────────────
        cx = grounding_output.screen_x
        cy = grounding_output.screen_y
        cross_size = 20
        cv2.line(img_cv, (cx - cross_size, cy), (cx + cross_size, cy), (0, 0, 255), 3)
        cv2.line(img_cv, (cx, cy - cross_size), (cx, cy + cross_size), (0, 0, 255), 3)
        cv2.circle(img_cv, (cx, cy), 8, (0, 0, 255), 2)

        # ── Info banner ────────────────────────────────────────────────────────
        banner_text = [
            f"DETECTED: ({cx}, {cy})",
            f"Confidence: {grounding_output.confidence:.0%}",
            f"Search depth: {grounding_output.search_depth}",
        ]
        if label:
            banner_text.insert(0, label)

        _draw_banner(img_cv, banner_text, position=(bx1, by2 + 10))

    else:
        # Draw failure indicator
        cv2.putText(
            img_cv, "NOT FOUND",
            (w // 2 - 100, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
            (0, 0, 255), 4, cv2.LINE_AA,
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    output_path = _next_available_path(SCREENSHOTS_DIR, save_name)
    cv2.imwrite(str(output_path), img_cv)
    logger.info(f"Annotated screenshot saved: {output_path}")
    return output_path


def _next_available_path(directory: Path, save_name: str) -> Path:
    """Return a path without replacing a previously captured deliverable.

    The interview evidence uses stable names such as ``icon_topleft.png``.
    When that file already exists, keep it intact and save a subsequent run as
    ``icon_topleft_01.png``, ``icon_topleft_02.png``, and so on.
    """
    primary_path = directory / f"{save_name}.png"
    if not primary_path.exists():
        return primary_path

    index = 1
    while True:
        candidate_path = directory / f"{save_name}_{index:02d}.png"
        if not candidate_path.exists():
            logger.warning(
                f"Preserving existing screenshot {primary_path.name}; "
                f"saving new capture as {candidate_path.name}"
            )
            return candidate_path
        index += 1


def _draw_banner(
    img: np.ndarray,
    lines: list[str],
    position: tuple[int, int],
) -> None:
    """Draw a semi-transparent text banner on the image."""
    x, y = position
    padding = 8
    line_height = 22
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    thickness = 1

    # Measure banner dimensions
    max_width = max(cv2.getTextSize(line, font, font_scale, thickness)[0][0] for line in lines)
    banner_h = len(lines) * line_height + padding * 2
    banner_w = max_width + padding * 2

    # Clamp banner position to image bounds
    h, w = img.shape[:2]
    x = min(x, w - banner_w - 5)
    y = min(y, h - banner_h - 5)
    x = max(5, x)
    y = max(5, y)

    # Draw semi-transparent background
    overlay = img.copy()
    cv2.rectangle(
        overlay,
        (x, y),
        (x + banner_w, y + banner_h),
        (20, 20, 20), -1  # Dark background
    )
    cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)

    # Draw text
    for i, line in enumerate(lines):
        text_y = y + padding + (i + 1) * line_height
        cv2.putText(img, line, (x + padding, text_y), font, font_scale, (0, 255, 0), thickness, cv2.LINE_AA)
