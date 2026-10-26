"""
Material-loading helpers for the Written Exam Agent.
Reads syllabus.md and materials/ (PDF / Markdown / txt) for a given subject.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

# written-exam-agent/ (two levels up from src/materials/)
BASE_DIR = Path(__file__).resolve().parents[2]
SUBJECTS_DIR = BASE_DIR / "subjects"


def load_syllabus(subject_name: str) -> str:
    """
    Load ``syllabus.md`` for the given subject.
    Returns an empty string (not an error) when the file is absent.
    """
    path = SUBJECTS_DIR / subject_name / "syllabus.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_materials(subject_name: str) -> str:
    """
    Concatenate all lecture materials found in
    ``subjects/<subject_name>/materials/``.

    Supported formats
    -----------------
    * ``.pdf``  — text extracted via *pdfplumber*
    * ``.md`` / ``.txt`` — read directly as UTF-8

    Files are processed in alphabetical order.
    Returns an empty string when the directory does not exist.
    """
    materials_dir = SUBJECTS_DIR / subject_name / "materials"
    if not materials_dir.exists():
        return ""

    chunks: list[str] = []
    for file_path in sorted(materials_dir.iterdir()):
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            text = _parse_pdf(file_path)
        elif suffix in (".md", ".txt"):
            text = file_path.read_text(encoding="utf-8")
        else:
            continue  # ignore unsupported formats (images, pptx, etc.)

        if text.strip():
            chunks.append(f"[파일: {file_path.name}]\n{text.strip()}")

    return "\n\n---\n\n".join(chunks)


def _parse_pdf(path: Path) -> str:
    """Extract text from a PDF using pdfplumber; returns an error tag on failure."""
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join(
                (page.extract_text() or "") for page in pdf.pages
            )
    except Exception as exc:  # noqa: BLE001
        return f"[PDF 파싱 오류: {exc}]"
