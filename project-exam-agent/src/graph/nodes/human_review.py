"""
Node: human_review
Passthrough — LangGraph interrupts before this node executes.
The Streamlit UI reads evaluation_drafts, lets the professor edit,
then updates review_status before resuming the graph.
"""


def human_review(state: dict) -> dict:
    return {}
