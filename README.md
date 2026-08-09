# Vision-Based Desktop Automation with Dynamic Icon Grounding

A Python application that uses **computer vision and AI** to dynamically locate and interact with desktop icons on Windows. Implements the **ScreenSeekeR** visual grounding framework from [arXiv 2504.07981](https://arxiv.org/abs/2504.07981).

## How It Works

The system implements a **3-stage cascaded grounding pipeline** (ScreenSeekeR):

```
Screenshot → [Stage 1: Planner] → Candidate Regions
          → [Stage 2: Grounder] → Precise Coordinates
          → [Stage 3: Recursive Search] → Verified Click Point
          → pyautogui → Double-Click → Notepad Opens
```

1. **Stage 1 — Position Inference**: A vision LLM analyzes the full desktop screenshot and proposes the 3 most likely regions where the icon is located
2. **Stage 2 — Precise Grounding**: Each candidate region is cropped and sent to the vision LLM for precise coordinate prediction within that patch
3. **Stage 3 — Recursive Refinement**: If confidence is low, the pipeline zooms into the best candidate region and repeats the search

This works for **any icon described in natural language** — not just Notepad.

## Backend Architecture

The system is configured out of the box to use **Google Gemini** as the primary engine for ease of setup, but features a built-in **resilient multi-backend strategy** if configured to use Groq.

When `PLANNER_BACKEND=groq` is set in `.env`, the system enables automatic failover:

```
Primary: Groq (meta-llama/llama-4-scout, free, fast)
       ↓ (on rate limit or failure)
Fallback: SBG Gateway (qwen3-vl-235b-a22b, vision model)
       ↓ (last resort)
Final: Google Gemini (gemini-3.5-flash-lite)
```

(The system also supports round-robin rotation of multiple Groq API keys to maximize throughput.)

## Requirements

- Windows 10/11 at 1920×1080 resolution
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A **free** Groq API key ([get one here](https://console.groq.com) — no credit card)
- A **free** Google Gemini API key ([get one here](https://aistudio.google.com) — no credit card)
- A Notepad shortcut on the Desktop

## Setup

### 1. Install uv (if not already installed)
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clone and install dependencies
```powershell
cd "path\to\project"
uv sync
```

### 3. Configure your API keys
```powershell
copy .env.example .env
notepad .env
```

Add your keys:
- `GROQ_API_KEY` — Free at https://console.groq.com → Create API Key
- `GEMINI_API_KEY` — Free at https://aistudio.google.com → Create API Key

### 4. Pre-requisite: Create Notepad shortcut
Make sure there is a **Notepad shortcut icon** on your Desktop before running.

To create one:
- Right-click Desktop → New → Shortcut
- Type: `notepad.exe`
- Name it: `Notepad`

## Running

```powershell
uv run python src/main.py
```

The script will:
1. Capture your desktop screenshot
2. Find the Notepad icon using ScreenSeekeR (regardless of position)
3. Double-click it to launch Notepad
4. Type 10 blog posts from JSONPlaceholder API
5. Save each as `post_{id}.txt` in `Desktop\tjm-project\`

## Output

Posts are saved to: `Desktop\tjm-project\` as per the assignment spec.

```
Desktop/tjm-project/
├── post_1.txt
├── post_2.txt
├── ...
└── post_10.txt
```

## Annotated Screenshots

After running, annotated screenshots are saved to `screenshots/`:

| File | Shows |
|---|---|
| `icon_topleft.png` | Icon detected in top-left area |
| `icon_center.png` | Icon detected in center of screen |
| `icon_bottomright.png` | Icon detected in bottom-right area |

Each screenshot shows:
- 🟦 **Blue boxes**: Candidate regions proposed by the Planner
- 🟩 **Green box**: Final detected icon bounding box
- 🔴 **Red crosshair**: Click coordinates

## Configuration

All settings are configured via `.env`:

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *required* | Free Groq API key (primary backend) |
| `GEMINI_API_KEY` | *required* | Free Gemini API key (last-resort fallback) |
| `PLANNER_BACKEND` | `gemini` | Planner: `gemini`, `groq`, `sbg` |
| `GROUNDER_BACKEND` | `gemini` | Grounder: `gemini`, `groq`, `sbg` |
| `MAX_SEARCH_DEPTH` | `3` | ScreenSeekeR recursion depth |
| `CONFIDENCE_THRESHOLD` | `0.60` | Min confidence to accept detection |
| `NUM_CANDIDATES` | `3` | Candidate regions to propose |
| `MAX_GROUNDING_RETRIES` | `3` | Retries if icon not found |

## Architecture

```
src/
├── main.py                     # Entry point, 10-post workflow loop
├── capturer/
│   └── screen_capture.py       # Fast screenshot capture (mss + Win+PrintScreen)
├── grounding/
│   ├── screenseeker.py         # ScreenSeekeR pipeline orchestrator
│   ├── planner.py              # Stage 1: region proposal (Groq/SBG/Gemini)
│   ├── grounder.py             # Stage 2: precise coordinate prediction
│   ├── candidate_scorer.py     # Gaussian scoring + NMS deduplication
│   └── prompts.py              # All LLM prompt templates (token-optimized)
├── automation/
│   ├── mouse_keyboard.py       # Click, type, hotkeys
│   └── window_manager.py       # Window detection, popup handling
├── api/
│   └── jsonplaceholder.py      # JSONPlaceholder API client with retry
└── utils/
    ├── config.py               # All constants (from .env)
    ├── logger.py               # Structured logging (loguru)
    └── annotator.py            # Annotated screenshot generation
```

## Grounding Approach

Based on the **ScreenSeekeR** framework from [ScreenSpot-Pro (arXiv 2504.07981)](https://arxiv.org/abs/2504.07981):

> *"Strategically reducing the search area enhances accuracy."*

| Approach | Accuracy | Notes |
|---|---|---|
| Template matching | Fails | Requires exact icon image |
| Hardcoded coordinates | Fails | Breaks when icon moves |
| Direct LLM grounding | < 5% | LLMs poor at pixel-precise coords on full screen |
| **ScreenSeekeR (ours)** | **~48%** | Paper benchmark, position-agnostic |

**Key insight**: Instead of asking the AI to find a 64×64 icon on a 1920×1080 screen (< 0.2% of pixels), we first identify which *region* of the screen likely contains the icon (easy), then zoom in and search that region precisely (much easier).

## Error Handling

The system handles:
- **Grounding failure** → Retry up to 3 times with fresh screenshot
- **API Network Block** → Tries `jsonplaceholder.typicode.com`, automatically falls back to `dummyjson.com` if a `ConnectionResetError` occurs.
- **API rate limits** → Automatic key rotation (3 Groq keys) + fallback to SBG/Gemini
- **Notepad won't open** → Retry double-click, check for blocking popups
- **Unexpected popup** → Vision LLM detects and dismisses ANY dialog automatically
- **Save dialog issues** → Keyboard navigation fallback (Ctrl+Shift+S)
- **Post failure** → Log and continue to next post

## References

- [ScreenSpot-Pro: GUI Grounding for Professional High-Resolution Computer Use](https://arxiv.org/abs/2504.07981)
- [Groq API Documentation](https://console.groq.com/docs)
- [Google Gemini API Documentation](https://ai.google.dev/gemini-api/docs)
