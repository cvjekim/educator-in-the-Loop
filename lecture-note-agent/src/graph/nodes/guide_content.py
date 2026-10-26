"""
Node: guide_content
Validates professor input and initialises pipeline progress tracking.

If the professor leaves guidelines blank, auto-extracts the week-specific
section from subjects/{subject}/guideline.pdf (기존주제, 보완/추가내용,
출처, 이론, 실습) and appends a summary of available materials from
configuration.md. The result is stored back into state["guidelines"] so
downstream nodes (draft_content, etc.) can use it as a prompt context.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import LectureState

# Matches "N주차:" or "N주차：" (full-width colon) at any indent
_WEEK_HEADER_RE = re.compile(r"(\d+)주차\s*[:：]")

# PDF page-footer artifacts to strip
_PAGE_ARTIFACT_RE = re.compile(
    r"^New\s+\d{4}-\d+.*강의\s*계획서\s*\d*\s*$|^\s*\d+\s*$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Public node function
# ---------------------------------------------------------------------------

def guide_content(state: LectureState) -> LectureState:
    guidelines = state.get("guidelines", "").strip()

    if not guidelines:
        guidelines = _auto_extract_guidelines(
            state["subject"], state["week"], state["topic"]
        )

    return {
        **state,
        "guidelines": guidelines,
        "current_stage": "guide_content",
        "overall_progress": 15,
        "status_message": f"{state['week']}주차 — {state['topic']} 지침 준비 완료",
    }


# ---------------------------------------------------------------------------
# Auto-extraction helpers
# ---------------------------------------------------------------------------

def _auto_extract_guidelines(subject: str, week: int, topic: str) -> str:
    """
    Build a prompt-style guidelines string from:
      1. The week section in subjects/{subject}/guideline.pdf
      2. Available materials listed in subjects/{subject}/configuration.md
    """
    parts: list[str] = []

    # 1. Week-specific section from guideline.pdf
    guideline_pdf = Path("subjects") / subject / "guideline.pdf"
    if guideline_pdf.exists():
        pdf_text = _read_pdf(guideline_pdf)
        week_section = _extract_week_section(pdf_text, week)
        if week_section:
            parts.append(f"## 강의계획서 지침 ({week}주차: {topic})\n\n{week_section}")

    # 2. Available materials from configuration.md
    config_summary = _config_summary(subject, week)
    if config_summary:
        parts.append(f"## 활용 가능한 강의 자료\n\n{config_summary}")

    if not parts:
        return (
            f"강의 주제: {topic}\n"
            "강의계획서 정보가 없습니다. 주제에 맞는 강의노트를 작성해 주세요."
        )

    return "\n\n---\n\n".join(parts)


def _read_pdf(path: Path) -> str:
    """Extract all text from a PDF via pdfplumber, then normalise week headers."""
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages)
    return _normalise_week_headers(text)


def _normalise_week_headers(text: str) -> str:
    """
    pdfplumber splits "N주차:" across two lines when the number is bold:
        "5 :\n주차 ..."          → "5주차: ..."
        "6 : (1)\n주차 딥러닝"  → "6주차: 딥러닝"   (subtitle dropped; week# is enough)
        "7 : (2) (CNN …)\n주차 …" → "7주차: …"
    The optional subtitle between ':' and '\n주차' is discarded because the
    week number alone uniquely identifies the section.
    """
    return re.sub(
        r"(\d+)\s*:[^\n]*\n주차\s*",
        lambda m: f"{m.group(1)}주차: ",
        text,
    )


def _extract_week_section(text: str, week: int) -> str:
    """
    Find the N주차 block in the PDF text and return it cleaned up.
    Spans from "N주차:" up to the next "M주차:" (or end of document).
    """
    headers = [
        (m.start(), int(m.group(1)))
        for m in _WEEK_HEADER_RE.finditer(text)
    ]

    for i, (start, w) in enumerate(headers):
        if w != week:
            continue

        end = headers[i + 1][0] if i + 1 < len(headers) else len(text)
        raw = text[start:end]

        # Strip PDF page-footer artifacts
        raw = _PAGE_ARTIFACT_RE.sub("", raw)

        # Collapse blank lines and strip leading/trailing whitespace per line
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        return "\n".join(lines)

    return ""


def _config_summary(subject: str, week: int) -> str:
    """
    Return a short bullet list of materials available for this subject/week,
    derived from configuration.md.
    """
    try:
        from src.utils.subject_config import load_config
        cfg = load_config(subject)
    except FileNotFoundError:
        return ""

    lines: list[str] = []

    # Previous lecture note for this exact week
    prev = cfg.get("previous_note_paths", {}).get(week)
    if prev:
        lines.append(f"- 이전 강의노트 ({week}주차): `{Path(prev).name}`")

    # Reference materials count
    ref_count = len(cfg.get("reference_paths", []))
    if ref_count:
        lines.append(f"- 참고 교재/자료: {ref_count}개 파일 로드 예정")

    # Syllabus
    if cfg.get("syllabus"):
        lines.append(f"- 강의계획서: `{Path(cfg['syllabus']).name}`")

    return "\n".join(lines)
