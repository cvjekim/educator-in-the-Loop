"""
plan_dispatch — remaining_tasks에서 다음 작업을 꺼내 current_task로 설정.

Demonstrates: 루프 드라이버 (pop-from-queue 패턴)
"""

from __future__ import annotations

from src.graph.state import ManagerState


def plan_dispatch(state: ManagerState) -> dict:
    remaining = list(state.get("remaining_tasks", []))
    if not remaining:
        return {"current_task": None, "current_stage": "plan_dispatch"}

    current_task = remaining.pop(0)

    return {
        "current_task": current_task,
        "remaining_tasks": remaining,
        "current_result": None,
        "reflection_count": 0,
        "quality_flag": "ok",
        "quality_notes": "",
        "current_stage": "plan_dispatch",
    }
