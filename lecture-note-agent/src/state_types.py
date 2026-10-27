"""Shared state contracts; importable without the Streamlit UI."""
from __future__ import annotations
from typing import List, Literal, Optional, TypedDict

class DraftOutline(TypedDict):
    intro_slide: str        # trend-augmented intro content
    main_slides: List[str]

class LectureState(TypedDict):
    # --- Professor input ---
    subject: str            # e.g. "sample-course"
    week: int               # lecture week number
    topic: str              # weekly topic title
    guidelines: str         # directional notes from the professor

    # --- Pipeline control ---
    current_stage: str      # active node name
    overall_progress: int   # 0–100, drives st.progress
    status_message: str     # micro-task description, drives st.status
    review_status: Literal["pending", "approved", "rejected"]

    # --- Content ---
    raw_context: str                    # merged text from PPTs/PDFs
    draft_outline: Optional[DraftOutline]
    final_output: Optional[str]
