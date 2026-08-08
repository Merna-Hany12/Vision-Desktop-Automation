"""
Structured logging setup using loguru.
Provides file + console logging with color-coded levels.
"""

import sys
from pathlib import Path
from loguru import logger

# Remove default handler
logger.remove()

# ── Console handler — colored, human-readable ─────────────────────────────────
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    ),
    level="DEBUG",
    colorize=True,
)

# ── File handler — full detail, auto-rotated ──────────────────────────────────
_log_dir = Path(__file__).parent.parent.parent / "logs"
_log_dir.mkdir(exist_ok=True)

logger.add(
    _log_dir / "automation_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} — {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
)

__all__ = ["logger"]
