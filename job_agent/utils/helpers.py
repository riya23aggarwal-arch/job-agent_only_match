"""
Shared utility functions for job-agent.
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Text Utilities ─────────────────────────────────────────────────────────


def clean_text(text: str) -> str:
    """Normalize whitespace in scraped or pasted text."""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def truncate(text: str, max_chars: int = 3000) -> str:
    """Truncate text to max_chars, ending at a word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] + "…" if last_space > 0 else truncated


def extract_years_experience(text: str) -> Optional[int]:
    """Extract the minimum years of experience required from a job description."""
    patterns = [
        r"(\d+)\+?\s*years? of experience",
        r"(\d+)\+?\s*years? experience",
        r"minimum (\d+)\+?\s*years?",
        r"at least (\d+)\+?\s*years?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return int(match.group(1))
    return None


def extract_salary(text: str) -> Optional[str]:
    """Try to extract salary range from job description."""
    patterns = [
        r"\$[\d,]+\s*[-–]\s*\$[\d,]+",              # $120,000 - $160,000
        r"\$[\d,.]+[kK]\s*[-–]\s*\$[\d,.]+[kK]",    # $120k - $160k
        r"[\d,]+\s*[-–]\s*[\d,]+\s*per year",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def is_remote(location: str, description: str = "") -> bool:
    """Detect if a job is remote."""
    text = (location + " " + description).lower()
    return any(kw in text for kw in ["remote", "work from home", "wfh", "distributed team", "fully remote"])


# ── JSON Utilities ─────────────────────────────────────────────────────────


def safe_json_loads(s: str, default=None) -> Any:
    """Parse JSON string, returning default on failure."""
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def pretty_json(obj: Any) -> str:
    """Pretty-print a JSON-serializable object."""
    return json.dumps(obj, indent=2, default=str)


# ── ID Utilities ───────────────────────────────────────────────────────────


def make_job_id(url: str, company: str = "", role: str = "") -> str:
    """Generate a stable short ID for a job from its URL."""
    key = (url or company + role).encode("utf-8")
    return hashlib.sha1(key).hexdigest()[:12].upper()


# ── Date Utilities ─────────────────────────────────────────────────────────


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def format_date(iso_str: str) -> str:
    """Format ISO date string to human-readable."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return iso_str[:10]


def days_ago(iso_str: str) -> int:
    """Return how many days ago this ISO date string was."""
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.utcnow() - dt
        return delta.days
    except ValueError:
        return 0


# ── File Utilities ─────────────────────────────────────────────────────────


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_file(path: Path, content: str) -> Path:
    """Write text content to file, creating parent directories."""
    path = Path(path)
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def read_file(path: Path) -> str:
    """Read text file content, return empty string if not found."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# ── Logging Setup ──────────────────────────────────────────────────────────


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None):
    """Configure logging for the job-agent system."""
    handlers: List[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        ensure_dir(Path(log_file).parent)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


# ── Display Utilities ──────────────────────────────────────────────────────


def score_bar(score: int, width: int = 20) -> str:
    """Return a simple ASCII progress bar for a score 0-100."""
    filled = int((score / 100) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {score:3d}"


def decision_emoji(decision: str) -> str:
    return {
        "apply_now": "🟢",
        "review": "🟡",
        "discard": "🔴",
    }.get(decision, "⚪")


def status_emoji(status: str) -> str:
    return {
        "shortlisted": "📋",
        "ready_to_apply": "✅",
        "applied": "📤",
        "interview": "🎤",
        "offer": "🎉",
        "rejected": "❌",
    }.get(status, "❓")
