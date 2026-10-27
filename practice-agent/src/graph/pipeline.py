"""
LangGraph StateGraph assembly.

Nodes (in order):
    parse_notebook → revise_code → self_reflect (loop)
    → format_markdown → assemble_notebook
    → [interrupt_before] human_review
    → export_notebook
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.state_types import PracticeState
from src.graph.nodes.parse_notebook import parse_notebook
from src.graph.nodes.revise_code import revise_code
from src.graph.nodes.self_reflect import self_reflect
from src.graph.nodes.format_markdown import format_markdown
from src.graph.nodes.assemble_notebook import assemble_notebook
from src.graph.nodes.human_review import human_review
from src.graph.nodes.export_notebook import export_notebook


def _route_reflection(state: PracticeState) -> str:
    """Loop back to revise_code until code passes or max_iterations reached."""
    if state["code_quality"] == "pass" or state["iteration_count"] >= state["max_iterations"]:
        return "format_markdown"
    return "revise_code"


def _route_review(state: PracticeState) -> str:
    """Route from human_review based on professor decision."""
    if state["review_status"] == "approved":
        return "export_notebook"
    return END


def build_graph(checkpointer: MemorySaver | None = None) -> StateGraph:
    """
    Build and compile the practice-agent pipeline.

    MemorySaver checkpointer is required for interrupt_before=["human_review"]
    to pause execution between the self-reflect loop and professor approval.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(PracticeState)

    graph.add_node("parse_notebook", parse_notebook)
    graph.add_node("revise_code", revise_code)
    graph.add_node("self_reflect", self_reflect)
    graph.add_node("format_markdown", format_markdown)
    graph.add_node("assemble_notebook", assemble_notebook)
    graph.add_node("human_review", human_review)
    graph.add_node("export_notebook", export_notebook)

    graph.set_entry_point("parse_notebook")
    graph.add_edge("parse_notebook", "revise_code")
    graph.add_edge("revise_code", "self_reflect")
    graph.add_conditional_edges("self_reflect", _route_reflection)
    graph.add_edge("format_markdown", "assemble_notebook")
    graph.add_edge("assemble_notebook", "human_review")
    graph.add_conditional_edges("human_review", _route_review)
    graph.add_edge("export_notebook", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
