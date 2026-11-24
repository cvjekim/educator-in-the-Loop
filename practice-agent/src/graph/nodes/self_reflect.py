"""
Node: self_reflect
Executes ordered code cells in one subprocess and observes the result.
The subprocess is not a security sandbox; hosted execution requires a separate runner.
Sets code_quality = 'pass' if all cells run without error, 'fail' otherwise.
The pipeline loops back to revise_code on 'fail' until max_iterations is reached.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from src.state_types import ExecutionResult, PracticeState


def _execute_cell(source: str) -> ExecutionResult:
    """Run a single code cell source in an isolated subprocess."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(source)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return {"success": True, "error": None, "traceback": None, "cell_index": None}
        else:
            return {
                "success": False,
                "error": result.stderr.split("\n")[-2] if result.stderr else "Unknown error",
                "traceback": result.stderr,
                "cell_index": None,
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "TimeoutExpired", "traceback": None, "cell_index": None}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def self_reflect(state: PracticeState) -> dict:
    iteration = state.get("iteration_count", 0) + 1

    cells = sorted(state["revised_cells"], key=lambda c: c["index"])
    # One fresh process per attempt, one shared namespace for every cell.
    program = "\n".join(
        f"exec(compile({cell['source']!r}, '<notebook-cell-{cell['index']}>', 'exec'), globals())"
        for cell in cells
    )
    result = _execute_cell(program)
    if not result["success"]:
        indices = re.findall(r"<notebook-cell-(\d+)>", result.get("traceback") or "")
        result["cell_index"] = int(indices[-1]) if indices else None
        return {
            "current_stage": "self_reflect",
            "overall_progress": min(30 + iteration * 10, 60),
            "status_message": "실행 오류 감지 — 전체 셀 문맥으로 재수정 중…",
            "code_quality": "fail",
            "execution_result": result,
            "iteration_count": iteration,
        }

    return {
        "current_stage": "self_reflect",
        "overall_progress": 65,
        "status_message": f"모든 코드 셀 실행 통과 ({iteration}회 반복)",
        "code_quality": "pass",
        "execution_result": {"success": True, "error": None, "traceback": None, "cell_index": None},
        "iteration_count": iteration,
    }
