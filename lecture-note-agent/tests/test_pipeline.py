"""
Tests for LangGraph pipeline state transitions.

Focus: interrupt before human_review, no progress past human_review without approval.
"""

import pytest
from unittest.mock import patch, MagicMock


INITIAL_STATE = {
    "subject": "machine-learning",
    "week": 3,
    "topic": "Logistic Regression",
    "guidelines": "",
    "current_stage": "guide_content",
    "overall_progress": 0,
    "status_message": "",
    "review_status": "pending",
    "raw_context": "",
    "draft_outline": None,
    "final_output": None,
}


class TestPipelineRouting:
    def test_does_not_reach_analysis_without_approval(self):
        """Pipeline must not advance past human_review when review_status != 'approved'."""
        from src.graph.pipeline import _should_continue

        state = {**INITIAL_STATE, "review_status": "pending"}
        result = _should_continue(state)
        assert result != "analysis_content"

    def test_routes_to_analysis_on_approval(self):
        from src.graph.pipeline import _should_continue

        state = {**INITIAL_STATE, "review_status": "approved"}
        result = _should_continue(state)
        assert result == "analysis_content"
