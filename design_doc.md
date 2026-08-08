# Design Document: Vision-Based Desktop Automation with Dynamic Icon Grounding

**Author:** Merna Hany  
**Date:** August 2026  
**Reference:** arXiv 2504.07981 — ScreenSpot-Pro: GUI Grounding for Professional High-Resolution Computer Use

---

## 1. Overview

This document describes the design of a Python-based desktop automation system that uses **computer vision and multimodal AI** to locate and interact with desktop icons on Windows 10/11 at 1920×1080 resolution.

### The Core Problem

Desktop icon positions are **not fixed**. Users move icons, change icon view modes, and rearrange the desktop. Any automation that depends on hardcoded coordinates or pre-stored template images will fail in production.

The solution is a system that locates icons the same way a human would: by **visually understanding** the screen and reasoning about where an icon is likely to be based on visual context — without any prior knowledge of its exact location.

### What the System Does

1. Captures a screenshot of the Windows desktop
2. Runs a **cascaded visual grounding pipeline** (ScreenSeekeR) to locate the target icon at any position
3. Double-clicks the icon to launch the application
4. Interacts with the launched application (Notepad)
5. Repeats for 10 iterations, typing blog post content fetched from a REST API

---

## 2. Assumptions

| Assumption | Rationale |
|---|---|
| Screen resolution: 1920×1080 | Specified in requirements |
| Primary monitor only | Multi-monitor detection adds complexity without benefit for the task |
| Notepad shortcut exists on desktop before running | Pre-requisite stated in requirements |
| Desktop is visible (no full-screen apps) | System calls `Win+D` to minimize all windows before each search |
| Internet connection available | Required for Gemini API and JSONPlaceholder API |
| Gemini API free tier | Generous daily quota (100+ calls/day), no credit card needed |
| Python 3.11+, uv installed | Standard modern Python tooling |

---

## 3. System Architecture

The system is organized into 5 independent components with clear interfaces:

```
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (main.py)                        │
│    Controls the 10-post loop: ground → launch → type → save     │
└────────────┬─────────────────┬──────────────────┬───────────────┘
             │                 │                  │
     ┌───────▼──────┐  ┌──────▼──────┐  ┌────────▼──────┐
     │   Capturer   │  │  ScreenSeeR │  │  Automator    │
     │  (mss lib)   │  │  (Grounding │  │ (pyautogui)   │
     │              │  │  Pipeline)  │  │               │
     │ capture_     │  │             │  │ double_click  │
     │ desktop()    │  │  Planner    │  │ type_text     │
     │ capture_     │  │  Grounder   │  │ save_file_as  │
     │ region()     │  │  Scorer     │  │ close_app     │
     └──────────────┘  └──────────────┘  └───────────────┘
                                │
                     ┌──────────▼──────────┐
                     │     API Client      │
                     │  (JSONPlaceholder)  │
                     │  fetch_posts()      │
                     └─────────────────────┘
```

**Why this separation?**
- Each component is independently testable
- The grounder backend is swappable (Gemini / Ollama / OS-Atlas) without touching the orchestrator
- The automation layer can be tested with mock coordinates

---

## 4. Grounding Strategy — ScreenSeekeR Pipeline

The grounding system directly implements the **ScreenSeekeR** algorithm from the ScreenSpot-Pro paper (arXiv 2504.07981). This is the intellectual core of the system.

### Why Visual Grounding?

Traditional approaches fail for this task:

| Approach | Why It Fails |
|---|---|
| Hardcoded coordinates | The icon moves — coordinates are stale immediately |
| Template matching (`cv2.matchTemplate`) | Requires storing the exact icon image; fails if icon skin/size changes |
| OCR (finding the "Notepad" text label) | Only works when the label is visible; fails for icon-only views |
| Windows API (`FindWindow`, `EnumWindows`) | Not visual; bypasses the grounding challenge entirely |
| Direct LLM coordinate prediction | Vision LLMs (including GPT-4o) score < 5% on grounding benchmarks |
| **ScreenSeekeR (proposed)** | **Position-agnostic, appearance-agnostic, 48.1% on ScreenSpot-Pro** |

### The ScreenSeekeR Algorithm (3 Stages)

**Stage 1 — Position Inference (Planner)**

A multimodal LLM (Gemini 2.5 Flash) analyzes the full 1920×1080 desktop screenshot and proposes **3 candidate regions** where the target is most likely located.

The planner uses its knowledge of Windows desktop conventions:
- Icons are arranged in a grid, typically starting top-left
- Icons have text labels below them
- Common neighboring icons (Recycle Bin, This PC) provide spatial cues

Prompt strategy: low temperature (0.2) for consistent spatial reasoning; structured JSON output for reliable parsing.

**Stage 2 — Precise Grounding (Grounder)**

Each candidate region is **cropped** from the original screenshot and sent to Gemini with a specialized grounding prompt. The model returns:
- Whether the target is visible in this patch
- The center coordinates (normalized 0.0–1.0)
- A confidence score
- Visual reasoning

The key insight from the paper: *"Strategically reducing the search area enhances accuracy."* A model that struggles on the full 1920×1080 image can accurately locate a 64×64 icon within a 300×300 crop.

**Stage 3 — Recursive Search + Scoring**

Candidates are scored using the **Gaussian-weighted centrality formula** from the paper:

```
score = planner_confidence × grounder_confidence × exp(-dist² / 2σ²)
```

Where `dist` is the distance from the grounder's prediction to the candidate center, and `σ = 0.3` (paper default).

Non-Maximum Suppression (NMS) removes overlapping candidates. If the best candidate's confidence is below threshold (0.55), the system **recurses** into the top region and repeats, up to `MAX_SEARCH_DEPTH=3`.

**Why this outperforms alternatives:**
- The planner's job is to *propose regions*, not *find pixels* — a task LLMs excel at
- The grounder's job is *precise localization* within a small crop — much easier than the full screen
- The recursive refinement progressively eliminates wrong areas
- The scoring formula prevents large, low-confidence regions from dominating

### Generalization

The `target_description` is a plain English string. Changing it from `"Notepad icon"` to `"Chrome browser shortcut"` or `"VS Code icon"` requires zero code changes. The system is **fully general**.

---

## 5. Tradeoffs

### Gemini API vs. Local Model

| Factor | Gemini API | Local Model (Ollama) |
|---|---|---|
| Cost | Free tier (generous quota) | Free (local compute) |
| RAM usage | ~50MB (Python only) | ~8GB (model weights) |
| Latency | 1–3s (network) | 5–15s (CPU inference) |
| Accuracy | Good (general vision) | Better (specialist GUI model) |
| Offline support | No | Yes |

**Decision:** Gemini API for 8GB RAM / CPU-only systems. The task (desktop icons at 1920×1080) is simpler than the professional environments in the paper, so Gemini's accuracy is sufficient.

### mss vs. PIL.ImageGrab

`mss` captures screenshots 3–5× faster than `PIL.ImageGrab` on Windows. During the demo where we loop 10 times, this makes a perceptible difference. Both return identical image quality.

### Clipboard paste vs. pyautogui.write()

`pyautogui.write()` sends individual keystrokes, which can drop characters at speed and fails on Unicode. Using `pyperclip.copy()` + `Ctrl+V` is 100× faster, handles all Unicode, and is more reliable.

---

## 6. Error Handling

### Error Classification and Response

| Error Class | Detection | Response |
|---|---|---|
| **Grounding failure** (icon not found) | `GroundingOutput.success == False` | Retry up to 3× with fresh screenshot |
| **Notepad won't open** | `wait_for_window()` timeout | Re-ground + retry double-click |
| **Unexpected popup** | Gemini analyzes screenshot for dialog | Gemini determines action (Enter/Escape/Yes/No/click button) |
| **Save dialog issues** | Window title polling | Keyboard navigation: type path → Enter |
| **File already exists** | Second Enter press after save | Accepts "overwrite?" prompt |
| **API network failure** | `requests.HTTPError` | Exponential backoff, 3 retries |
| **Fatal per-post error** | `Exception` catch-all | Emergency `Alt+F4`, log and continue |

### Key Robustness Feature: Popup Handling

The assignment specifically requires handling "unexpected pop-ups without knowing what they look like in advance." The system handles this by:

1. After any automation action, if the expected next state isn't reached, take a screenshot
2. Send the screenshot to Gemini with a popup-detection prompt
3. Gemini returns: `{popup_detected: true, action: "click_yes", button_description: "..."}`
4. The system clicks the appropriate button — even if it's never seen that dialog before

This is fundamentally different from hardcoded dialog handling because it works for **any** unexpected dialog.

---

## 7. Performance

| Operation | Expected Latency |
|---|---|
| Desktop screenshot (mss) | ~50ms |
| Gemini planner call | 1–3s |
| Gemini grounder call × 3 candidates | 3–9s |
| Scoring + NMS | <10ms |
| Mouse/keyboard automation | 2–4s |
| **Total per iteration (no recursion)** | **~7–16s** |
| **Total for 10 posts** | **~2–3 minutes** |

### Optimization Strategies (if more time available)
- **Caching**: If the desktop screenshot is visually similar to the previous one (pixel diff < 5%), reuse the last grounding result
- **Parallel grounding**: Send all 3 candidate patches to Gemini concurrently (async API calls)
- **Confidence learning**: After a successful run, cache the icon's approximate screen region and search there first next time

---

*Design document prepared in compliance with assessment requirements. Implementation follows this design exactly.*
