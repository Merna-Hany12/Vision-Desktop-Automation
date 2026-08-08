"""
All LLM prompt templates for the ScreenSeekeR pipeline.
Optimized for minimal token usage while preserving accuracy.
"""

# ── Stage 1: Planner Prompts ──────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = (
    "GUI grounding assistant for Windows desktops. "
    "Locate UI elements in screenshots. "
    "Desktop icons: grid layout, text label below, ~64-96px at 1080p. "
    "Output ONLY valid JSON starting with { and ending with }. "
    "CRITICAL: You are FORBIDDEN from using <think> blocks. Start your response immediately with { and output nothing else."
)

PLANNER_USER_PROMPT_TEMPLATE = (
    'Find this element in the Windows desktop screenshot:\n'
    'TARGET: "{target_description}"\n\n'
    'Return up to {num_candidates} candidate regions.\n'
    'CRITICAL: Candidate regions MUST be small, tight bounding boxes around the icon itself (e.g. width and height around 0.10). Do NOT return massive regions or the entire screen.\n'
    'If target NOT found: return {num_candidates} diverse fallback regions '
    '(1 on FAR LEFT edge x<0.15, 1 on FAR RIGHT edge x>0.85, 1 random).\n\n'
    '{{"target_found":true/false,"reasoning":"brief","candidates":['
    '{{"bbox":[x1,y1,x2,y2],"confidence":0.0-1.0,"reasoning":"brief"}}'
    ']}}\n'
    'bbox: normalized 0.0-1.0. Order by confidence desc.'
)


# ── Stage 2: Grounder Prompts ──────────────────────────────────────────────────

GROUNDER_SYSTEM_PROMPT = (
    "Precise GUI element locator for cropped image patches. "
    "Return CENTER coordinates of the target relative ONLY to this specific cropped patch. "
    "0.0 is the top/left edge of the patch, 1.0 is the bottom/right edge. "
    "DO NOT output global full-screen coordinates. "
    "Output ONLY valid JSON. "
    "CRITICAL: You are FORBIDDEN from using <think> blocks. Start your response immediately with { and output nothing else."
)
GROUNDER_USER_PROMPT_TEMPLATE = (
    'Find this element in the CROPPED image patch:\n'
    'TARGET: "{target_description}"\n\n'
    '- May be partially cut off at edges; estimate center.\n'
    '- Match strictly by shape, color, and text label.\n'
    '- If the target is NOT completely or partially visible in this patch, you MUST set "found": false.\n'
    '- CRITICAL: "confidence" MUST be strictly calibrated. Output > 0.85 ONLY if you are 100% certain it matches the description exactly. If it is just a vaguely similar icon (e.g. a yellow folder instead of a blue notebook), output confidence < 0.30.\n\n'
    '{{"found":true/false,"confidence":0.0-1.0,'
    '"center_x":float,"center_y":float,'
    '"bbox":[x1,y1,x2,y2],"reasoning":"brief"}}\n'
    'Coords MUST be relative to the width/height of this specific cropped patch (0.0-1.0). found=false ONLY if target is entirely missing from this patch.'
)


# ── Stage 3: Verification Prompt ──────────────────────────────────────────────

VERIFIER_PROMPT_TEMPLATE = (
    'Verify detection: TARGET="{target_description}" '
    'at center=({center_x:.3f},{center_y:.3f}).\n'
    'Is target visible there?\n'
    '{{"verified":true/false,"confidence":0.0-1.0,'
    '"correction_needed":true/false,'
    '"corrected_center_x":float_or_null,'
    '"corrected_center_y":float_or_null,'
    '"reasoning":"brief"}}'
)


# ── Popup/Dialog Detection Prompt ─────────────────────────────────────────────

POPUP_DETECTION_PROMPT = (
    'Detect any blocking dialog/popup.\n'
    'Look for: modal dialogs, error/warning, save confirmations, UAC.\n'
    '{{"popup_detected":true/false,'
    '"popup_type":"save_dialog/error/uac/confirmation/none",'
    '"action_needed":"click_yes/click_no/click_ok/click_cancel/press_enter/none",'
    '"button_description":"text or null",'
    '"reasoning":"brief"}}'
)
