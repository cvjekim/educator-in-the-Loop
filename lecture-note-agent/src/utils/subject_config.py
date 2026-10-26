"""
Subject configuration parser.

Reads subjects/{subject}/configuration.md and maps logical references
(syllabus, detail_plan, previous_notes, references) to real filesystem paths.
"""

from __future__ import annotations

import re
from pathlib import Path

_WEEK_RE = re.compile(r"-\s*week\s+(\d+)\s*:(.*)", re.IGNORECASE)
_PREV_NOTES_RE = re.compile(r"-\s*/prev\w*-lecture-notes", re.IGNORECASE)
_REFERENCES_RE = re.compile(r"-\s*/references\b", re.IGNORECASE)
_REF_LINK_RE = re.compile(r"-\s*references\s+link", re.IGNORECASE)


def load_config(subject: str) -> dict:
    """
    Parse subjects/{subject}/configuration.md and return a structured dict.

    Returns:
        {
            "syllabus": str | None,
            "detail_plan": str | None,
            "previous_note_paths": {week_number: path, ...},
            "reference_paths": [path, ...],
        }
    """
    config_path = Path("subjects") / subject / "configuration.md"
    if not config_path.exists():
        raise FileNotFoundError(f"No configuration found for subject '{subject}'.")

    lines = config_path.read_text(encoding="utf-8").splitlines()
    result: dict = {
        "syllabus": None,
        "detail_plan": None,
        "previous_note_paths": {},
        "reference_paths": [],
    }

    section: str | None = None  # "previous_notes" | "references" | None
    prev_folder: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # --- Section detection ---
        if _PREV_NOTES_RE.match(stripped):
            section = "previous_notes"
            continue
        if _REFERENCES_RE.match(stripped):
            section = "references"
            continue
        if _REF_LINK_RE.match(stripped):
            section = None
            continue

        # --- Top-level fields (no active section) ---
        if section is None:
            if "sylabus" in stripped.lower() and ":" in stripped:
                val = stripped.split(":", 1)[1].strip()
                if val:
                    result["syllabus"] = val
            elif stripped.lower().startswith("- detail_plan") and ":" in stripped:
                val = stripped.split(":", 1)[1].strip()
                result["detail_plan"] = _resolve_path(val, subject)
            continue

        # --- Previous notes section ---
        if section == "previous_notes":
            m = _WEEK_RE.match(stripped)
            if m:
                week_num = int(m.group(1))
                filename = m.group(2).strip()
                if filename and prev_folder:
                    result["previous_note_paths"][week_num] = str(
                        Path(prev_folder) / filename
                    )
            elif "folder path" in stripped.lower() and ":" in stripped:
                prev_folder = stripped.split(":", 1)[1].strip()
            continue

        # --- References section ---
        if section == "references":
            if ":" in stripped and stripped.startswith("-"):
                val = stripped.split(":", 1)[1].strip()
                if val and not val.startswith("http"):
                    p = Path(val)
                    if p.is_dir():
                        result["reference_paths"].extend(
                            str(f) for f in sorted(p.rglob("*.pdf"))
                        )
                        result["reference_paths"].extend(
                            str(f) for f in sorted(p.rglob("*.pptx"))
                        )
                    elif p.is_file():
                        result["reference_paths"].append(str(p))

    return result


def _resolve_path(val: str, subject: str) -> str:
    """Resolve relative paths (./...) relative to the subject folder."""
    if val.startswith("./"):
        return str(Path("subjects") / subject / val[2:])
    return val
