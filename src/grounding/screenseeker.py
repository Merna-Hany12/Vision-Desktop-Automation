"""
ScreenSeekeR — Main grounding pipeline orchestrator.

Implements the full ScreenSeekeR agentic framework from arXiv 2504.07981:

Algorithm:
  1. Position Inference: Planner proposes candidate regions from full screenshot
  2. Candidate Area Scoring: Grounder evaluates each region; regions are scored and ranked
  3. Recursive Search: If confidence < threshold, recurse into the best candidate region

The key insight: "Strategically reducing the search area enhances accuracy."
By narrowing from full-desktop → candidate region → precise element, we achieve
significantly better results than direct full-image grounding.

This pipeline works for ANY UI element described in natural language:
  - "Notepad icon"
  - "Chrome browser shortcut"
  - "Recycle Bin"
  - "OK button in the dialog"
"""

from dataclasses import dataclass
from typing import Optional


from src.utils.config import (
    MAX_SEARCH_DEPTH,
    CONFIDENCE_THRESHOLD,
)
from src.utils.logger import logger
from src.capturer.screen_capture import Screenshot, crop_region_from_image
from src.grounding.planner import Planner
from src.grounding.grounder import Grounder, GroundingResult
from src.grounding.candidate_scorer import (
    ScoredCandidate,
    score_and_rank,
    apply_nms,
    dilate_bbox,
)
import concurrent.futures


@dataclass
class GroundingOutput:
    """Final output of the ScreenSeekeR pipeline."""
    success: bool
    screen_x: int              # Absolute screen pixel X to click
    screen_y: int              # Absolute screen pixel Y to click
    confidence: float
    search_depth: int          # How many recursive levels were needed
    norm_bbox: list[float]     # Normalized bounding box of detected element
    reasoning: str             # Explanation of how the element was found


class ScreenSeekeR:
    """
    The full ScreenSeekeR visual grounding pipeline.

    Usage:
        seeker = ScreenSeekeR()
        result = seeker.ground("Notepad icon", screenshot)
        if result.success:
            pyautogui.doubleClick(result.screen_x, result.screen_y)
    """

    def __init__(self) -> None:
        self._planner = Planner()
        self._grounder = Grounder()
        # Positional Memory: cache successful target locations (absolute pixels)
        self._cache: dict[str, tuple[int, int]] = {}
        # The screenshot, not a configuration constant, is the coordinate
        # authority.  This avoids stale coordinates when Windows DPI, monitor,
        # or resolution changes.
        self._desktop_size: tuple[int, int] | None = None
        logger.info("ScreenSeekeR pipeline initialized with Positional Memory")

    def ground(
        self,
        target_description: str,
        screenshot: Screenshot,
        depth: int = 0,
        region_offset: tuple[float, float] = (0.0, 0.0),
        region_scale: tuple[float, float] = (1.0, 1.0),
    ) -> GroundingOutput:
        """
        Ground a UI element described in natural language.

        Implements the recursive ScreenSeekeR search algorithm.

        Args:
            target_description: Natural language description of the target
            screenshot: Current screenshot (may be cropped sub-region in recursion)
            depth: Current recursion depth (0 = full desktop)
            region_offset: (x_offset, y_offset) in normalized screen coords
                           (where this screenshot starts in the full screen)
            region_scale: (x_scale, y_scale) scaling factors for coordinate conversion

        Returns:
            GroundingOutput with absolute screen coordinates for clicking
        """
        if depth > MAX_SEARCH_DEPTH:
            logger.warning(f"Max search depth {MAX_SEARCH_DEPTH} reached without finding target")
            return _failure_output()

        if depth == 0:
            self._desktop_size = (screenshot.width, screenshot.height)

        logger.info(f"ScreenSeekeR depth={depth}: searching for '{target_description}'")

        # ── Stage 0: Check Positional Memory Cache (Fast Path) ───────────────
        if depth == 0 and target_description in self._cache:
            logger.info("Target found in Positional Memory cache. Verifying...")
            cached_result = self._verify_cache(target_description, screenshot)
            if cached_result:
                return cached_result
            logger.warning("Cache verification failed. Target moved. Falling back to full search.")
            del self._cache[target_description]

        # ── Stage 1: Planner → candidate regions ─────────────────────────────
        candidates = self._planner.infer_positions(target_description, screenshot)

        if not candidates:
            logger.warning("Planner returned no candidates")
            return _failure_output()

        # ── Stage 2: Grounder → score each candidate ───────────
        groundings = [None] * len(candidates)
        
        def _process_candidate(i: int, candidate):
            logger.debug(f"  Grounding candidate {i+1}/{len(candidates)}: {candidate.bbox}")
            # Expand the bounding box to make the cropped patch (batch) bigger
            # Note: dilate_bbox will be updated to use dynamic sizing
            expanded_bbox = dilate_bbox(candidate.bbox, factor=1.5)

            patch, pixel_bbox = crop_region_from_image(
                image=screenshot.image,
                norm_bbox=expanded_bbox,
                screen_w=screenshot.width,
                screen_h=screenshot.height,
            )
            result = self._grounder.ground(target_description, patch)
            if result.found:
                logger.debug(
                    f"  ✓ Candidate {i+1}: found=True conf={result.confidence:.2f} "
                    f"center=({result.center_x:.3f},{result.center_y:.3f})"
                )
            return result

        # Run sequentially (max_workers=1) to prevent backend (e.g. SBG Gateway) from crashing under concurrent load
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future_to_idx = {
                executor.submit(_process_candidate, i, c): i 
                for i, c in enumerate(candidates)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    groundings[idx] = future.result()
                except Exception as e:
                    logger.error(f"Error grounding candidate {idx+1}: {e}")
                    # Create a dummy failed result
                    groundings[idx] = GroundingResult(False, 0.0, 0.0, 0.0, [0.0, 0.0, 0.0, 0.0], str(e))

        # ── Scoring and NMS ───────────────────────────────────────────────────
        scored = score_and_rank(candidates, groundings)
        scored = apply_nms(scored)

        if not scored:
            logger.warning("No candidates survived after scoring/NMS")
            # Recurse with fallback: search all 3 default regions
            return self._recurse_fallback(target_description, screenshot, depth)

        best = scored[0]
        logger.info(
            f"Best candidate: score={best.combined_score:.3f} "
            f"conf={best.grounding.confidence:.2f} "
            f"center=({best.screen_center_x:.3f},{best.screen_center_y:.3f})"
        )

        # ── Stage 3: Accept or recurse ────────────────────────────────────────
        if best.grounding.confidence >= CONFIDENCE_THRESHOLD:
            # Convert normalized coords to absolute screen pixels
            abs_x, abs_y = self._to_screen_pixels(
                norm_x=best.screen_center_x,
                norm_y=best.screen_center_y,
                region_offset=region_offset,
                region_scale=region_scale,
                img_w=screenshot.width,
                img_h=screenshot.height,
            )

            logger.info(
                f"✅ ScreenSeekeR SUCCESS at depth={depth}: "
                f"pixel=({abs_x},{abs_y}) "
                f"confidence={best.grounding.confidence:.2f}"
            )
            
            # Cache the successful coordinates
            if depth == 0:
                self._cache[target_description] = (abs_x, abs_y)

            return GroundingOutput(
                success=True,
                screen_x=abs_x,
                screen_y=abs_y,
                confidence=best.grounding.confidence,
                search_depth=depth,
                norm_bbox=best.screen_bbox,
                reasoning=(
                    f"Depth {depth}: Planner→{best.candidate.reasoning}; "
                    f"Grounder→{best.grounding.reasoning}"
                ),
            )
        else:
            # Low confidence → recurse into the best candidate region
            logger.info(
                f"Confidence {best.grounding.confidence:.2f} < threshold {CONFIDENCE_THRESHOLD}. "
                f"Recursing into best candidate region..."
            )
            return self._recurse_into_candidate(
                target_description=target_description,
                screenshot=screenshot,
                best=best,
                depth=depth,
                region_offset=region_offset,
                region_scale=region_scale,
            )

    def _verify_cache(self, target_description: str, screenshot: Screenshot) -> Optional[GroundingOutput]:
        """Verify if the target is still at the cached location by grounding a 600x600 crop."""
        cached_x, cached_y = self._cache[target_description]
        
        # Create a 600x600 bounding box around the cached point
        box_size = 600
        left = max(0, cached_x - box_size // 2)
        top = max(0, cached_y - box_size // 2)
        right = min(screenshot.width, cached_x + box_size // 2)
        bottom = min(screenshot.height, cached_y + box_size // 2)
        
        norm_bbox = [
            left / screenshot.width,
            top / screenshot.height,
            right / screenshot.width,
            bottom / screenshot.height
        ]
        
        patch, pixel_bbox = crop_region_from_image(
            image=screenshot.image,
            norm_bbox=norm_bbox,
            screen_w=screenshot.width,
            screen_h=screenshot.height,
        )
        
        result = self._grounder.ground(target_description, patch)
        if result.found and result.confidence >= CONFIDENCE_THRESHOLD:
            # Map back to full screen
            abs_x = int(left + result.center_x * (right - left))
            abs_y = int(top + result.center_y * (bottom - top))
            
            # Update cache just in case it moved slightly
            self._cache[target_description] = (abs_x, abs_y)
            
            logger.info(f"✅ Cache hit confirmed: ({abs_x}, {abs_y})")
            return GroundingOutput(
                success=True,
                screen_x=abs_x,
                screen_y=abs_y,
                confidence=result.confidence,
                search_depth=0,
                norm_bbox=[0,0,0,0], # Ignored for cache hits
                reasoning="Positional Memory Cache Hit"
            )
        return None

    def _recurse_into_candidate(
        self,
        target_description: str,
        screenshot: Screenshot,
        best: ScoredCandidate,
        depth: int,
        region_offset: tuple[float, float],
        region_scale: tuple[float, float],
    ) -> GroundingOutput:
        """
        Zoom into the best candidate region and run ScreenSeekeR recursively.
        Implements Stage 3 (Recursive Search) of the paper.
        """
        from src.capturer.screen_capture import Screenshot as ScreenshotClass
        import io
        import base64

        # Instead of dilating the entire candidate bbox (which might contain multiple icons),
        # we zoom in with a microscopic 150x150 pixel box dead-centered on the AI's predicted coordinate.
        # This mathematically forces the next recursion depth to see ONLY the target icon, destroying VLM drift.
        norm_cx = best.screen_center_x
        norm_cy = best.screen_center_y
        
        # 150 pixels converted to normalized coordinates of the CURRENT region scale
        # Work in the dimensions of the captured image.  SCREEN_WIDTH and
        # SCREEN_HEIGHT used to be fixed at 1920x1080, which made recursion
        # crop the wrong area on a scaled or differently sized display.
        norm_w = (150.0 / screenshot.width) / region_scale[0]
        norm_h = (150.0 / screenshot.height) / region_scale[1]
        
        tight_bbox = [
            max(0.0, norm_cx - norm_w / 2),
            max(0.0, norm_cy - norm_h / 2),
            min(1.0, norm_cx + norm_w / 2),
            min(1.0, norm_cy + norm_h / 2)
        ]

        # Crop the highly zoomed-in region
        sub_image, pixel_coords = crop_region_from_image(
            image=screenshot.image,
            norm_bbox=tight_bbox,
            screen_w=screenshot.width,
            screen_h=screenshot.height,
        )

        # Encode the sub-image
        buf = io.BytesIO()
        sub_image.save(buf, format="PNG")
        sub_b64 = base64.b64encode(buf.getvalue()).decode()

        sub_screenshot = ScreenshotClass(
            image=sub_image,
            base64_png=sub_b64,
            width=sub_image.width,
            height=sub_image.height,
            region={"left": pixel_coords[0], "top": pixel_coords[1],
                    "width": pixel_coords[2]-pixel_coords[0],
                    "height": pixel_coords[3]-pixel_coords[1]},
        )

        # Calculate new offset and scale for coordinate conversion based on tight_bbox
        new_offset_x = region_offset[0] + tight_bbox[0] * region_scale[0]
        new_offset_y = region_offset[1] + tight_bbox[1] * region_scale[1]
        new_scale_x = region_scale[0] * (tight_bbox[2] - tight_bbox[0])
        new_scale_y = region_scale[1] * (tight_bbox[3] - tight_bbox[1])

        return self.ground(
            target_description=target_description,
            screenshot=sub_screenshot,
            depth=depth + 1,
            region_offset=(new_offset_x, new_offset_y),
            region_scale=(new_scale_x, new_scale_y),
        )

    def _recurse_fallback(
        self,
        target_description: str,
        screenshot: Screenshot,
        depth: int,
    ) -> GroundingOutput:
        """
        Last-resort fallback when no candidates score above threshold.
        Tries again with the full screenshot at a higher recursion depth.
        """
        if depth >= MAX_SEARCH_DEPTH:
            return _failure_output()

        logger.warning(f"Fallback: retrying full screenshot at depth {depth + 1}")
        return self.ground(
            target_description=target_description,
            screenshot=screenshot,
            depth=depth + 1,
        )

    def _to_screen_pixels(
        self,
        norm_x: float,
        norm_y: float,
        region_offset: tuple[float, float],
        region_scale: tuple[float, float],
        img_w: int,
        img_h: int,
    ) -> tuple[int, int]:
        """
        Convert normalized coordinates within a sub-region back to absolute screen pixels.

        At depth=0: simply multiply by the dimensions of the desktop capture.
        At depth>0: account for the region's offset and scale within the full screen
        """
        # Map from sub-region normalized → full screen normalized
        full_norm_x = region_offset[0] + norm_x * region_scale[0]
        full_norm_y = region_offset[1] + norm_y * region_scale[1]

        # Map to absolute pixels.  Never use a hard-coded 1920x1080 here:
        # Windows can change the desktop size with display scaling or a
        # different monitor.
        desktop_w, desktop_h = self._desktop_size or (img_w, img_h)
        abs_x = int(full_norm_x * desktop_w)
        abs_y = int(full_norm_y * desktop_h)

        # Clamp to screen bounds
        abs_x = max(0, min(desktop_w - 1, abs_x))
        abs_y = max(0, min(desktop_h - 1, abs_y))

        return abs_x, abs_y


def _failure_output() -> GroundingOutput:
    return GroundingOutput(
        success=False,
        screen_x=0,
        screen_y=0,
        confidence=0.0,
        search_depth=-1,
        norm_bbox=[0.0, 0.0, 0.0, 0.0],
        reasoning="Element not found after exhausting all search strategies",
    )
