"""
reflect_quality — LLM으로 서브 에이전트 결과 품질을 평가.

max_reflections 초과 시 'ok'로 강제 처리하여 무한 루프 방지.

Demonstrates: Reflection 패턴 (결과 관찰 → 재시도 판단)
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

from src.graph.state import ManagerState

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def reflect_quality(state: ManagerState) -> dict:
    reflection_count = state.get("reflection_count", 0) + 1
    max_reflections = state.get("max_reflections", 2)

    # Force ok if max retries exceeded
    if reflection_count > max_reflections:
        return {
            "reflection_count": reflection_count,
            "quality_flag": "ok",
            "quality_notes": f"최대 재시도 횟수({max_reflections}) 초과 — 강제 통과",
            "current_stage": "reflect_quality",
        }

    current_result = state.get("current_result") or {}
    prompt_text = (_PROMPTS_DIR / "reflect.md").read_text(encoding="utf-8")

    result_summary = json.dumps(
        {k: str(v)[:300] for k, v in current_result.items()},
        ensure_ascii=False,
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke(f"{prompt_text}\n\n## 실행 결과\n{result_summary}")

    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        quality_flag = parsed.get("quality_flag", "ok")
        quality_notes = parsed.get("quality_notes", "")
    except json.JSONDecodeError:
        quality_flag = "ok"
        quality_notes = "품질 평가 파싱 실패 — ok로 처리"

    return {
        "reflection_count": reflection_count,
        "quality_flag": quality_flag,
        "quality_notes": quality_notes,
        "current_stage": "reflect_quality",
    }
