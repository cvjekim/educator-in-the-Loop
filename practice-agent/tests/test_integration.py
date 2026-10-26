"""
Integration tests for the self-reflect loop and HITL interrupt behaviour.
Uses mocked LLM calls to avoid real API usage.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import nbformat
import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.graph.pipeline import build_graph
from src.notebook.loader import load_notebook, split_cells


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_notebook(tmp_path: Path) -> str:
    nb = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell("# 실습"),
        nbformat.v4.new_code_cell("x = 1 + 1\nprint(x)"),
    ])
    path = tmp_path / "test.ipynb"
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    return str(path)


@pytest.fixture
def initial_state(simple_notebook: str) -> dict:
    nb = load_notebook(simple_notebook)
    code_cells, markdown_cells = split_cells(nb)
    return {
        "subject": "deep-learning",
        "guidelines": "deprecated 라이브러리 교체",
        "notebook_path": simple_notebook,
        "current_stage": "",
        "overall_progress": 0,
        "status_message": "",
        "code_quality": "fail",
        "iteration_count": 0,
        "max_iterations": 3,
        "review_status": "pending",
        "code_cells": code_cells,
        "markdown_cells": markdown_cells,
        "revised_cells": [],
        "execution_result": None,
        "output_path": None,
    }


# ---------------------------------------------------------------------------
# Self-reflect loop: passes on clean code
# ---------------------------------------------------------------------------

def test_self_reflect_passes_on_valid_code(initial_state):
    """self_reflect should set code_quality='pass' when all cells execute cleanly."""
    from src.graph.nodes.self_reflect import self_reflect

    state = {**initial_state, "revised_cells": initial_state["code_cells"]}
    result = self_reflect(state)
    assert result["code_quality"] == "pass"
    assert result["execution_result"]["success"] is True


def test_self_reflect_fails_on_syntax_error(initial_state):
    """self_reflect should set code_quality='fail' on a SyntaxError."""
    from src.graph.nodes.self_reflect import self_reflect

    broken_cell = {**initial_state["code_cells"][0], "source": "def broken(:\n    pass"}
    state = {**initial_state, "revised_cells": [broken_cell]}
    result = self_reflect(state)
    assert result["code_quality"] == "fail"
    assert result["execution_result"]["success"] is False


# ---------------------------------------------------------------------------
# HITL: graph pauses before human_review
# ---------------------------------------------------------------------------

def test_graph_pauses_before_human_review(initial_state):
    """Pipeline should interrupt before human_review node."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread = {"configurable": {"thread_id": "test-hitl"}}

    with (
        patch("src.graph.nodes.revise_code.ChatOpenAI") as mock_llm_cls,
        patch("src.graph.nodes.format_markdown.ChatOpenAI") as mock_fmt_cls,
    ):
        mock_response = MagicMock()
        mock_response.content = initial_state["code_cells"][0]["source"]
        mock_llm_cls.return_value.invoke.return_value = mock_response
        mock_fmt_cls.return_value.invoke.return_value = mock_response

        result = graph.invoke(initial_state, config=thread)

    # Graph should stop at human_review interrupt
    snapshot = graph.get_state(thread)
    assert "human_review" in (snapshot.next or [])


def test_graph_resumes_after_approval(initial_state, tmp_path, monkeypatch):
    """Graph should proceed to export_notebook after review_status='approved'."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    thread = {"configurable": {"thread_id": "test-approve"}}

    with (
        patch("src.graph.nodes.revise_code.ChatOpenAI") as mock_llm_cls,
        patch("src.graph.nodes.format_markdown.ChatOpenAI") as mock_fmt_cls,
    ):
        mock_response = MagicMock()
        mock_response.content = "x = 1"
        mock_llm_cls.return_value.invoke.return_value = mock_response
        mock_fmt_cls.return_value.invoke.return_value = mock_response

        graph.invoke(initial_state, config=thread)

    # Export into an isolated workspace, never the repository's subjects/.
    monkeypatch.chdir(tmp_path)
    # Simulate professor approval
    graph.update_state(thread, {"review_status": "approved"})
    final = graph.invoke(None, config=thread)

    assert final.get("overall_progress") == 100
    assert (tmp_path / final["output_path"]).is_file()
