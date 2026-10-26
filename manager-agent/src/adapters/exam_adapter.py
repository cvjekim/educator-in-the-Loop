"""
Adapter for written-exam-agent.

Stub mode: returns mock result immediately.
Real mode: imports and runs written-exam-agent/src/graph/pipeline.build_graph()
           headlessly. HITL skipped — manager UI handles review.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.adapters.base import STUB_MODE, stub_result

_AGENT_ROOT = Path(__file__).resolve().parents[4] / "written-exam-agent"


def run(payload: dict) -> dict:
    if STUB_MODE:
        return stub_result(
            task_type="exam",
            week=payload.get("week", 0),
            subject=payload.get("subject", ""),
            note="시험 문제 및 루브릭 초안이 생성되었습니다. (스텁 모드)",
        )

    sys.path.insert(0, str(_AGENT_ROOT))
    try:
        import importlib
        pipeline = importlib.import_module("src.graph.pipeline")

        graph = pipeline.build_graph()
        initial_state = {
            "subject_name": payload.get("subject", ""),
            "parameters": [{"question_type": "short_answer", "count": 3}],
            "questions": [],
            "rubrics": [],
            "final_output": None,
            "review_status": "approved",
            "feedback": "",
        }
        config = {"configurable": {"thread_id": f"exam-{payload.get('week', 0)}"}}
        result = graph.invoke(initial_state, config)
        return {
            "success": True,
            "output": result.get("formatted_exam", ""),
            "note": "",
        }
    except Exception as e:
        return {"success": False, "output": "", "note": str(e)}
    finally:
        if str(_AGENT_ROOT) in sys.path:
            sys.path.remove(str(_AGENT_ROOT))
