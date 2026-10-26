"""
Adapter for lecture-note-agent.

Stub mode: returns mock result immediately.
Real mode: imports and runs lecture-note-agent/src/graph/pipeline.build_graph()
           headlessly (HITL skipped — professor reviews via manager UI instead).
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.adapters.base import STUB_MODE, stub_result

_AGENT_ROOT = Path(__file__).resolve().parents[4] / "lecture-note-agent"


def run(payload: dict) -> dict:
    """
    Args:
        payload: {task_type, week, subject, context, syllabus, rubric_guidelines}
    Returns:
        {success, output, note, task_type, week, subject}
    """
    if STUB_MODE:
        return stub_result(
            task_type="lecture",
            week=payload.get("week", 0),
            subject=payload.get("subject", ""),
            note="강의 노트 초안이 생성되었습니다. (스텁 모드)",
        )

    # --- Real integration ---
    sys.path.insert(0, str(_AGENT_ROOT))
    try:
        import importlib
        pipeline = importlib.import_module("src.graph.pipeline")
        state_mod = importlib.import_module("app")

        graph = pipeline.build_graph()
        initial_state = {
            "subject": payload.get("subject", ""),
            "week": payload.get("week", 1),
            "topic": payload.get("context", ""),
            "guidelines": payload.get("context", ""),
            "raw_context": "",
            "draft_outline": None,
            "final_output": None,
            "review_status": "approved",   # headless: skip HITL
            "current_stage": "",
            "overall_progress": 0,
            "status_message": "",
        }
        config = {"configurable": {"thread_id": f"lecture-{payload.get('week', 0)}"}}
        result = graph.invoke(initial_state, config)
        return {
            "success": True,
            "output": result.get("final_output", ""),
            "note": "",
        }
    except Exception as e:
        return {"success": False, "output": "", "note": str(e)}
    finally:
        if str(_AGENT_ROOT) in sys.path:
            sys.path.remove(str(_AGENT_ROOT))
