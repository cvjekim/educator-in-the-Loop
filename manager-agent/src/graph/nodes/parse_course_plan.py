"""
parse_course_plan — LLM으로 강의 계획서를 분석하여 task_queue 생성.

Demonstrates: 에이전트의 Plan 단계 (계획 수립)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

from src.graph.state import ManagerState

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def parse_course_plan(state: ManagerState) -> dict:
    prompt_text = (_PROMPTS_DIR / "plan.md").read_text(encoding="utf-8")

    feedback_section = ""
    if state.get("feedback"):
        feedback_section = f"\n\n## 교수자 피드백\n{state['feedback']}\n위 피드백을 반영하여 다시 분석하세요."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(
        f"{prompt_text}{feedback_section}\n\n## 강의 계획서\n{state['syllabus']}"
    )

    raw = response.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        task_queue = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: single generic task
        task_queue = [
            {
                "task_type": "lecture",
                "week": 1,
                "subject": "강의",
                "context": state["syllabus"][:200],
            }
        ]

    return {
        "task_queue": task_queue,
        "remaining_tasks": task_queue.copy(),
        "current_stage": "parse_course_plan",
        "review_status": "pending",
        "feedback": "",
        "results": [],
    }
