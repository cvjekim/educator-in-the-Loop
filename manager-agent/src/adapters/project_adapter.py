"""
Adapter for project-exam-agent.

Stub mode: returns mock result immediately.
Real mode: imports and runs project-exam-agent/src/graph/pipeline.build_graph()
           headlessly. Requires GITHUB_TOKEN env var and a roster payload.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.adapters.base import STUB_MODE, stub_result

_AGENT_ROOT = Path(__file__).resolve().parents[4] / "project-exam-agent"


def run(payload: dict) -> dict:
    if STUB_MODE:
        return stub_result(
            task_type="project",
            week=payload.get("week", 0),
            subject=payload.get("subject", ""),
            note="프로젝트 평가 초안이 생성되었습니다. (스텁 모드)",
        )

    sys.path.insert(0, str(_AGENT_ROOT))
    try:
        import importlib
        pipeline = importlib.import_module("src.graph.pipeline")

        graph = pipeline.build_graph()
        initial_state = {
            "rubric_guidelines": payload.get("rubric_guidelines", ""),
            "rubric_prompt": "",
            "roster": payload.get("roster", []),
            "current_stage": "",
            "overall_progress": 0,
            "status_message": "",
            "review_status": "approved",
            "crawled_data": {},
            "summaries": {},
            "evaluation_drafts": [],
            "output_dir": None,
        }
        config = {"configurable": {"thread_id": f"project-{payload.get('week', 0)}"}}
        result = graph.invoke(initial_state, config)
        return {
            "success": True,
            "output": f"평가 결과 저장 완료: {result.get('export_paths', [])}",
            "note": "",
        }
    except Exception as e:
        return {"success": False, "output": "", "note": str(e)}
    finally:
        if str(_AGENT_ROOT) in sys.path:
            sys.path.remove(str(_AGENT_ROOT))
