"""
Response-parsing and prompt-formatting utilities for the Written Exam Agent.
Intentionally free of LLM / Streamlit imports so this module is lightweight
and can be unit-tested without side effects.
"""

from __future__ import annotations

import json
import re

# Korean display names for question types (used in prompt construction)
_TYPE_NAMES: dict[str, str] = {
    "single_choice": "객관식 (5지선다)",
    "short_answer": "단답형",
    "open_answer": "서술형",
}


def build_params_description(parameters: list[dict]) -> str:
    """Convert the parameters list to a human-readable Korean string."""
    lines = []
    for p in parameters:
        label = _TYPE_NAMES.get(p["question_type"], p["question_type"])
        lines.append(f"- {label}: {p['count']}문제")
    return "\n".join(lines)


def parse_questions_response(content: str) -> list[dict]:
    """
    Parse the LLM's raw string into a list of question dicts.

    Handles the following common LLM output variants:

    1. Bare JSON array (ideal)
    2. JSON wrapped in ```json … ``` or ``` … ``` code fences
    3. Leading/trailing prose — extracts the first ``[…]`` block
    """
    # Strip markdown code fences (```json … ``` or ``` … ```)
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip().strip("`").strip()

    # Attempt 1: direct parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        raise ValueError("JSON 최상위 타입이 배열이 아닙니다.")
    except json.JSONDecodeError:
        pass

    # Attempt 2: slice from the first '[' to the last ']'
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start: end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(
        "LLM이 유효한 JSON 배열을 반환하지 않았습니다.\n"
        f"응답 앞부분:\n{content[:400]}"
    )


# Rubric responses use the exact same parsing strategy as questions.
parse_rubrics_response = parse_questions_response


def format_questions_for_rubric(questions: list[dict]) -> str:
    """
    Render the question list into a structured block for the rubric LLM.

    Each entry includes the question number, Korean type label, full content,
    and the model answer so the LLM can calibrate scoring precisely.
    Returns an empty string when the list is empty.
    """
    if not questions:
        return ""
    parts = []
    for q in questions:
        type_label = _TYPE_NAMES.get(q["question_type"], q["question_type"])
        parts.append(
            f"[문제 {q['number']}] ({type_label})\n"
            f"문제: {q['content']}\n"
            f"모범 답안: {q['model_answer']}"
        )
    return "\n\n".join(parts)
