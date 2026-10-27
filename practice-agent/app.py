"""
Practice Agent — Streamlit entry point.

Pipeline: parse_notebook → revise_code → self_reflect (loop)
          → format_markdown → assemble_notebook
          → [HITL] human_review
          → export_notebook
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import List, Literal, Optional, TypedDict

import streamlit as st
from src.state_types import NotebookCell, ExecutionResult, PracticeState
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# TypedDicts — single source of truth for the LangGraph StateGraph
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# Available subjects
# ---------------------------------------------------------------------------

SUBJECTS = sorted(p.name for p in (Path(__file__).parent / "subjects").glob("*") if p.is_dir()) or ["sample-course"]


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    defaults: dict = {
        "ui_stage": "input",        # "input" | "review" | "output"
        "graph_state": None,        # PracticeState dict after graph run
        "graph": None,              # compiled LangGraph (holds MemorySaver)
        "thread_id": None,          # LangGraph checkpoint thread id
        "tmp_notebook_path": None,  # uploaded file temp path
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
        },
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# OpenAI usage tracking
# ---------------------------------------------------------------------------

# blended estimate: practice uses gpt-4o (revise) + gpt-4o-mini (format)
_PRICE_INPUT_PER_1M  = 1.50   # rough average (USD)
_PRICE_OUTPUT_PER_1M = 5.00


def _invoke_with_tracking(graph, input_state, config: dict):
    """Wrap graph.invoke with UsageMetadataCallbackHandler and accumulate session usage."""
    from langchain_core.callbacks import UsageMetadataCallbackHandler

    cb = UsageMetadataCallbackHandler()
    tracked_config = {**config, "callbacks": [cb]}
    result = graph.invoke(input_state, tracked_config)

    for meta in cb.usage_metadata.values():
        st.session_state.usage["input_tokens"]  += meta.get("input_tokens", 0)
        st.session_state.usage["output_tokens"] += meta.get("output_tokens", 0)

    return result


def _session_cost() -> float:
    u = st.session_state.usage
    return (
        u["input_tokens"]  / 1_000_000 * _PRICE_INPUT_PER_1M
        + u["output_tokens"] / 1_000_000 * _PRICE_OUTPUT_PER_1M
    )


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _stage_badge(label: str, active: bool) -> str:
    return f"**→ {label}**" if active else label


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.title("Practice Agent")
        st.caption("실습 자료(.ipynb) 최신화 에이전트")
        st.divider()

        ui_stage = st.session_state.get("ui_stage", "input")
        st.markdown(_stage_badge("1. 파일 업로드 및 수정", ui_stage == "input"))
        st.markdown(_stage_badge("2. 검토 (HITL)", ui_stage == "review"))
        st.markdown(_stage_badge("3. 완료 및 다운로드", ui_stage == "output"))

        state: Optional[PracticeState] = st.session_state.get("graph_state")
        if state:
            st.divider()
            st.caption(f"**Subject**: {state['subject']}")
            st.caption(f"**Node**: `{state['current_stage']}`")
            iter_count = state.get("iteration_count", 0)
            max_iter   = state.get("max_iterations", 5)
            quality    = state.get("code_quality", "-")
            quality_label = "✅ PASS" if quality == "pass" else f"⚠️ {quality.upper()}"
            st.caption(f"**반복**: {iter_count} / {max_iter}")
            st.caption(f"**코드 품질**: {quality_label}")
            st.progress(state["overall_progress"])
            st.caption(state["status_message"])

        st.divider()
        st.caption("**OpenAI Usage (이번 세션)**")
        u = st.session_state.get("usage", {"input_tokens": 0, "output_tokens": 0})
        total = u["input_tokens"] + u["output_tokens"]
        st.caption(f"토큰: {total:,}")
        st.caption(f"↳ in {u['input_tokens']:,} / out {u['output_tokens']:,}")
        st.caption(f"추정 비용: **${_session_cost():.4f}**")
        st.caption("※ gpt-4o / gpt-4o-mini 혼합 요율 기준")


# ---------------------------------------------------------------------------
# Stage 1 — Input & Pipeline Run
# ---------------------------------------------------------------------------

def render_input_stage() -> None:
    st.header("Stage 1: 실습 파일 업로드")
    st.caption(
        "수정할 `.ipynb` 파일을 업로드하고 가이드라인을 입력하세요. "
        "에이전트가 코드를 자동 수정하고 실행 검증합니다."
    )

    with st.form("practice_input_form"):
        subject = st.selectbox("과목", SUBJECTS)
        notebook_file = st.file_uploader("실습 파일 (.ipynb)", type=["ipynb"])
        guidelines = st.text_area(
            "수정 가이드라인",
            placeholder=(
                "예: deprecated 라이브러리 교체, TF1 → TF2 마이그레이션,\n"
                "scikit-learn 최신 API 적용, Agent 실습 셀 추가..."
            ),
            height=150,
        )
        max_iter = st.number_input(
            "자가 수정 최대 반복 횟수",
            min_value=1,
            max_value=10,
            value=5,
            help="self_reflect 루프 상한. 이 횟수 도달 시 실패 상태로도 다음 단계 진행.",
        )
        submitted = st.form_submit_button("수정 시작 →", type="primary")

    if submitted:
        if notebook_file is None:
            st.error(".ipynb 파일을 업로드하세요.")
            return
        # Save uploaded file to a persistent temp path
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ipynb")
        tmp.write(notebook_file.getvalue())
        tmp.close()
        notebook_path = tmp.name
        st.session_state.tmp_notebook_path = notebook_path

        from src.graph.pipeline import build_graph

        initial_state: PracticeState = {
            "subject": subject,
            "guidelines": guidelines.strip(),
            "notebook_path": notebook_path,
            "current_stage": "parse_notebook",
            "overall_progress": 0,
            "status_message": "파이프라인 시작 중…",
            "code_quality": "fail",
            "iteration_count": 0,
            "max_iterations": int(max_iter),
            "review_status": "pending",
            "code_cells": [],
            "markdown_cells": [],
            "revised_cells": [],
            "execution_result": None,
            "output_path": None,
        }

        thread_id = str(uuid.uuid4())
        graph = build_graph()
        config = {"configurable": {"thread_id": thread_id}}

        with st.status("Stage 1 실행 중 — 코드 수정 및 자가 검증…", expanded=True) as status:
            st.write("📂 노트북 파싱 중…")
            st.write("🔧 코드 셀 수정 중 (gpt-4o)…")
            st.write("⚙️ 코드 실행 및 self-reflect 루프…")
            st.write("📝 마크다운 포맷팅 중 (gpt-4o-mini)…")
            st.write("🔗 노트북 조립 중…")
            graph_state = _invoke_with_tracking(graph, initial_state, config)
            status.update(label="수정 완료 — 교수자 검토 대기 중", state="complete")

        st.session_state.graph       = graph
        st.session_state.thread_id   = thread_id
        st.session_state.graph_state = graph_state
        st.session_state.ui_stage    = "review"
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 2 — Human Review (HITL pause)
# ---------------------------------------------------------------------------

def render_review_stage() -> None:
    import nbformat

    state: PracticeState = st.session_state.graph_state

    st.header("Stage 2: 수정된 노트북 검토")
    st.caption(
        "코드 수정 결과를 확인하고 **승인** 또는 **처음부터 재시작**하세요. "
        "재시작 시 새 가이드라인을 입력할 수 있습니다."
    )

    st.progress(state["overall_progress"], text=state["status_message"])

    # --- Execution summary metrics ---
    iter_count  = state.get("iteration_count", 0)
    max_iter    = state.get("max_iterations", 5)
    quality     = state.get("code_quality", "fail")
    revised_cells = state.get("revised_cells", [])
    exec_result: Optional[ExecutionResult] = state.get("execution_result")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("자가 수정 반복", f"{iter_count} / {max_iter}")
    col_b.metric("코드 품질", "✅ PASS" if quality == "pass" else "⚠️ FAIL (max 도달)")
    col_c.metric("수정된 코드 셀 수", len(revised_cells))

    # Show last execution error if max_iterations reached with failure
    if exec_result and not exec_result.get("success"):
        with st.expander("⚠️ 마지막 실행 오류 (max_iterations 도달 시 표시)", expanded=True):
            failed_cell = exec_result.get("cell_index")
            if failed_cell is not None:
                st.warning(f"실패 셀: Cell {failed_cell}")
            st.error(exec_result.get("error") or "알 수 없는 오류")
            tb = exec_result.get("traceback")
            if tb:
                st.code(tb, language="python")

    st.divider()

    # --- Notebook cell-by-cell preview ---
    st.subheader("수정된 노트북 미리보기")
    output_path = state.get("output_path")

    if output_path and Path(output_path).exists():
        nb = nbformat.read(output_path, as_version=4)
        total_cells = len(nb.cells)
        st.caption(f"전체 셀: {total_cells}개 | 코드 셀: {len(revised_cells)}개")

        for i, cell in enumerate(nb.cells):
            if cell.cell_type == "code":
                label = f"💻 Code Cell [{i}]"
                # Mark if this cell was the one that failed
                if (exec_result and not exec_result.get("success")
                        and exec_result.get("cell_index") == i):
                    label += "  ⚠️ 오류 발생 셀"
                with st.expander(label, expanded=False):
                    st.code(cell.source or "(빈 셀)", language="python")
            elif cell.cell_type == "markdown":
                with st.expander(f"📝 Markdown Cell [{i}]", expanded=False):
                    st.markdown(cell.source or "*(빈 셀)*")
    else:
        st.warning("조립된 노트북 파일을 찾을 수 없습니다.")

    st.divider()

    # --- Approve / Restart ---
    col_approve, col_restart = st.columns([1, 4])
    with col_approve:
        approved = st.button("승인 및 저장 →", type="primary")
    with col_restart:
        restarted = st.button("↺ 처음부터 (새 가이드라인)")

    if approved:
        graph  = st.session_state.graph
        config = {"configurable": {"thread_id": st.session_state.thread_id}}
        graph.update_state(config, {"review_status": "approved"})

        with st.status("저장 중…", expanded=True) as status:
            st.write("💾 최종 파일 저장 중…")
            result = _invoke_with_tracking(graph, None, config)
            status.update(label="저장 완료!", state="complete")

        st.session_state.graph_state = result
        st.session_state.ui_stage    = "output"
        st.rerun()

    if restarted:
        _cleanup_and_reset()


# ---------------------------------------------------------------------------
# Stage 3 — Output & Download
# ---------------------------------------------------------------------------

def render_output_stage() -> None:
    state: PracticeState = st.session_state.graph_state

    st.header("Stage 3: 완료")
    st.caption("수정된 노트북이 저장되었습니다. 다운로드하거나 경로를 확인하세요.")

    st.progress(state["overall_progress"], text=state["status_message"])

    output_path = state.get("output_path", "")
    if output_path and Path(output_path).exists():
        st.success(f"저장 경로: `{output_path}`")
        nb_bytes = Path(output_path).read_bytes()
        st.download_button(
            label="⬇ 노트북 다운로드 (.ipynb)",
            data=nb_bytes,
            file_name=Path(output_path).name,
            mime="application/x-ipynb+json",
        )
    else:
        st.warning("저장된 파일 경로를 찾을 수 없습니다.")

    st.divider()

    # Final stats
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("총 반복 횟수", state.get("iteration_count", 0))
    col_b.metric(
        "최종 코드 품질",
        "✅ PASS" if state.get("code_quality") == "pass" else "⚠️ MAX 도달",
    )
    col_c.metric("수정된 코드 셀", len(state.get("revised_cells", [])))

    st.divider()
    if st.button("↺ 새 파일 처리"):
        _cleanup_and_reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cleanup_and_reset() -> None:
    """Delete temp notebook file and reset session state to input stage."""
    tmp_path = st.session_state.get("tmp_notebook_path")
    if tmp_path:
        Path(tmp_path).unlink(missing_ok=True)
    for key in ("ui_stage", "graph_state", "graph", "thread_id",
                "tmp_notebook_path", "usage"):
        st.session_state.pop(key, None)
    st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Practice Agent",
        page_icon="🧪",
        layout="wide",
    )
    _init_session_state()
    render_sidebar()

    ui_stage = st.session_state.ui_stage
    if ui_stage == "input":
        render_input_stage()
    elif ui_stage == "review":
        render_review_stage()
    elif ui_stage == "output":
        render_output_stage()


if __name__ == "__main__":
    main()
