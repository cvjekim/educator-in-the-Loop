"""
LangGraph StateGraph assembly.

Workflow:
    parse_course_plan
    → [interrupt_before] human_review
    → plan_dispatch → invoke_sub_agent → reflect_quality (reflection loop)
    → collect_result → [loop: plan_dispatch | END]

Key patterns:
    Loop       : collect_result → plan_dispatch while remaining_tasks
    Reflection : reflect_quality → invoke_sub_agent while quality_flag == 'retry'
    HITL       : interrupt_before=["human_review"]
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.graph.state import ManagerState
from src.graph.nodes.parse_course_plan import parse_course_plan
from src.graph.nodes.human_review import human_review
from src.graph.nodes.plan_dispatch import plan_dispatch
from src.graph.nodes.invoke_sub_agent import invoke_sub_agent
from src.graph.nodes.reflect_quality import reflect_quality
from src.graph.nodes.collect_result import collect_result


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def _route_after_review(state: ManagerState) -> str:
    """Post-HITL: approved → start dispatching; needs_revision → re-parse."""
    if state.get("review_status") == "approved":
        return "plan_dispatch"
    return "parse_course_plan"


def _route_after_reflection(state: ManagerState) -> str:
    """Reflection loop: retry → invoke again; ok → collect result."""
    if state.get("quality_flag") == "retry":
        return "invoke_sub_agent"
    return "collect_result"


def _route_next_task(state: ManagerState) -> str:
    """Task loop: more tasks remaining → dispatch next; done → END."""
    if state.get("remaining_tasks"):
        return "plan_dispatch"
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(checkpointer: MemorySaver | None = None):
    """
    Build and compile the manager pipeline.

    MemorySaver checkpointer is required for interrupt_before=["human_review"]
    to pause between task-plan analysis and professor approval.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(ManagerState)

    graph.add_node("parse_course_plan", parse_course_plan)
    graph.add_node("human_review",      human_review)
    graph.add_node("plan_dispatch",     plan_dispatch)
    graph.add_node("invoke_sub_agent",  invoke_sub_agent)
    graph.add_node("reflect_quality",   reflect_quality)
    graph.add_node("collect_result",    collect_result)

    graph.set_entry_point("parse_course_plan")
    graph.add_edge("parse_course_plan", "human_review")
    graph.add_conditional_edges(
        "human_review",
        _route_after_review,
        {"plan_dispatch": "plan_dispatch", "parse_course_plan": "parse_course_plan"},
    )
    graph.add_edge("plan_dispatch", "invoke_sub_agent")
    graph.add_edge("invoke_sub_agent", "reflect_quality")
    graph.add_conditional_edges(
        "reflect_quality",
        _route_after_reflection,
        {"invoke_sub_agent": "invoke_sub_agent", "collect_result": "collect_result"},
    )
    graph.add_conditional_edges(
        "collect_result",
        _route_next_task,
        {"plan_dispatch": "plan_dispatch", END: END},
    )

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
