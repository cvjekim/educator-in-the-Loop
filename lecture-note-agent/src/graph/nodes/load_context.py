"""
Node: load_context
Reads subject configuration and extracts text from PPTs/PDFs.
Populates state["raw_context"] exclusively from reference materials.
"""

from src.state_types import LectureState
from src.context.loader import load_subject_context


def load_context(state: LectureState) -> LectureState:
    raw_context = load_subject_context(state["subject"], state["week"])
    return {
        **state,
        "current_stage": "load_context",
        "overall_progress": 25,
        "status_message": "Parsing lecture materials…",
        "raw_context": raw_context,
    }
