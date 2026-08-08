import pytest

from src.grounding.candidate_scorer import apply_nms, dilate_bbox, score_and_rank
from src.grounding.grounder import GroundingResult
from src.grounding.planner import CandidateRegion


def _candidate(bbox: list[float], confidence: float) -> CandidateRegion:
    return CandidateRegion(bbox=bbox, confidence=confidence, reasoning="test")


def _grounding(*, found: bool, confidence: float, center_x: float, center_y: float) -> GroundingResult:
    return GroundingResult(
        found=found,
        confidence=confidence,
        center_x=center_x,
        center_y=center_y,
        bbox=[center_x - 0.05, center_y - 0.05, center_x + 0.05, center_y + 0.05],
        reasoning="test",
    )


def test_dilate_bbox_clamps_to_screen_edges() -> None:
    assert dilate_bbox([0.0, 0.0, 0.1, 0.1], factor=1.5) == pytest.approx([0.0, 0.0, 0.15417, 0.23519], abs=1e-4)


def test_score_and_rank_discards_missing_and_ranks_best_first() -> None:
    candidates = [_candidate([0.1, 0.1, 0.5, 0.5], 0.9), _candidate([0.5, 0.5, 0.9, 0.9], 0.8)]
    groundings = [
        _grounding(found=True, confidence=0.9, center_x=0.5, center_y=0.5),
        _grounding(found=False, confidence=0.0, center_x=0.0, center_y=0.0),
    ]

    scored = score_and_rank(candidates, groundings)

    assert len(scored) == 1
    assert scored[0].candidate is candidates[0]
    assert scored[0].screen_center_x == pytest.approx(0.3)
    assert scored[0].screen_center_y == pytest.approx(0.3)


def test_nms_removes_overlapping_lower_score_candidate() -> None:
    candidates = [_candidate([0.1, 0.1, 0.5, 0.5], 0.9), _candidate([0.12, 0.12, 0.52, 0.52], 0.7)]
    groundings = [
        GroundingResult(True, 0.9, 0.5, 0.5, [0.0, 0.0, 1.0, 1.0], "test"),
        GroundingResult(True, 0.8, 0.5, 0.5, [0.0, 0.0, 1.0, 1.0], "test"),
    ]

    assert len(apply_nms(score_and_rank(candidates, groundings))) == 1
