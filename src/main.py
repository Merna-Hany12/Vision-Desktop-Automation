"""
Main entry point — orchestrates the full 10-post automation workflow.

Workflow per post:
  1. Minimize all windows → show desktop
  2. Capture desktop screenshot
  3. ScreenSeekeR: ground Notepad icon → (x, y) coordinates
  4. Save annotated screenshot
  5. Double-click to launch Notepad
  6. Wait for Notepad to open
  7. Type post content into Notepad text area
  8. Save as post_{id}.txt in output/
  9. Close Notepad
  10. Repeat

Error handling per post:
  - Grounding failure → retry up to MAX_GROUNDING_RETRIES
  - Notepad launch failure → re-ground and retry
  - Unexpected popup → detect and dismiss via Gemini
  - Save dialog issues → handle via keyboard navigation
  - Any fatal error → emergency close + continue to next post
"""

import sys
import time

from src.utils.config import validate_config, OUTPUT_DIR, MAX_GROUNDING_RETRIES
from src.utils.logger import logger
from src.capturer.screen_capture import capture_desktop
from src.grounding.screenseeker import ScreenSeekeR
from src.automation.mouse_keyboard import (
    double_click,
    type_text,
    press_hotkey,
    press_key,
    save_file_as,
    close_notepad,
    emergency_close,
    focus_desktop,
)
from src.automation.window_manager import (
    wait_for_window,
    is_notepad_open,
    handle_unexpected_popup,
    click_notepad_text_area,
)
from src.api.jsonplaceholder import fetch_posts, format_post, get_filename
from src.utils.annotator import annotate_and_save


# ── Target description for ScreenSeekeR ──────────────────────────────────────
# This works for any icon — not hard-coded to specific pixel locations
NOTEPAD_TARGET = (
    "The desktop shortcut that launches Windows Notepad. Identify it visually "
    "from its icon and visible label; do not select folders, documents, or "
    "taskbar icons."
)

# Annotated screenshot names (for the 3 deliverable screenshots)
_ANNOTATION_POSITIONS = ["topleft", "center", "bottomright"]


def main() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Vision-Based Desktop Automation — ScreenSeekeR")
    logger.info("=" * 60)

    # ── Pre-flight validation ─────────────────────────────────────────────────
    try:
        validate_config()
    except ValueError as e:
        logger.error(f"Configuration error:\n{e}")
        sys.exit(1)

    # ── Create output directory ───────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {OUTPUT_DIR}")

    # ── Fetch all posts upfront (fail fast if API is down) ────────────────────
    logger.info("Fetching posts from JSONPlaceholder API...")
    try:
        posts = fetch_posts(limit=10)
    except Exception as e:
        logger.error(f"Failed to fetch posts: {e}")
        sys.exit(1)

    logger.info(f"Ready to process {len(posts)} posts")

    # ── Initialize ScreenSeekeR pipeline ─────────────────────────────────────
    seeker = ScreenSeekeR()

    # ── Process each post ─────────────────────────────────────────────────────
    successful = 0
    failed = 0

    for post_index, post in enumerate(posts):
        post_id = post["id"]
        filename = get_filename(post)
        content = format_post(post)

        logger.info(f"\n{'─' * 50}")
        logger.info(f"Post {post_index + 1}/10 — id={post_id} — {filename}")
        logger.info(f"{'─' * 50}")

        post_success = False

        for attempt in range(1, MAX_GROUNDING_RETRIES + 1):
            try:
                logger.info(f"Attempt {attempt}/{MAX_GROUNDING_RETRIES}")

                # ── Step 1: Show desktop ──────────────────────────────────────
                focus_desktop()
                time.sleep(0.8)

                # Check for unexpected popups before grounding
                handle_unexpected_popup(capture_desktop)

                # ── Step 2: Capture screenshot ────────────────────────────────
                logger.info("Capturing desktop screenshot...")
                screenshot = capture_desktop()

                # ── Step 3: Ground Notepad icon ───────────────────────────────
                logger.info("Running ScreenSeekeR grounding pipeline...")
                grounding_result = seeker.ground(NOTEPAD_TARGET, screenshot)

                if not grounding_result.success:
                    logger.warning(
                        f"Grounding failed on attempt {attempt}. "
                        f"Reason: {grounding_result.reasoning}"
                    )
                    if attempt < MAX_GROUNDING_RETRIES:
                        logger.info("Waiting 2 seconds before retry...")
                        time.sleep(2.0)
                    continue

                logger.info(
                    f"✅ Grounding SUCCESS: pixel=({grounding_result.screen_x},{grounding_result.screen_y}) "
                    f"confidence={grounding_result.confidence:.0%} "
                    f"depth={grounding_result.search_depth}"
                )

                # ── Step 4: Save annotated screenshot (first 3 posts) ─────────
                if post_index < 3:
                    position_label = _ANNOTATION_POSITIONS[post_index]
                    save_name = f"icon_{position_label}"
                    annotate_and_save(
                        screenshot=screenshot.image,
                        grounding_output=grounding_result,
                        candidates=[],  # Candidates not stored at this level
                        save_name=save_name,
                        label=f"Post {post_id} — Icon {position_label}",
                    )

                # ── Step 5: Double-click to launch Notepad ────────────────────
                logger.info(f"Double-clicking Notepad icon at ({grounding_result.screen_x}, {grounding_result.screen_y})")
                double_click(grounding_result.screen_x, grounding_result.screen_y)

                # ── Step 6: Wait for Notepad to open ─────────────────────────
                if not wait_for_window("Notepad", timeout=6.0):
                    logger.warning("Notepad didn't open. Checking for popup...")
                    handle_unexpected_popup(capture_desktop)

                    # Try double-clicking again
                    logger.info("Retrying double-click...")
                    focus_desktop()
                    time.sleep(0.5)
                    double_click(grounding_result.screen_x, grounding_result.screen_y)

                    if not wait_for_window("Notepad", timeout=5.0):
                        raise RuntimeError("Notepad failed to open after 2 attempts")

                logger.info("Notepad is open ✓")
                time.sleep(0.5)

                # ── Step 7: Click text area and type content ──────────────────
                click_notepad_text_area()
                time.sleep(0.3)

                logger.info(f"Typing post content ({len(content)} chars)...")
                type_text(content)
                time.sleep(0.5)

                # ── Step 8: Save file ─────────────────────────────────────────
                logger.info(f"Saving as {filename}...")
                save_file_as(filename, OUTPUT_DIR)

                # ── Step 9: Close Notepad ─────────────────────────────────────
                logger.info("Closing Notepad...")
                close_notepad()
                time.sleep(1.0)

                # Verify Notepad is closed
                if is_notepad_open():
                    logger.warning("Notepad still open, pressing Alt+F4 again")
                    press_hotkey("alt", "f4")
                    press_key("n")  # Don't Save
                    time.sleep(0.5)

                logger.info(f"✅ Post {post_id} completed successfully → {filename}")
                successful += 1
                post_success = True
                break

            except Exception as e:
                logger.error("Error on attempt {}: {}".format(attempt, str(e).replace('{','{{').replace('}','}}')), exc_info=True)

                # Emergency cleanup
                try:
                    handle_unexpected_popup(capture_desktop)
                    emergency_close()
                    time.sleep(1.0)
                except Exception:
                    pass

                if attempt < MAX_GROUNDING_RETRIES:
                    logger.info("Retrying in 2 seconds...")
                    time.sleep(2.0)

        if not post_success:
            logger.error(f"❌ Post {post_id} FAILED after {MAX_GROUNDING_RETRIES} attempts. Skipping.")
            failed += 1

    # ── Final Summary ──────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("AUTOMATION COMPLETE")
    logger.info(f"  ✅ Successful: {successful}/10")
    logger.info(f"  ❌ Failed:     {failed}/10")
    logger.info(f"  📁 Output:    {OUTPUT_DIR}")
    logger.info("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
