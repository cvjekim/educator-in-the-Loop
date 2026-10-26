"""
Base adapter interface for sub-agents.

STUB_MODE (default: True) returns mock data so manager can run without
sub-agents being fully implemented.

Real integration pattern (for each adapter):
    1. sys.path.insert(0, str(AGENT_ROOT))
    2. import importlib; pipeline = importlib.import_module("src.graph.pipeline")
    3. graph = pipeline.build_graph()  — runs headlessly (no Streamlit HITL)
    4. result = graph.invoke(initial_state, config)
    5. sys.path.pop(0)
"""

from __future__ import annotations

import os

STUB_MODE: bool = os.getenv("AGENT_STUB_MODE", "true").lower() == "true"


def stub_result(task_type: str, week: int, subject: str, note: str = "") -> dict:
    return {
        "success": True,
        "output": f"[STUB] {task_type} 에이전트 실행 완료 — {subject} {week}주차",
        "note": note or f"{task_type} 어댑터가 스텁 모드로 실행되었습니다.",
    }
