"""
Node: analysis_content

Per-slide 3-step pipeline (main slides only — trend data strictly excluded):

  Step 1 — Retrieve : Split raw_context into overlapping chunks and score
            each chunk by keyword overlap with the slide title.
            Take the top-3 scoring passages.
            If the total retrieved text is < MIN_CONTEXT_CHARS, supplement
            with a Wikipedia search (ko → en, no API key required).

  Step 2 — Summarise: (internal, not shown in output)
            LLM identifies 3 core concepts from the retrieved content.

  Step 3 — Bullets  : LLM converts those concepts into Korean bullet points
            (개조식, 3–6 bullets per slide).

Result: per-slide bullets are assembled into an intermediate Markdown draft
and stored in state["final_output"] for format_output to finalise.
"""

from __future__ import annotations

import re

import requests
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.state_types import DraftOutline, LectureState

# ── Tuning constants ──────────────────────────────────────────────────────────
_MIN_CONTEXT_CHARS = 300   # fewer chars from PDF/PPT → trigger web search
_CHUNK_SIZE = 800          # characters per context chunk
_CHUNK_OVERLAP = 150       # overlap between consecutive chunks
_TOP_K_CHUNKS = 3          # top-scoring chunks to pass to the LLM
_WEB_TIMEOUT = 8           # seconds for Wikipedia request
_MAX_CONTEXT_FOR_LLM = 3_000  # chars fed into the prompt (token guard)

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        from dotenv import load_dotenv
        load_dotenv()
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    return _llm


# ── Public node ───────────────────────────────────────────────────────────────

def analysis_content(state: LectureState) -> LectureState:
    outline: DraftOutline | None = state.get("draft_outline")
    if not outline:
        return {
            **state,
            "current_stage": "analysis_content",
            "overall_progress": 75,
            "status_message": "개요가 없어 분석을 건너뜁니다.",
        }

    slides: list[str] = outline.get("main_slides", [])
    raw_context: str = state.get("raw_context", "")
    topic: str = state.get("topic", "")
    subject: str = state.get("subject", "")
    guidelines: str = state.get("guidelines", "")

    slide_bullets: list[tuple[str, str]] = []  # (slide_title, bullet_markdown)

    for slide_title in slides:
        # Step 1: retrieve from local context
        passages, source_label = _retrieve(slide_title, raw_context, topic, subject)

        # Steps 2 + 3: summarise → Korean bullets (single LLM call)
        bullets = _to_bullets(slide_title, passages, source_label, guidelines)
        slide_bullets.append((slide_title, bullets))

    draft_md = _assemble_draft(outline.get("intro_slide", ""), slide_bullets)

    return {
        **state,
        "current_stage": "analysis_content",
        "overall_progress": 80,
        "status_message": f"{len(slides)}개 슬라이드 분석 완료.",
        "final_output": draft_md,
    }


# ── Step 1: retrieve ──────────────────────────────────────────────────────────

def _retrieve(
    slide_title: str,
    raw_context: str,
    topic: str,
    subject: str,
) -> tuple[str, str]:
    """
    Returns (passages_text, source_label).
    Tries PDF/PPT context first; falls back to Wikipedia (ko → en) if thin.
    """
    passages = _score_chunks(slide_title, raw_context)

    if len(passages) >= _MIN_CONTEXT_CHARS:
        return passages, "교재/PPT"

    # Strip markdown heading prefix ("## ") before searching the web.
    # Use the clean title alone — adding topic words degrades Wikipedia search.
    clean_title = re.sub(r"^#+\s*", "", slide_title).strip()
    web = _web_search(clean_title)
    if web:
        combined = (passages + "\n\n[웹 참고]\n" + web).strip() if passages else web
        label = "교재/PPT + Wikipedia" if passages else "Wikipedia"
        return combined, label

    # Nothing found — LLM will fall back to its own training knowledge
    return passages, "교재/PPT (내용 부족 — AI 지식 보완)"


def _score_chunks(slide_title: str, raw_context: str) -> str:
    """Keyword-score overlapping chunks; return top-K joined."""
    if not raw_context.strip():
        return ""

    keywords = [w for w in re.split(r"\W+", slide_title) if len(w) > 1]
    chunks = _split_chunks(raw_context, _CHUNK_SIZE, _CHUNK_OVERLAP)

    def _score(chunk: str) -> int:
        lower = chunk.lower()
        return sum(lower.count(kw.lower()) for kw in keywords)

    ranked = sorted(chunks, key=_score, reverse=True)
    top = [c for c in ranked[:_TOP_K_CHUNKS] if _score(c) > 0]
    return "\n\n".join(top)


def _split_chunks(text: str, size: int, overlap: int) -> list[str]:
    step = max(1, size - overlap)
    return [text[i: i + size] for i in range(0, len(text), step)]


# ── Step 2 (web fallback): Wikipedia (ko → en) ───────────────────────────────

def _web_search(query: str) -> str:
    """
    Search order:
      1. Korean Wikipedia  — returns Korean text directly (ideal for our LLM)
      2. English Wikipedia — broader coverage of academic/technical topics
    Returns the page extract or empty string on any failure.
    """
    return _wiki_extract("ko", query) or _wiki_extract("en", query)


def _wiki_extract(lang: str, query: str) -> str:
    """
    Search Wikipedia in *lang* for *query*, then return the full page extract.
    Uses the MediaWiki action API (no key required).
    """
    try:
        base = f"https://{lang}.wikipedia.org"

        # 1. Find the best matching article title
        search = requests.get(
            f"{base}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 1,
                "format": "json",
            },
            timeout=_WEB_TIMEOUT,
            headers={"User-Agent": "LectureNoteAgent/1.0"},
        )
        results = search.json().get("query", {}).get("search", [])
        if not results:
            return ""

        title = results[0]["title"]

        # 2. Fetch the REST summary (extract field — plain text, no markup)
        summary = requests.get(
            f"{base}/api/rest_v1/page/summary/{requests.utils.quote(title)}",
            timeout=_WEB_TIMEOUT,
            headers={"User-Agent": "LectureNoteAgent/1.0"},
        )
        return summary.json().get("extract", "").strip()
    except Exception:
        return ""


# ── Steps 2+3: summarise → Korean bullets (single LLM call) ──────────────────

def _to_bullets(
    slide_title: str,
    context: str,
    source_label: str,
    guidelines: str,
) -> str:
    """
    Internally performs:
      1. Identify 3 core concepts from context
      2. Summarise each into 1 Korean sentence
      3. Convert each sentence to a Korean bullet point (개조식)
    Only the final bullet points are returned.
    """
    excerpt = context[:_MAX_CONTEXT_FOR_LLM] if context else "(참고 자료 없음 — AI 지식 기반으로 작성)"

    messages = [
        SystemMessage(
            content=(
                "당신은 대학교 강의 슬라이드 스크립트를 작성하는 AI 어시스턴트입니다.\n"
                "반드시 한국어로 작성하세요.\n\n"
                "내부 작업 절차 (사고 과정은 출력하지 않음):\n"
                "  1. 참고 내용에서 슬라이드 주제와 관련된 핵심 개념 3가지를 파악한다.\n"
                "  2. 각 개념을 학생 눈높이에 맞는 핵심 1문장으로 요약한다.\n"
                "  3. 그 3문장 각각을 개조식 불릿 포인트로 변환한다.\n\n"
                "출력 규칙:\n"
                "- 불릿 포인트만 출력 (절차 1·2의 중간 결과는 절대 출력 금지)\n"
                "- 각 항목은 '- '로 시작\n"
                "- 개조식 서술 (명사형 또는 짧은 서술형), 줄 끝 마침표 없음\n"
                "- 필요하면 서브 불릿 ('  - ')으로 추가 설명 가능\n"
                "- 총 3–6개 불릿 (핵심 3개 필수, 나머지는 보조)"
            )
        ),
        HumanMessage(
            content=(
                f"슬라이드 제목: {slide_title}\n"
                f"출처: {source_label}\n"
                f"교수 지침: {guidelines or '없음'}\n\n"
                f"참고 내용:\n{excerpt}\n\n"
                "위 내용을 바탕으로 한국어 불릿 포인트를 작성하세요."
            )
        ),
    ]

    resp = _get_llm().invoke(messages)
    return resp.content.strip()


# ── Assemble intermediate Markdown draft ──────────────────────────────────────

def _assemble_draft(intro_slide: str, slide_bullets: list[tuple[str, str]]) -> str:
    """
    Combine intro slide + per-slide bullets into a single Markdown draft
    that format_output will finalise.
    """
    parts: list[str] = []

    if intro_slide.strip():
        parts.append(f"## 인트로 슬라이드 (트렌드)\n\n{intro_slide.strip()}")

    for slide_title, bullets in slide_bullets:
        parts.append(f"{slide_title}\n\n{bullets}")

    return "\n\n---\n\n".join(parts)
