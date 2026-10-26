"""
ProjectState — canonical TypedDict for the LangGraph StateGraph.
Re-exported from app.py for use in pipeline nodes.
"""

from app import EvaluationDraft, ProjectState, RosterEntry

__all__ = ["ProjectState", "RosterEntry", "EvaluationDraft"]
