"""
Node: summarize_project
Compresses each student's crawled repository into a single project summary.
Token-limited: truncates file content before sending to LLM.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "summarize.md"
_MAX_CONTENT_CHARS = 6_000   # per student — keeps prompt within context window


def _build_context(repo_data: dict) -> str:
    """Build a truncated text block from readme + source files."""
    parts = []

    readme = repo_data.get("readme", "")
    if readme:
        parts.append(f"## README\n{readme[:2000]}")

    for f in repo_data.get("files", []):
        snippet = f["content"][:500]
        parts.append(f"### {f['path']}\n{snippet}")
        if sum(len(p) for p in parts) >= _MAX_CONTENT_CHARS:
            break

    return "\n\n".join(parts)


def summarize_project(state: dict) -> dict:
    """
    State reads:  crawled_data, roster
    State writes: summaries
    """
    crawled_data: dict   = state["crawled_data"]
    roster: list[dict]   = state["roster"]
    system_prompt        = _PROMPT_PATH.read_text(encoding="utf-8")

    llm       = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    summaries = {}

    id_to_name = {e["student_id"]: e.get("name", e["student_id"]) for e in roster}

    for student_id, repo_data in crawled_data.items():
        if not repo_data.get("readme") and not repo_data.get("files"):
            summaries[student_id] = "(Repository 접근 불가 또는 내용 없음)"
            continue

        context = _build_context(repo_data)
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"학생: {id_to_name.get(student_id, student_id)}\n\n{context}"),
        ])
        summaries[student_id] = response.content.strip()

    return {
        "current_stage": "summarize_project",
        "overall_progress": 55,
        "status_message": f"프로젝트 요약 완료 — {len(summaries)}명",
        "summaries": summaries,
    }
