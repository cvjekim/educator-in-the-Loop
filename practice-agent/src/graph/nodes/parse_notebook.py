"""
Node: parse_notebook
Loads the .ipynb file and splits cells into code_cells and markdown_cells.
"""

from app import PracticeState
from src.notebook.loader import load_notebook, split_cells


def parse_notebook(state: PracticeState) -> dict:
    notebook = load_notebook(state["notebook_path"])
    code_cells, markdown_cells = split_cells(notebook)

    return {
        "current_stage": "parse_notebook",
        "overall_progress": 10,
        "status_message": f"노트북 파싱 완료 — 코드 셀 {len(code_cells)}개, 마크다운 셀 {len(markdown_cells)}개",
        "code_cells": code_cells,
        "markdown_cells": markdown_cells,
        "revised_cells": [],
        "iteration_count": 0,
    }
