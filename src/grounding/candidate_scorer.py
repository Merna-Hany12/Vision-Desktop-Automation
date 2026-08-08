"""
Candidate area scoring and Non-Maximum Suppression (NMS).

Implements the scoring formula from the ScreenSeekeR paper (arXiv 2504.07981):
  "Candidates are ranked based on the sum of their scores across all grounded boxes.
   Each candidate's score from a given box is computed using a predefined function
   that considers the distance between their center points: exp(-dist² / (2σ²))"

This ensures:
- Candidates with more grounder votes near their center score higher
- Bias toward large areas is mitigated (size-independent scoring)
- Overlapping candidates are deduplicated via NMS
"""

import math
from dataclasses import dataclass

from src.utils.config import SIGMA, NMS_IOU_THRESHOLD, BOX_DILATION_FACTOR
from src.utils.logger import logger
from src.grounding.planner import CandidateRegion
from src.grounding.grounder import GroundingResult


@dataclass
class ScoredCandidate:
    """A candidate region after scoring by the grounder."""
    candidate: CandidateRegion      # Original planner candidate
    grounding: GroundingResult      # Grounder's finding within this region
    combined_score: float           # Planner confidence × grounder confidence
    screen_center_x: float          # Center in full-screen normalized coords
    screen_center_y: float          # Center in full-screen normalized coords
    screen_bbox: list[float]        # Bounding box in full-screen normalized coords


def score_and_rank(
    candidates: list[CandidateRegion],
    groundings: list[GroundingResult],
) -> list[ScoredCandidate]:
    """
    Score and rank candidate regions using the ScreenSeekeR formula.

    Args:
        candidates: Candidate regions from the planner
        groundings: Grounder results for each candidate (1-to-1 correspondence)

    Returns:
        Sorted list of ScoredCandidate, best first
    """
    assert len(candidates) == len(groundings), "Candidates and groundings must match"

    scored = []
    for candidate, grounding in zip(candidates, groundings):
        if not grounding.found:
            continue

        # The grounder evaluates the patch cropped with an expanded bounding box,
        # so we MUST map its coordinates back using the exact same expanded_bbox!
        expanded_bbox = dilate_bbox(candidate.bbox, factor=1.5)
        region_w = expanded_bbox[2] - expanded_bbox[0]
        region_h = expanded_bbox[3] - expanded_bbox[1]

        screen_cx = expanded_bbox[0] + grounding.center_x * region_w
        screen_cy = expanded_bbox[1] + grounding.center_y * region_h

        # Convert grounder's patch bbox to screen coords
        screen_bbox = [
            expanded_bbox[0] + grounding.bbox[0] * region_w,
            expanded_bbox[1] + grounding.bbox[1] * region_h,
            expanded_bbox[0] + grounding.bbox[2] * region_w,
            expanded_bbox[1] + grounding.bbox[3] * region_h,
        ]
        screen_bbox = [max(0.0, min(1.0, v)) for v in screen_bbox]

        # ScreenSeekeR scoring: planner confidence × Gaussian-weighted grounder score
        gaussian_score = _gaussian_score(
            vote_center=(screen_cx, screen_cy),
            candidate_bbox=screen_bbox,
            sigma=SIGMA,
        )
        combined = candidate.confidence * grounding.confidence * gaussian_score

        scored.append(ScoredCandidate(
            candidate=candidate,
            grounding=grounding,
            combined_score=combined,
            screen_center_x=screen_cx,
            screen_center_y=screen_cy,
            screen_bbox=screen_bbox,
        ))

    # Sort by combined score, best first
    scored.sort(key=lambda s: s.combined_score, reverse=True)

    logger.debug(f"Scored {len(scored)} candidates:")
    for i, s in enumerate(scored):
        logger.debug(
            f"  [{i+1}] score={s.combined_score:.3f} "
            f"center=({s.screen_center_x:.3f},{s.screen_center_y:.3f})"
        )

    return scored


def apply_nms(
    scored: list[ScoredCandidate],
    iou_threshold: float = NMS_IOU_THRESHOLD,
) -> list[ScoredCandidate]:
    """
    Non-Maximum Suppression: remove overlapping candidates.

    When two bounding boxes overlap more than iou_threshold,
    keep only the one with the higher score.

    Args:
        scored: Sorted list of ScoredCandidate (best first)
        iou_threshold: IoU threshold for suppression

    Returns:
        De-duplicated list of ScoredCandidate
    """
    if not scored:
        return []

    kept = []
    for candidate in scored:
        suppressed = False
        for kept_candidate in kept:
            iou = _compute_iou(candidate.screen_bbox, kept_candidate.screen_bbox)
            if iou > iou_threshold:
                suppressed = True
                break
        if not suppressed:
            kept.append(candidate)

    logger.debug(f"NMS: {len(scored)} → {len(kept)} candidates after suppression")
    return kept


def dilate_bbox(
    bbox: list[float], 
    factor: float = BOX_DILATION_FACTOR,
    min_pixel_size: int = 400,
    screen_w: int = 1920,
    screen_h: int = 1080
) -> list[float]:
    """
    Expand a bounding box by a factor around its center, ensuring a minimum pixel size.

    From ScreenSeekeR: "We apply box dilation to expand smaller boxes
    into larger candidate areas, reducing the risk of missing the target."
    
    V2 Enhancement: Ensures the crop is at least `min_pixel_size` to prevent
    Vision LLMs from hallucinating blank images on small patches.

    Args:
        bbox: [x1, y1, x2, y2] normalized
        factor: Expansion factor (e.g., 1.2 = 20% larger)
        min_pixel_size: Minimum width/height in pixels for the crop
        screen_w: Full screen width
        screen_h: Full screen height

    Returns:
        Dilated bbox, clamped to [0, 1]
    """
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2

    # Current pixel dimensions
    px_w = (bbox[2] - bbox[0]) * screen_w
    px_h = (bbox[3] - bbox[1]) * screen_h

    # Target pixel dimensions (max of factor expansion or min_pixel_size)
    target_px_w = max(px_w * factor, min_pixel_size)
    target_px_h = max(px_h * factor, min_pixel_size)

    # Convert back to normalized half-dimensions
    hw = (target_px_w / screen_w) / 2
    hh = (target_px_h / screen_h) / 2

    return [
        max(0.0, cx - hw),
        max(0.0, cy - hh),
        min(1.0, cx + hw),
        min(1.0, cy + hh),
    ]


def _gaussian_score(
    vote_center: tuple[float, float],
    candidate_bbox: list[float],
    sigma: float,
) -> float:
    """
    Gaussian-weighted centrality score from ScreenSeekeR paper.

    score = exp(-dist² / (2σ²))
    where dist = Euclidean distance from vote_center to candidate_bbox center.

    Higher when the vote center is near the candidate center.
    """
    candidate_cx = (candidate_bbox[0] + candidate_bbox[2]) / 2
    candidate_cy = (candidate_bbox[1] + candidate_bbox[3]) / 2

    dist_sq = (vote_center[0] - candidate_cx) ** 2 + (vote_center[1] - candidate_cy) ** 2
    score = math.exp(-dist_sq / (2 * sigma ** 2))
    return score


def _compute_iou(bbox_a: list[float], bbox_b: list[float]) -> float:
    """Compute Intersection over Union (IoU) between two normalized bounding boxes."""
    x1 = max(bbox_a[0], bbox_b[0])
    y1 = max(bbox_a[1], bbox_b[1])
    x2 = min(bbox_a[2], bbox_b[2])
    y2 = min(bbox_a[3], bbox_b[3])

    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
    area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0
