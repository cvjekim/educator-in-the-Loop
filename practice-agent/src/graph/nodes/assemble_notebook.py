"""
Node: assemble_notebook
Merges revised code cells and formatted markdown cells back into original order,
then serialises to a temporary .ipynb path (does NOT overwrite the source file).
"""

from __future__ import annotations

from app import PracticeState
from src.notebook.loader import load_notebook, assemble_and_save


def assemble_notebook(state: PracticeState) -> dict:
    source_nb = load_notebook(state["notebook_path"])

    output_path = assemble_and_save(
        source_nb=source_nb,
        revised_code_cells=state["revised_cells"],
        formatted_markdown_cells=state["markdown_cells"],
    )

    return {
        "current_stage": "assemble_notebook",
        "overall_progress": 85,
        "status_message": "노트북 조립 완료 — 교수자 검토 대기 중",
        "output_path": output_path,
        "review_status": "pending",
    }
