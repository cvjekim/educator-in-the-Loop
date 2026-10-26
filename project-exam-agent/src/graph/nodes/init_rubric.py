"""
Node: init_rubric
Expands the professor's raw rubric guidelines into a structured LLM system prompt.
"""

from __future__ import annotations

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()


def init_rubric(state: dict) -> dict:
    """
    State reads:  rubric_guidelines
    State writes: rubric_prompt
    """
    guidelines = state["rubric_guidelines"]

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke([
        SystemMessage(content=(
            "교수자의 루브릭 가이드라인을 평가 시스템 프롬프트로 변환하세요. "
            "각 평가 항목을 명확한 기준으로 구조화하되, "
            "수치 점수·랭킹 없이 기여도 중심 정성 평가임을 명시하세요. "
            "한국어로 작성하세요."
        )),
        HumanMessage(content=f"루브릭 가이드라인:\n{guidelines}"),
    ])

    return {
        "current_stage": "init_rubric",
        "overall_progress": 10,
        "status_message": "루브릭 구조화 완료",
        "rubric_prompt": response.content.strip(),
    }
