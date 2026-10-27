"""
Node: format_markdown
Rewrites markdown cells into structured bullet-point form for readability.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
from langchain_core.messages import HumanMessage, SystemMessage

from src.state_types import PracticeState, NotebookCell

_PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "format_markdown.md"
_system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")


def _format_cell(llm: ChatOpenAI, cell: NotebookCell) -> NotebookCell:
    response = llm.invoke([
        SystemMessage(content=_system_prompt),
        HumanMessage(content=cell["source"]),
    ])
    return {**cell, "source": response.content.strip()}


def format_markdown(state: PracticeState) -> dict:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    formatted = [_format_cell(llm, cell) for cell in state["markdown_cells"]]

    return {
        "current_stage": "format_markdown",
        "overall_progress": 75,
        "status_message": f"마크다운 셀 정리 완료 — {len(formatted)}개 셀",
        "markdown_cells": formatted,
    }
