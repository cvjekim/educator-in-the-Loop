"""
Node: generate_questions
Loads lecture materials and generates exam questions + model answers via LLM.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.materials.loader import load_materials, load_syllabus
from src.utils.parser import build_params_description, parse_questions_response

load_dotenv()

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def _load_prompt() -> str:
    path = _PROMPTS_DIR / "question_gen.md"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 템플릿을 찾을 수 없습니다: {path}")
    return path.read_text(encoding="utf-8")


def generate_questions(state: dict) -> dict:
    """
    State reads:  subject_name, parameters, feedback
    State writes: questions (fresh list), rubrics (reset to [])
    """
    subject_name: str = state["subject_name"]
    parameters: list[dict] = state["parameters"]
    feedback: str = state.get("feedback", "")

    # 1. Load course context
    syllabus = load_syllabus(subject_name)
    materials = load_materials(subject_name)

    # 2. Compose user message
    syllabus_section = (
        f"## 교과목표\n{syllabus}"
        if syllabus
        else "## 교과목표\n(syllabus.md 파일 없음 — 강의 자료 기반으로 출제)"
    )
    materials_section = (
        f"## 강의 자료\n{materials}"
        if materials
        else "## 강의 자료\n(materials 폴더 없음 — 일반 지식 기반으로 출제)"
    )
    params_section = (
        "## 출제 요청\n"
        "다음 유형과 수량으로 문제를 출제하십시오:\n"
        + build_params_description(parameters)
    )

    user_parts = [syllabus_section, materials_section, params_section]
    if feedback:
        user_parts.append(
            "## ⚠️ 교수님의 수정 요청 (반드시 반영할 것)\n" + feedback
        )

    # 3. Call LLM
    llm = ChatOpenAI(model="gpt-4o", temperature=0.7)
    response = llm.invoke([
        SystemMessage(content=_load_prompt()),
        HumanMessage(content="\n\n".join(user_parts)),
    ])

    # 4. Parse and return
    questions = parse_questions_response(response.content)
    return {"questions": questions, "rubrics": []}
