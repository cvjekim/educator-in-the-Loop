"""Shared state contracts; importable without the Streamlit UI."""
from __future__ import annotations
from typing import List, Literal, Optional, TypedDict

class RosterEntry(TypedDict):
    student_id: str
    name: str
    github_id: str
    repo_name: str

class EvaluationDraft(TypedDict):
    student_id: str
    name: str
    summary: str
    feedback_items: dict        # {rubric_item: str}
    overall_feedback: str

class ProjectState(TypedDict):
    # Input
    rubric_guidelines: str
    roster: List[RosterEntry]
    # Pipeline control
    current_stage: str
    overall_progress: int       # 0–100 → st.progress
    status_message: str
    review_status: Literal["pending", "approved", "needs_revision"]
    # Content
    rubric_prompt: str
    crawled_data: dict          # {student_id: {readme, files, has_required_outputs}}
    summaries: dict             # {student_id: str}
    evaluation_drafts: List[EvaluationDraft]
    # Output
    output_dir: Optional[str]
