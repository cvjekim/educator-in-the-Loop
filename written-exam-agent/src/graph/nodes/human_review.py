"""
Node: human_review
Pass-through checkpoint.
interrupt_before=["human_review"] fires before this executes;
when the graph resumes, this node forwards state unchanged to the router.
"""


def human_review(state: dict) -> dict:
    return {}
