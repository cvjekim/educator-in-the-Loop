"""
Tests for manager pipeline compilation and routing logic.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END

from src.graph.pipeline import build_graph, _route_after_review, _route_after_reflection, _route_next_task


def test_build_graph_compiles():
    assert build_graph() is not None


def test_build_graph_with_checkpointer():
    assert build_graph(MemorySaver()) is not None


# --- HITL routing ---

def test_route_approved():
    assert _route_after_review({"review_status": "approved"}) == "plan_dispatch"


def test_route_needs_revision():
    assert _route_after_review({"review_status": "needs_revision"}) == "parse_course_plan"


def test_route_pending():
    assert _route_after_review({"review_status": "pending"}) == "parse_course_plan"


# --- Reflection routing ---

def test_route_reflection_retry():
    assert _route_after_reflection({"quality_flag": "retry"}) == "invoke_sub_agent"


def test_route_reflection_ok():
    assert _route_after_reflection({"quality_flag": "ok"}) == "collect_result"


# --- Loop routing ---

def test_route_next_task_has_remaining():
    state = {"remaining_tasks": [{"task_type": "lecture", "week": 2, "subject": "s", "context": "c"}]}
    assert _route_next_task(state) == "plan_dispatch"


def test_route_next_task_empty():
    assert _route_next_task({"remaining_tasks": []}) == END


def test_route_next_task_missing_key():
    assert _route_next_task({}) == END
