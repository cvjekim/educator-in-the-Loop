"""Shared state contracts; importable without the Streamlit UI."""
from __future__ import annotations
from typing import Optional

class QuestionParam(TypedDict):
    """A single question-type configuration."""
    question_type: str   # "single_choice" | "short_answer" | "open_answer"
    count: int

class ExamState(TypedDict):
    """Full state carried through the LangGraph pipeline."""
    subject_name:  str
    parameters:    list[QuestionParam]
    questions:     list[dict]
    rubrics:       list[dict]
    final_output:  Optional[dict]
    review_status: str    # "pending" | "approved" | "needs_revision"
    feedback:      str
