"""
collect_result — current_result를 results에 누적하고 current_task 초기화.

루프 라우터 (_route_next_task)가 remaining_tasks 여부를 확인하여
다음 반복 또는 종료를 결정함.

Demonstrates: Observe 단계 (루프 상태 전이)
"""

from __future__ import annotations

from src.graph.state import ManagerState


def collect_result(state: ManagerState) -> dict:
    results = list(state.get("results", []))
    current_result = state.get("current_result")

    if current_result:
        results.append(current_result)

    return {
        "results": results,
        "current_task": None,
        "current_result": None,
        "current_stage": "collect_result",
    }
