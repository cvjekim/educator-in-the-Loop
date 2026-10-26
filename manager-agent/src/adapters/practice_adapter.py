"""
Adapter for practice-agent.

Stub mode: returns mock result immediately.
Real mode: imports and runs practice-agent/src/graph/pipeline.build_graph()
           headlessly. The self-reflect loop runs to completion; HITL skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.adapters.base import STUB_MODE, stub_result

_AGENT_ROOT = Path(__file__).resolve().parents[4] / "practice-agent"


def run(payload: dict) -> dict:
    if STUB_MODE:
        return stub_result(
            task_type="practice",
            week=payload.get("week", 0),
            subject=payload.get("subject", ""),
            note="실습 노트북이 수정되었습니다. (스텁 모드)",
        )

    sys.path.insert(0, str(_AGENT_ROOT))
    try:
        import importlib
        pipeline = importlib.import_module("src.graph.pipeline")

        graph = pipeline.build_graph()
        initial_state = {
            "subject": payload.get("subject", ""),
            "guidelines": payload.get("context", ""),
            "notebook_path": payload.get("notebook_path", ""),
            "current_stage": "",
            "overall_progress": 0,
            "status_message": "",
            "code_quality": "fail",
            "iteration_count": 0,
            "max_iterations": 3,
            "review_status": "approved",
            "code_cells": [],
            "markdown_cells": [],
            "revised_cells": [],
            "execution_result": None,
            "output_path": None,
        }
        config = {"configurable": {"thread_id": f"practice-{payload.get('week', 0)}"}}
        result = graph.invoke(initial_state, config)
        return {"success": True, "output": result.get("output_path", ""), "note": ""}
    except Exception as e:
        return {"success": False, "output": "", "note": str(e)}
    finally:
        if str(_AGENT_ROOT) in sys.path:
            sys.path.remove(str(_AGENT_ROOT))
