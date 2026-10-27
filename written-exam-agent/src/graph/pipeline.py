"""
LangGraph StateGraph assembly.

Nodes (in order):
    generate_questions → draft_rubric
    → [interrupt_before] human_review
    → format_exam
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.state_types import ExamState
from src.graph.nodes.generate_questions import generate_questions
from src.graph.nodes.draft_rubric import draft_rubric
from src.graph.nodes.human_review import human_review
from src.graph.nodes.format_exam import format_exam


def _route_after_review(state: ExamState) -> str:
    """Route from human_review based on professor decision."""
    if state.get("review_status") == "approved":
        return "format_exam"
    return "generate_questions"


def build_graph(checkpointer: MemorySaver | None = None):
    """
    Build and compile the written-exam pipeline.

    A MemorySaver checkpointer is required for interrupt_before=["human_review"]
    to pause execution between generation and professor review.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(ExamState)

    graph.add_node("generate_questions", generate_questions)
    graph.add_node("draft_rubric", draft_rubric)
    graph.add_node("human_review", human_review)
    graph.add_node("format_exam", format_exam)

    graph.set_entry_point("generate_questions")
    graph.add_edge("generate_questions", "draft_rubric")
    graph.add_edge("draft_rubric", "human_review")
    graph.add_conditional_edges(
        "human_review",
        _route_after_review,
        {"format_exam": "format_exam", "generate_questions": "generate_questions"},
    )
    graph.add_edge("format_exam", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
