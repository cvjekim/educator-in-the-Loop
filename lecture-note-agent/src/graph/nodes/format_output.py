"""
Node: format_output

Converts the intermediate bullet draft (produced by analysis_content and
stored in state["final_output"]) into a polished, portable Markdown document.

Document hierarchy (per the edit-article skill — treat sections as a DAG,
ensure concepts flow from foundational to applied):

  # {Week}주차: {Topic}          ← document title
  > metadata blockquote

  ---

  ## 인트로 슬라이드 (트렌드)   ← intro kept as sub-heading
  ...

  ---

  # {Slide Title}                ← each main slide becomes a top-level heading
  ## {Sub-concept A}             ← LLM groups bullets into 2-3 logical sub-topics
  - bullet (개조식, no period)
    - sub-bullet if needed
  ## {Sub-concept B}
  - bullet
  ```python                      ← code block added for algorithmic topics
  ...
  ```
  ![alt](url)                    ← image only when LLM is confident of a public URL

"""

from __future__ import annotations

import re
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.state_types import LectureState

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        from dotenv import load_dotenv
        load_dotenv()
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    return _llm


# ── System prompt (shared across all section calls) ───────────────────────────

_SECTION_SYSTEM_PROMPT = """\
당신은 대학교 강의 슬라이드를 체계적인 마크다운 문서로 정리하는 AI 어시스턴트입니다.
입력: 슬라이드 하나의 한국어 불릿 포인트 목록
출력: 계층 구조를 갖춘 마크다운 섹션 (슬라이드 제목 '# '은 제외 — 별도로 추가됨)

━━━ 마크다운 계층 규칙 ━━━
1. 불릿들을 의미적으로 2~3개 그룹으로 분류한다.
2. 각 그룹에 한국어 소제목을 붙인다 → ## 소제목
3. 그룹 내 세부 항목 → - 불릿 (개조식, 마침표 없음)
4. 더 구체적인 하위 내용 → (들여쓰기 2칸 + -) 서브 불릿
5. 수식·알고리즘 설명 시 → ### 수식/알고리즘, 이후 LaTeX 인라인 `$...$` 또는 블록 `$$...$$`
6. 코드 예시가 자연스러운 기술 주제 → ```python 코드 블록 ``` (핵심 5~10줄)
7. 유명한 아키텍처 이미지(CNN, Transformer 등) → ![설명](공개 URL) — URL이 확실할 때만, 불확실하면 생략

━━━ 출력 규칙 ━━━
- 반드시 한국어 유지
- 입력된 불릿 내용만 재구성 (새 정보 추가 금지)
- 개조식 문체 (명사형 또는 짧은 서술형), 줄 끝 마침표 없음
- 슬라이드 제목(# 레벨) 출력 금지
- 섹션 간 빈 줄 한 줄씩 삽입

━━━ edit-article 원칙 ━━━
- 정보를 의존 관계 그래프(DAG)로 파악한다: 기초 개념 → 메커니즘 → 응용 순서로 ## 소제목 배치
- 각 ## 소제목 아래 최대 240자 분량의 불릿으로 간결하게 작성한다
"""


# ── Public node ───────────────────────────────────────────────────────────────

def format_output(state: LectureState) -> LectureState:
    draft: str = state.get("final_output") or ""

    if not draft.strip():
        return {
            **state,
            "current_stage": "format_output",
            "overall_progress": 100,
            "status_message": "생성할 내용이 없습니다.",
        }

    sections = _parse_sections(draft)

    parts: list[str] = [_build_doc_header(state)]

    for title, body in sections:
        parts.append(_format_section(title, body, state.get("guidelines", "")))

    final_md = "\n\n---\n\n".join(parts)

    return {
        **state,
        "current_stage": "format_output",
        "overall_progress": 100,
        "status_message": "강의노트 생성 완료.",
        "final_output": final_md,
    }


# ── Document header ───────────────────────────────────────────────────────────

def _build_doc_header(state: LectureState) -> str:
    today = date.today().strftime("%Y-%m-%d")
    subject_display = state.get("subject", "").replace("-", " ").title()
    week = state.get("week", "")
    topic = state.get("topic", "")
    return (
        f"# {week}주차: {topic}\n\n"
        f"> **과목**: {subject_display} &nbsp;|&nbsp; **날짜**: {today}"
    )


# ── Section parsing ───────────────────────────────────────────────────────────

def _parse_sections(draft: str) -> list[tuple[str, str]]:
    """
    Split the intermediate draft on --- separators.
    Returns [(heading_line, body_text), ...].
    """
    raw = re.split(r"\n\s*---\s*\n", draft)
    result: list[tuple[str, str]] = []
    for block in raw:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        title_line = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        result.append((title_line, body))
    return result


# ── Per-section formatting ────────────────────────────────────────────────────

def _format_section(title: str, body: str, guidelines: str) -> str:
    """
    Intro slide → kept as ## (sub-heading, already formatted well).
    Main slides → LLM restructures body under # heading with ## sub-concepts.
    """
    is_intro = "인트로" in title
    clean_title = re.sub(r"^#+\s*", "", title).strip()

    if is_intro:
        # Intro slide: keep body as-is, just normalise heading level
        return f"## {clean_title}\n\n{body}" if body else f"## {clean_title}"

    if not body.strip():
        return f"# {clean_title}"

    messages = [
        SystemMessage(content=_SECTION_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"슬라이드 제목: {clean_title}\n"
                f"교수 지침: {guidelines or '없음'}\n\n"
                f"원본 불릿 포인트:\n{body}\n\n"
                "위 내용을 마크다운 계층 구조로 재구성하세요. "
                "슬라이드 제목(# 레벨)은 출력하지 마세요."
            )
        ),
    ]

    resp = _get_llm().invoke(messages)
    formatted_body = resp.content.strip()

    return f"# {clean_title}\n\n{formatted_body}"
