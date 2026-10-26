"""
invoke_sub_agent — task_type에 따라 적절한 어댑터를 호출.

Demonstrates: Act 단계 (서브 에이전트 디스패치)
"""

from __future__ import annotations

from src.graph.state import ManagerState


_ADAPTER_MAP = {
    "lecture":  "src.adapters.lecture_adapter",
    "practice": "src.adapters.practice_adapter",
    "exam":     "src.adapters.exam_adapter",
    "project":  "src.adapters.project_adapter",
}


def invoke_sub_agent(state: ManagerState) -> dict:
    task = state.get("current_task")
    if not task:
        return {
            "current_result": {"success": False, "output": "no task", "task_type": "unknown"},
            "current_stage": "invoke_sub_agent",
        }

    task_type = task.get("task_type", "lecture")
    module_path = _ADAPTER_MAP.get(task_type, _ADAPTER_MAP["lecture"])

    import importlib
    adapter = importlib.import_module(module_path)

    payload = {
        "syllabus": state.get("syllabus", ""),
        "rubric_guidelines": state.get("rubric_guidelines", ""),
        **task,
    }
    result = adapter.run(payload)
    result.setdefault("task_type", task_type)
    result.setdefault("week", task.get("week", 0))
    result.setdefault("subject", task.get("subject", ""))

    return {
        "current_result": result,
        "current_stage": "invoke_sub_agent",
    }
