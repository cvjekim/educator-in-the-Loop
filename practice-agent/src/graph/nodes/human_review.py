"""
Node: human_review
Passthrough node — execution is paused here by interrupt_before=["human_review"].
The Streamlit UI reads state["output_path"], renders the notebook preview,
and updates review_status to 'approved' or 'rejected' before resuming the graph.
"""

from app import PracticeState


def human_review(state: PracticeState) -> dict:
    # This node is never actually executed; LangGraph interrupts before it.
    # Included for graph completeness and testability.
    return {}
