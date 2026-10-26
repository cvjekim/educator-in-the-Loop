"""
Trend archive manager.

Naming convention : {Number}_{Category}_{YYYYMMDD}_{Topic}.md
Categories        : Vision | AI | Paper | Article | News | Model | LLM | Agent
Retention limit   : 1,000 files (oldest deleted first by YYYYMMDD in filename)
"""

from __future__ import annotations

import re
from pathlib import Path

TRENDS_DIR = Path("data/trends")
MAX_FILES = 1_000
VALID_CATEGORIES = {"Vision", "AI", "Paper", "Article", "News", "Model", "LLM", "Agent"}
_FILENAME_RE = re.compile(r"^(\d{4})_(Vision|AI|Paper|Article|News|Model|LLM|Agent)_(\d{8})_.+\.md$")


def next_number() -> str:
    """Return the next 4-digit zero-padded file number."""
    existing = sorted(TRENDS_DIR.glob("*.md"))
    if not existing:
        return "0001"
    last = existing[-1].name
    m = _FILENAME_RE.match(last)
    n = int(m.group(1)) + 1 if m else 1
    return f"{n:04d}"


def enforce_limit() -> None:
    """Delete oldest trend files if the archive exceeds MAX_FILES."""
    files = sorted(TRENDS_DIR.glob("*.md"), key=_sort_key)
    while len(files) > MAX_FILES:
        files.pop(0).unlink()


def save_trend(category: str, date: str, topic: str, content: str) -> Path:
    """
    Write a new trend file, auto-assigning its number.
    Enforces the 1,000-file limit after writing.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of {VALID_CATEGORIES}.")

    TRENDS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{next_number()}_{category}_{date}_{topic}.md"
    path = TRENDS_DIR / filename
    path.write_text(content, encoding="utf-8")
    enforce_limit()
    return path


def select_trends_for_topic(topic: str, n: int = 2) -> list[dict]:
    """
    Scan data/trends/ and return the n most relevant trend dicts for the topic.
    Relevance scoring is a TODO (LLM-based or keyword match).
    """
    files = list(TRENDS_DIR.glob("*.md"))
    # TODO: score files by relevance to `topic` and return top n
    return [_parse_trend_file(f) for f in files[:n]]


def _sort_key(path: Path) -> str:
    m = _FILENAME_RE.match(path.name)
    return m.group(3) if m else ""   # sort by YYYYMMDD


def _parse_trend_file(path: Path) -> dict:
    """Return a dict with the trend file's metadata fields."""
    content = path.read_text(encoding="utf-8")
    data: dict = {"filename": path.name, "raw": content}
    for line in content.splitlines():
        for key in ("Number", "Date", "Topic", "Category", "Summary", "Source URL"):
            if line.startswith(f"- {key}:"):
                data[key.lower().replace(" ", "_")] = line.split(":", 1)[1].strip()
    return data
