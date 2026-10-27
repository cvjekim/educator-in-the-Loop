"""
Node: revise_code
LLM rewrites code cells according to professor guidelines.
On the first pass: revises all code cells.
On retry (after self_reflect fail): revises only the cell that failed execution.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
from langchain_core.messages import HumanMessage, SystemMessage

from src.state_types import PracticeState, NotebookCell

_PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "revise_code.md"
_system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")


def _revise_cell(llm: ChatOpenAI, cell: NotebookCell, guidelines: str) -> NotebookCell:
    response = llm.invoke([
        SystemMessage(content=_system_prompt),
        HumanMessage(content=f"가이드라인:\n{guidelines}\n\n원본 코드:\n{cell['source']}"),
    ])
    return {**cell, "source": response.content.strip()}


def revise_code(state: PracticeState) -> dict:
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    guidelines = state["guidelines"]
    execution_result = state.get("execution_result")

    if execution_result and not execution_result["success"]:
        # Retry: revise only the failed cell
        failed_idx = execution_result.get("cell_index")
        revised = list(state["revised_cells"])
        for i, cell in enumerate(revised):
            if cell["index"] == failed_idx:
                revised[i] = _revise_cell(llm, cell, guidelines)
                break
    else:
        # First pass: revise all code cells
        revised = [_revise_cell(llm, cell, guidelines) for cell in state["code_cells"]]

    return {
        "current_stage": "revise_code",
        "overall_progress": 30 + state.get("iteration_count", 0) * 10,
        "status_message": f"코드 수정 중… (반복 {state.get('iteration_count', 0) + 1}회)",
        "revised_cells": revised,
        "code_quality": "fail",     # self_reflect will update this
    }
