"""
Central configuration — all tunable constants in one place.
Loaded from environment variables (.env) with safe defaults.
"""

import os
from pathlib import Path
import itertools
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Screen Resolution ─────────────────────────────────────────────────────────
SCREEN_WIDTH: int = 1920
SCREEN_HEIGHT: int = 1080

# ── Gemini API ────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_PLANNER_MODEL: str = os.getenv("GEMINI_PLANNER_MODEL", "gemini-3.5-flash-lite")
GEMINI_GROUNDER_MODEL: str = os.getenv("GEMINI_GROUNDER_MODEL", "gemini-3.5-flash-lite")



# "gemini" → Google Gemini API
# "sbg"    → Custom SBG Gateway
# "groq"   → Groq API (fast, generous free tier, supports vision)
PLANNER_BACKEND: str = os.getenv("PLANNER_BACKEND", "gemini")
GROUNDER_BACKEND: str = os.getenv("GROUNDER_BACKEND", "gemini")

# ── SBG API ───────────────────────────────────────────────────────────────────
SBG_BASE_URL: str = os.getenv("SBG_BASE_URL", "")
SBG_API_KEY: str = os.getenv("SBG_API_KEY", "")
SBG_PLANNER_MODEL: str = os.getenv("SBG_PLANNER_MODEL", "anthropic.claude-sonnet-4-6")
SBG_GROUNDER_MODEL: str = os.getenv("SBG_GROUNDER_MODEL", "qwen.qwen3-vl-235b-a22b")

# ── Groq API ──────────────────────────────────────────────────────────────────
# Comma-separated list of keys for round-robin rotation to bypass rate limits
GROQ_API_KEYS: list[str] = [k.strip() for k in os.getenv("GROQ_API_KEY", "").split(",") if k.strip()]
_groq_key_cycle = itertools.cycle(GROQ_API_KEYS) if GROQ_API_KEYS else None

def get_next_groq_key() -> str:
    """Return the next Groq API key in a round-robin fashion."""
    if not _groq_key_cycle:
        return ""
    return next(_groq_key_cycle)

# Qwen3.6 is Groq's fast vision model
GROQ_PLANNER_MODEL: str = os.getenv("GROQ_PLANNER_MODEL", "qwen/qwen3.6-27b")
GROQ_GROUNDER_MODEL: str = os.getenv("GROQ_GROUNDER_MODEL", "qwen/qwen3.6-27b")

# ── ScreenSeekeR Parameters ───────────────────────────────────────────────────
# Number of candidate regions the planner proposes (paper: 3-5 is optimal)
NUM_CANDIDATES: int = int(os.getenv("NUM_CANDIDATES", "3"))

# Max recursive search depth (paper: depth 3 gives best accuracy/speed tradeoff)
MAX_SEARCH_DEPTH: int = int(os.getenv("MAX_SEARCH_DEPTH", "3"))

# Confidence threshold to accept a grounding result (0.0-1.0)
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.60"))

# Patch size for grounding model input (pixels) — paper: 1024 optimal for OS-Atlas-7B
REGROUND_PATCH_SIZE: int = 1024

# Scoring sigma — controls how quickly score decays with distance from center
# Value from ScreenSeekeR paper (Algorithm 1)
SIGMA: float = 0.3

# NMS IoU threshold — boxes overlapping more than this are deduplicated
NMS_IOU_THRESHOLD: float = 0.5

# Box dilation factor — expands small boxes to reduce boundary miss risk
BOX_DILATION_FACTOR: float = 1.2

# ── Automation Parameters ─────────────────────────────────────────────────────
# Max grounding retries per post before skipping
MAX_GROUNDING_RETRIES: int = int(os.getenv("MAX_GROUNDING_RETRIES", "3"))

# Seconds to wait after double-clicking for app to open
APP_LAUNCH_TIMEOUT: float = 5.0

# Seconds to wait between keystrokes (prevents dropped characters)
TYPING_INTERVAL: float = 0.02

# Seconds to pause between automation steps (prevents race conditions)
ACTION_DELAY: float = 0.5

# ── API ───────────────────────────────────────────────────────────────────────
JSONPLACEHOLDER_BASE_URL: str = "https://jsonplaceholder.typicode.com"
API_TIMEOUT: int = 15  # seconds

# ── Paths ─────────────────────────────────────────────────────────────────────
# Output directory for saved text files
_output_env = os.getenv("OUTPUT_DIR", "")
OUTPUT_DIR: Path = (
    Path(_output_env) if _output_env
    else Path.home() / "Desktop" / "tjm-project"
)

# Screenshots directory (for annotated deliverables)
SCREENSHOTS_DIR: Path = Path(__file__).parent.parent.parent / "screenshots"

# ── Validation ────────────────────────────────────────────────────────────────
def validate_config() -> None:
    """Raise early if critical config is missing."""
    backend = PLANNER_BACKEND
    if backend == "gemini" and not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not set.\n"
            "Get a FREE key at: https://aistudio.google.com\n"
            "Then add it to your .env file: GEMINI_API_KEY=your_key_here"
        )
    if backend == "groq" and not GROQ_API_KEYS:
        raise ValueError(
            "GROQ_API_KEY is not set.\n"
            "Get a FREE key at: https://console.groq.com\n"
            "Then add it to your .env file: GROQ_API_KEY=key1,key2,key3"
        )
