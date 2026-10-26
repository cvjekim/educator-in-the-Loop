"""
Node: human_review
Runs after the professor approves the draft in the Streamlit HITL stage.

State contract (set by app.py before resuming the graph):
  - draft_outline : contains the professor's direct title edits (from st.data_editor)
  - guidelines    : original guidelines, optionally with a professor feedback block
                    appended using FEEDBACK_MARKER by the Streamlit UI
  - review_status : "approved"

If a feedback block is found in guidelines, an LLM revision pass is applied
to the outline so the professor's written directions are honoured.
Direct edits (title renames via st.data_editor) need no LLM — they are
already reflected in draft_outline when the state arrives here.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app import DraftOutline, LectureState

# Both the node and app.py import this marker so the contract stays in one place.
FEEDBACK_MARKER = "\n\n[교수 피드백]\n"

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        from dotenv import load_dotenv
        load_dotenv()
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    return _llm


# ---------------------------------------------------------------------------
# Public node function
# ---------------------------------------------------------------------------

def human_review(state: LectureState) -> LectureState:
    """
    Executed once the professor clicks '승인 및 생성'.
    Applies text feedback (if any) to the already-edited draft_outline.
    """
    outline: DraftOutline | None = state.get("draft_outline")
    feedback = _extract_feedback(state.get("guidelines", ""))

    if feedback and outline:
        outline = _apply_feedback(outline, feedback, state["topic"])

    return {
        **state,
        "draft_outline": outline,
        "current_stage": "human_review",
        "overall_progress": 55,
        "status_message": "교수 검토 완료. 본문 생성을 시작합니다.",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_feedback(guidelines: str) -> str:
    """Return professor feedback text when FEEDBACK_MARKER is present."""
    if FEEDBACK_MARKER not in guidelines:
        return ""
    _, _, tail = guidelines.partition(FEEDBACK_MARKER)
    return tail.strip()


def _apply_feedback(
    outline: DraftOutline,
    feedback: str,
    topic: str,
) -> DraftOutline:
    """
    Ask an LLM to revise the outline based on the professor's written feedback.

    Strict constraints preserved:
    - Intro slide: only trend-related content
    - Main slides: only textbook/PPT-based titles (no trend data)
    """
    main_text = "\n".join(outline.get("main_slides", []))

    messages = [
        SystemMessage(
            content=(
                "당신은 대학교 강의 슬라이드 구성을 교수 피드백에 맞게 수정하는 AI 어시스턴트입니다.\n"
                "규칙:\n"
                "- 인트로 슬라이드: 최신 트렌드 내용만 포함. 교재/PPT 내용 금지.\n"
                "- 메인 슬라이드: 교재/PPT 기반 제목만 포함. 트렌드 내용 금지.\n"
                "- 메인 슬라이드 각 항목은 '## '로 시작하는 한 줄 제목.\n"
                "출력: 반드시 아래 JSON 형식만 출력하세요.\n"
                '{"intro_slide": "...", "main_slides": ["## 제목1", "## 제목2", ...]}'
            )
        ),
        HumanMessage(
            content=(
                f"강의 주제: {topic}\n\n"
                f"교수 피드백:\n{feedback}\n\n"
                f"현재 인트로 슬라이드:\n{outline.get('intro_slide', '')}\n\n"
                f"현재 메인 슬라이드 목차:\n{main_text}\n\n"
                "피드백을 반영하여 수정된 슬라이드 구성을 JSON으로 출력하세요."
            )
        ),
    ]

    response = _get_llm().invoke(messages)
    return _parse_outline(response.content, fallback=outline)


def _parse_outline(response_text: str, fallback: DraftOutline) -> DraftOutline:
    """Parse LLM JSON response; return fallback on any failure."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", response_text).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return fallback
    try:
        data = json.loads(m.group(0))
        return DraftOutline(
            intro_slide=str(data.get("intro_slide", fallback["intro_slide"])),
            main_slides=list(data.get("main_slides", fallback["main_slides"])),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return fallback
