"""
Tests for LangGraph pipeline compilation and routing logic.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END

from src.graph.pipeline import build_graph, _route_after_review


def test_build_graph_compiles():
    assert build_graph() is not None


def test_build_graph_with_checkpointer():
    assert build_graph(MemorySaver()) is not None


def test_route_approved():
    assert _route_after_review({"review_status": "approved"}) == "export_evaluation"


def test_route_needs_revision():
    assert _route_after_review({"review_status": "needs_revision"}) == "evaluate_project"


def test_route_pending():
    assert _route_after_review({"review_status": "pending"}) == "evaluate_project"
