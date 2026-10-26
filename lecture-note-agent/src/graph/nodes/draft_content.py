"""
Node: draft_content
Produces the two-part outline draft:
  - Intro slide: uses trend data ONLY (via trend_augmentation workflow)
  - Main slides: uses raw_context ONLY (no trend data)
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app import DraftOutline, LectureState
from src.trends.archive import select_trends_for_topic

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        from dotenv import load_dotenv
        load_dotenv()
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    return _llm


def draft_content(state: LectureState) -> LectureState:
    # Intro slide — trend-augmented (strict isolation)
    trends = select_trends_for_topic(state["topic"], n=2)
    intro_draft = _draft_intro(trends, state["topic"], state.get("guidelines", ""))

    # Main slides — textbook/PPT context only (no trend data)
    main_outline = _draft_main_outline(
        state["raw_context"],
        state["topic"],
        state.get("guidelines", ""),
        state["subject"],
        state["week"],
    )

    draft: DraftOutline = {
        "intro_slide": intro_draft,
        "main_slides": main_outline,
    }

    return {
        **state,
        "current_stage": "draft_content",
        "overall_progress": 50,
        "status_message": "Outline draft ready for review.",
        "draft_outline": draft,
    }


def _draft_intro(trends: list[dict], topic: str, guidelines: str) -> str:
    """Call LLM to connect selected trends to the week's topic. Output in Korean."""
    if not trends:
        return f"## 최신 트렌드 소개\n\n- 관련 트렌드 데이터가 없습니다."

    trend_block = "\n\n".join(
        f"[트렌드 {i + 1}]\n"
        f"제목: {t.get('topic', '(제목 없음)')}\n"
        f"카테고리: {t.get('category', '')}\n"
        f"요약: {t.get('summary', '')}\n"
        f"날짜: {t.get('date', '')}"
        for i, t in enumerate(trends)
    )

    messages = [
        SystemMessage(
            content=(
                "당신은 대학교 교수의 강의 슬라이드 초안을 작성하는 AI 어시스턴트입니다. "
                "인트로 슬라이드는 최신 AI/기술 트렌드 2개를 소개하고, "
                "이번 주 강의 주제와의 연결성을 학생들에게 간결한 한국어 불릿 포인트로 설명합니다. "
                "형식: 마크다운 불릿 포인트, 슬라이드 제목 포함, 각 트렌드마다 2~3개 핵심 포인트."
            )
        ),
        HumanMessage(
            content=(
                f"이번 주 강의 주제: {topic}\n"
                f"교수 지침: {guidelines or '없음'}\n\n"
                f"선별된 최신 트렌드:\n{trend_block}\n\n"
                "위 트렌드 2개를 이번 주 강의 주제와 연결하는 인트로 슬라이드 초안을 "
                "한국어 불릿 포인트로 작성해 주세요."
            )
        ),
    ]

    response = _get_llm().invoke(messages)
    return response.content


def _draft_main_outline(
    raw_context: str, topic: str, guidelines: str, subject: str, week: int
) -> list[str]:
    """
    Produce ordered slide titles.

    Priority logic:
      1. If a previous lecture note PDF exists for this week, extract its slide
         structure and reconcile it with the professor's guidelines.
      2. Otherwise fall back to raw_context + guidelines (original behaviour).
    """
    prev_slides = _extract_prev_note_slides(subject, week)

    if prev_slides:
        return _reconcile_with_guidelines(prev_slides, topic, guidelines, raw_context)

    # ── Fallback: no previous note ────────────────────────────────────────────
    if not raw_context.strip():
        return [
            f"## {topic}: 개요 및 핵심 개념",
            f"## {topic}: 주요 알고리즘 / 방법론",
            f"## {topic}: 사례 분석 및 응용",
            f"## {topic}: 정리 및 핵심 요약",
        ]

    context_excerpt = raw_context[:6000]

    messages = [
        SystemMessage(
            content=(
                "당신은 대학교 교수의 강의 슬라이드 목차를 설계하는 AI 어시스턴트입니다. "
                "교재/PPT 원문 내용만을 기반으로 슬라이드 제목 목록을 작성합니다. "
                "트렌드 데이터나 외부 정보는 절대 사용하지 마세요. "
                "각 항목은 '## 슬라이드 제목' 형식으로, 한 줄에 하나씩 작성합니다. "
                "보통 5~8개의 슬라이드로 구성합니다."
            )
        ),
        HumanMessage(
            content=(
                f"강의 주제: {topic}\n"
                f"교수 지침: {guidelines or '없음'}\n\n"
                f"교재/강의 자료 발췌:\n{context_excerpt}\n\n"
                "위 자료를 기반으로 이번 주 강의의 메인 슬라이드 목차(제목 목록)를 "
                "한국어로 작성해 주세요. 각 슬라이드 제목은 '## '로 시작하는 한 줄로 작성하세요. "
                "개조식으로 작성하고, 중요 개념 이름 위주로 제목을 작성하세요."
            )
        ),
    ]

    response = _get_llm().invoke(messages)
    return [
        line.strip()
        for line in response.content.splitlines()
        if line.strip().startswith("##")
    ]


def _extract_prev_note_slides(subject: str, week: int) -> list[tuple[str, str]]:
    """
    Load the previous year's lecture note PDF for this week and extract
    (slide_title, slide_body) pairs — one per PDF page.

    Returns an empty list if no note exists or the file is missing.
    """
    from pathlib import Path
    try:
        from src.utils.subject_config import load_config
        config = load_config(subject)
    except FileNotFoundError:
        return []

    note_path_str = config.get("previous_note_paths", {}).get(week)
    if not note_path_str:
        return []

    note_path = Path(note_path_str)
    if not note_path.exists() or note_path.suffix.lower() != ".pdf":
        return []

    try:
        import pdfplumber
        slides: list[tuple[str, str]] = []
        with pdfplumber.open(note_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if not lines:
                    continue
                title = lines[0]
                body = "\n".join(lines[1:])
                slides.append((title, body))
        return slides
    except Exception:
        return []


def _reconcile_with_guidelines(
    prev_slides: list[tuple[str, str]],
    topic: str,
    guidelines: str,
    raw_context: str,
) -> list[str]:
    """
    Given the existing slide structure and the professor's guidelines,
    ask the LLM to produce a reconciled, improved slide title list.
    """
    # Build a readable summary of existing slides
    existing_block = "\n".join(
        f"{i + 1}. {title}" + (f"\n   (내용 요약: {body[:120]}…)" if body else "")
        for i, (title, body) in enumerate(prev_slides)
    )

    # Optionally attach a snippet of the textbook for additional context
    context_snippet = raw_context[:3000] if raw_context.strip() else ""
    context_section = (
        f"\n\n[교재/강의 자료 발췌]\n{context_snippet}" if context_snippet else ""
    )

    messages = [
        SystemMessage(
            content=(
                "당신은 대학교 교수의 강의 슬라이드 목차를 설계하는 AI 어시스턴트입니다.\n"
                "입력:\n"
                "  1) 기존 강의 노트(전년도)의 슬라이드 제목과 내용 요약\n"
                "  2) 교수의 이번 주 수정/추가 지침\n"
                "  3) (선택) 교재/강의 자료 발췌\n\n"
                "작업:\n"
                "  - 기존 슬라이드 구조를 기반으로 하되, 교수 지침을 충실히 반영하여\n"
                "    슬라이드 제목 목록을 재구성하세요.\n"
                "  - 지침에서 삭제/병합/추가/순서 변경 등을 요청하면 그대로 적용하세요.\n"
                "  - 지침이 없거나 '없음'이면 기존 구조를 그대로 유지하세요.\n"
                "  - 각 슬라이드 제목은 '## ' 로 시작하는 한 줄, 한국어, 개조식으로 작성하세요.\n"
                "  - 보통 5~8개 슬라이드. 트렌드 데이터 참조 금지."
            )
        ),
        HumanMessage(
            content=(
                f"강의 주제: {topic}\n"
                f"교수 지침: {guidelines or '없음'}\n\n"
                f"[기존 강의 노트 슬라이드 구조]\n{existing_block}"
                f"{context_section}\n\n"
                "위 내용을 종합하여 이번 주 메인 슬라이드 목차(제목만)를 "
                "'## 제목' 형식으로 한 줄씩 작성하세요."
            )
        ),
    ]

    response = _get_llm().invoke(messages)
    return [
        line.strip()
        for line in response.content.splitlines()
        if line.strip().startswith("##")
    ]
