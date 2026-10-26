"""
GitHub REST API crawler.
Fetches README.md and source files from a student's public repository.
Requires GITHUB_TOKEN in environment for higher rate limits (5000 req/hr vs 60).
"""

from __future__ import annotations

import base64
import os
from pathlib import PurePosixPath

import requests
from dotenv import load_dotenv

load_dotenv()

_TOKEN = os.getenv("GITHUB_TOKEN", "")
_HEADERS = {"Authorization": f"token {_TOKEN}"} if _TOKEN else {}
_API_BASE = "https://api.github.com"

# Only collect text-readable source files; skip images/binaries
_SUPPORTED_SUFFIXES = {".py", ".ipynb", ".md", ".txt", ".csv", ".json", ".yaml", ".yml"}
_MAX_FILE_BYTES = 50_000   # 50 KB per file — avoid context overflow
_MAX_FILES = 20            # Max files collected per repo


def _get(url: str) -> dict | list | None:
    """GET request with error handling. Returns None on failure."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def get_repo_tree(github_id: str, repo_name: str) -> list[dict]:
    """
    Return the flat file tree of the repository.
    Each entry: {"path": str, "type": "blob"|"tree", "size": int}
    """
    url  = f"{_API_BASE}/repos/{github_id}/{repo_name}/git/trees/HEAD?recursive=1"
    data = _get(url)
    if not data or "tree" not in data:
        return []
    return [item for item in data["tree"] if item.get("type") == "blob"]


def get_file_content(github_id: str, repo_name: str, path: str) -> str:
    """Fetch a single file's decoded text content via the Contents API."""
    url  = f"{_API_BASE}/repos/{github_id}/{repo_name}/contents/{path}"
    data = _get(url)
    if not data or data.get("encoding") != "base64":
        return ""
    try:
        raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return raw[:_MAX_FILE_BYTES]
    except Exception:
        return ""


def crawl_repo(entry: dict) -> dict:
    """
    Crawl a single student's repository.

    Returns:
        {
            "readme": str,
            "files": [{"path": str, "content": str}],
            "has_required_outputs": bool,   # README exists + at least one source file
        }
    """
    github_id = entry.get("github_id", "")
    repo_name = entry.get("repo_name", "")

    tree = get_repo_tree(github_id, repo_name)
    if not tree:
        return {"readme": "", "files": [], "has_required_outputs": False}

    readme_content = ""
    source_files: list[dict] = []

    for item in tree:
        path   = item.get("path", "")
        suffix = PurePosixPath(path).suffix.lower()
        name   = PurePosixPath(path).name.lower()

        # Always collect README
        if name in ("readme.md", "readme.txt", "readme"):
            readme_content = get_file_content(github_id, repo_name, path)
            continue

        # Collect supported source files up to _MAX_FILES limit
        if suffix in _SUPPORTED_SUFFIXES and len(source_files) < _MAX_FILES:
            content = get_file_content(github_id, repo_name, path)
            if content.strip():
                source_files.append({"path": path, "content": content})

    has_required = bool(readme_content) and len(source_files) > 0

    return {
        "readme": readme_content,
        "files": source_files,
        "has_required_outputs": has_required,
    }
