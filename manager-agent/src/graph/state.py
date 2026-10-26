"""
ManagerState — canonical TypedDict for the LangGraph StateGraph.
Defined here (not in app.py) so nodes and tests can import without Streamlit.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict


class TaskSpec(TypedDict):
    task_type: str      # 'lecture' | 'practice' | 'exam' | 'project'
    week: int
    subject: str
    context: str        # extracted context for the sub-agent


class ManagerState(TypedDict):
    # --- Input ---
    syllabus: str
    rubric_guidelines: str

    # --- Pipeline control ---
    current_stage: str
    review_status: str          # 'pending' | 'approved' | 'needs_revision'
    feedback: str

    # --- Task queue (loop driver) ---
    task_queue: List[TaskSpec]          # full parsed task list
    current_task: Optional[TaskSpec]    # task currently being processed
    remaining_tasks: List[TaskSpec]     # tasks yet to be dispatched

    # --- Current execution (reflection) ---
    current_result: Optional[dict]      # result from invoke_sub_agent
    reflection_count: int               # retry counter per task
    max_reflections: int                # default: 2
    quality_flag: str                   # 'ok' | 'retry'
    quality_notes: str                  # LLM quality review comment

    # --- Accumulated results ---
    results: List[dict]


__all__ = ["ManagerState", "TaskSpec"]
