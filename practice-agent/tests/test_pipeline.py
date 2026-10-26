"""
Tests for LangGraph StateGraph compilation and routing logic.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.graph.pipeline import build_graph, _route_reflection, _route_review


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def test_build_graph_compiles():
    graph = build_graph()
    assert graph is not None


def test_build_graph_with_checkpointer():
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    assert graph is not None


# ---------------------------------------------------------------------------
# Routing: self_reflect → revise_code | format_markdown
# ---------------------------------------------------------------------------

def test_route_reflection_pass():
    state = {"code_quality": "pass", "iteration_count": 1, "max_iterations": 5}
    assert _route_reflection(state) == "format_markdown"


def test_route_reflection_fail_within_limit():
    state = {"code_quality": "fail", "iteration_count": 2, "max_iterations": 5}
    assert _route_reflection(state) == "revise_code"


def test_route_reflection_max_iterations_reached():
    state = {"code_quality": "fail", "iteration_count": 5, "max_iterations": 5}
    assert _route_reflection(state) == "format_markdown"


def test_route_reflection_max_iterations_exceeded():
    state = {"code_quality": "fail", "iteration_count": 6, "max_iterations": 5}
    assert _route_reflection(state) == "format_markdown"


# ---------------------------------------------------------------------------
# Routing: human_review → export_notebook | END
# ---------------------------------------------------------------------------

def test_route_review_approved():
    from langgraph.graph import END
    state = {"review_status": "approved"}
    assert _route_review(state) == "export_notebook"


def test_route_review_rejected():
    from langgraph.graph import END
    state = {"review_status": "rejected"}
    assert _route_review(state) == END


def test_route_review_pending():
    from langgraph.graph import END
    state = {"review_status": "pending"}
    assert _route_review(state) == END
