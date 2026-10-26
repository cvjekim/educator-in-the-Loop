"""
LangGraph StateGraph assembly.

Nodes (in order):
    guide_content → load_context → draft_content
    → [interrupt_before] human_review
    → analysis_content → format_output
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from app import LectureState
from src.graph.nodes.guide_content import guide_content
from src.graph.nodes.load_context import load_context
from src.graph.nodes.draft_content import draft_content
from src.graph.nodes.human_review import human_review
from src.graph.nodes.analysis_content import analysis_content
from src.graph.nodes.format_output import format_output


def _should_continue(state: LectureState) -> str:
    """Route from human_review based on professor decision."""
    if state["review_status"] == "approved":
        return "analysis_content"
    return END


def build_graph(checkpointer: MemorySaver | None = None) -> StateGraph:
    """
    Build and compile the lecture-note pipeline.

    A MemorySaver checkpointer is required for interrupt_before=["human_review"]
    to actually pause execution between Stage 1 and Stage 2.
    Pass a shared MemorySaver instance when multiple runs need to share state
    (e.g. across Streamlit reruns for the same thread_id).
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(LectureState)

    graph.add_node("guide_content", guide_content)
    graph.add_node("load_context", load_context)
    graph.add_node("draft_content", draft_content)
    graph.add_node("human_review", human_review)
    graph.add_node("analysis_content", analysis_content)
    graph.add_node("format_output", format_output)

    graph.set_entry_point("guide_content")
    graph.add_edge("guide_content", "load_context")
    graph.add_edge("load_context", "draft_content")
    graph.add_edge("draft_content", "human_review")
    graph.add_conditional_edges("human_review", _should_continue)
    graph.add_edge("analysis_content", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
