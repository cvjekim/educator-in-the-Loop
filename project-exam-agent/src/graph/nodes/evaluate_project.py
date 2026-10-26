"""
Node: evaluate_project
Applies the structured rubric to each project summary and generates
item-by-item feedback drafts. No numeric scores or rankings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "evaluate.md"


def _parse_eval_response(content: str) -> dict:
    """Extract JSON from LLM response; fall back to raw text on parse failure."""
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip().strip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "feedback_items": {},
            "overall_feedback": content.strip(),
        }


def evaluate_project(state: dict) -> dict:
    """
    State reads:  summaries, rubric_prompt, roster
    State writes: evaluation_drafts
    """
    summaries: dict    = state["summaries"]
    rubric_prompt: str = state["rubric_prompt"]
    roster: list[dict] = state["roster"]

    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    full_system   = f"{system_prompt}\n\n## 루브릭\n{rubric_prompt}"

    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
    id_to_entry = {e["student_id"]: e for e in roster}
    evaluation_drafts = []

    for student_id, summary in summaries.items():
        entry    = id_to_entry.get(student_id, {})
        response = llm.invoke([
            SystemMessage(content=full_system),
            HumanMessage(content=f"학생: {entry.get('name', student_id)}\n\n프로젝트 요약:\n{summary}"),
        ])
        parsed = _parse_eval_response(response.content)
        evaluation_drafts.append({
            "student_id":       student_id,
            "name":             entry.get("name", student_id),
            "summary":          summary,
            "feedback_items":   parsed.get("feedback_items", {}),
            "overall_feedback": parsed.get("overall_feedback", ""),
        })

    return {
        "current_stage": "evaluate_project",
        "overall_progress": 75,
        "status_message": f"평가 초안 생성 완료 — {len(evaluation_drafts)}명",
        "evaluation_drafts": evaluation_drafts,
        "review_status": "pending",
    }
