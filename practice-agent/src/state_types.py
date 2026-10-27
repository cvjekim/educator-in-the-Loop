"""Shared state contracts; importable without the Streamlit UI."""
from __future__ import annotations
from typing import List, Literal, Optional, TypedDict

class NotebookCell(TypedDict):
    index: int
    cell_type: str      # 'code' | 'markdown'
    source: str
    outputs: list

class ExecutionResult(TypedDict):
    success: bool
    error: Optional[str]
    traceback: Optional[str]
    cell_index: Optional[int]

class PracticeState(TypedDict):
    # --- Professor input ---
    subject: str
    guidelines: str
    notebook_path: str          # path to source .ipynb

    # --- Pipeline control ---
    current_stage: str
    overall_progress: int       # 0–100, drives st.progress
    status_message: str         # micro-task description
    code_quality: str           # 'pass' | 'fail'
    iteration_count: int        # self-reflect loop counter
    max_iterations: int         # default: 5
    review_status: Literal["pending", "approved", "rejected"]

    # --- Content ---
    code_cells: List[NotebookCell]
    markdown_cells: List[NotebookCell]
    revised_cells: List[NotebookCell]
    execution_result: Optional[ExecutionResult]

    # --- Output ---
    output_path: Optional[str]
