"""
Node: draft_rubric
Drafts a detailed grading rubric for every generated question via LLM.
Uses temperature=0.3 for deterministic, reproducible scoring criteria.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.utils.parser import format_questions_for_rubric, parse_rubrics_response

load_dotenv()

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def _load_prompt() -> str:
    path = _PROMPTS_DIR / "rubric_gen.md"
    if not path.exists():
        raise FileNotFoundError(f"루브릭 프롬프트 템플릿을 찾을 수 없습니다: {path}")
    return path.read_text(encoding="utf-8")


def draft_rubric(state: dict) -> dict:
    """
    State reads:  questions
    State writes: rubrics (one per question, ordered by question_number)
    """
    questions: list[dict] = state.get("questions", [])
    if not questions:
        return {"rubrics": []}

    question_block = format_questions_for_rubric(questions)
    user_message = (
        "아래 문제들에 대한 채점 루브릭을 작성해 주십시오.\n\n"
        + question_block
    )

    # Lower temperature for consistent scoring criteria across runs
    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
    response = llm.invoke([
        SystemMessage(content=_load_prompt()),
        HumanMessage(content=user_message),
    ])

    rubrics = parse_rubrics_response(response.content)
    return {"rubrics": rubrics}
