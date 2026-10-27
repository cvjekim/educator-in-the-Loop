"""
LangGraph StateGraph assembly.

Nodes (in order):
    init_rubric → crawl_github → summarize_project → evaluate_project
    → [interrupt_before] human_review
    → export_evaluation
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.state_types import ProjectState
from src.graph.nodes.init_rubric import init_rubric
from src.graph.nodes.crawl_github import crawl_github
from src.graph.nodes.summarize_project import summarize_project
from src.graph.nodes.evaluate_project import evaluate_project
from src.graph.nodes.human_review import human_review
from src.graph.nodes.export_evaluation import export_evaluation


def _route_after_review(state: ProjectState) -> str:
    if state.get("review_status") == "approved":
        return "export_evaluation"
    return "evaluate_project"


def build_graph(checkpointer: MemorySaver | None = None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(ProjectState)

    graph.add_node("init_rubric",        init_rubric)
    graph.add_node("crawl_github",       crawl_github)
    graph.add_node("summarize_project",  summarize_project)
    graph.add_node("evaluate_project",   evaluate_project)
    graph.add_node("human_review",       human_review)
    graph.add_node("export_evaluation",  export_evaluation)

    graph.set_entry_point("init_rubric")
    graph.add_edge("init_rubric",       "crawl_github")
    graph.add_edge("crawl_github",      "summarize_project")
    graph.add_edge("summarize_project", "evaluate_project")
    graph.add_edge("evaluate_project",  "human_review")
    graph.add_conditional_edges(
        "human_review",
        _route_after_review,
        {"export_evaluation": "export_evaluation", "evaluate_project": "evaluate_project"},
    )
    graph.add_edge("export_evaluation", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
