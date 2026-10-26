"""
Project Exam Agent — Streamlit entry point.

Pipeline: init_rubric → crawl_github → summarize_project → evaluate_project
          → [HITL] human_review
          → export_evaluation
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Literal, Optional, TypedDict

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


# ─── TypedDicts ───────────────────────────────────────────────────────────────

class RosterEntry(TypedDict):
    student_id: str
    name: str
    github_id: str
    repo_name: str


class EvaluationDraft(TypedDict):
    student_id: str
    name: str
    summary: str
    feedback_items: dict        # {rubric_item: str}
    overall_feedback: str


class ProjectState(TypedDict):
    # Input
    rubric_guidelines: str
    roster: List[RosterEntry]
    # Pipeline control
    current_stage: str
    overall_progress: int       # 0–100 → st.progress
    status_message: str
    review_status: Literal["pending", "approved", "needs_revision"]
    # Content
    rubric_prompt: str
    crawled_data: dict          # {student_id: {readme, files, has_required_outputs}}
    summaries: dict             # {student_id: str}
    evaluation_drafts: List[EvaluationDraft]
    # Output
    output_dir: Optional[str]


# ─── Constants ────────────────────────────────────────────────────────────────

# gpt-4o pricing (USD per 1M tokens) — dominant cost node is evaluate_project
_PRICE_INPUT_PER_1M  = 2.50
_PRICE_OUTPUT_PER_1M = 10.00

STAGE_STEPS = [
    ("idle",           "1. 루브릭 & 명단 입력"),
    ("running",        "2. 크롤링 및 평가 생성 중"),
    ("waiting_review", "3. 평가 초안 검토 (HITL)"),
    ("exporting",      "4. 리포트 저장 중"),
    ("done",           "5. 완료"),
]


# ─── Session state ────────────────────────────────────────────────────────────

def _init_session_state() -> None:
    defaults: dict = {
        "app_stage":     "idle",
        "thread_id":     str(uuid.uuid4()),
        "graph":         None,   # compiled LangGraph (holds MemorySaver)
        "project_state": None,
        "usage": {
            "input_tokens":  0,
            "output_tokens": 0,
        },
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _get_graph():
    """Lazily build the graph once and store in session_state."""
    if st.session_state.graph is None:
        from src.graph.pipeline import build_graph
        st.session_state.graph = build_graph()
    return st.session_state.graph


# ─── OpenAI usage tracking ────────────────────────────────────────────────────

def _invoke_with_tracking(graph, input_state, config: dict):
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _thread_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def _parse_roster(uploaded_file) -> List[RosterEntry]:
    """CSV or JSON roster file → list of RosterEntry."""
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
        return df.to_dict("records")
    return json.loads(uploaded_file.read().decode("utf-8"))


# ─── Sidebar ─────────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    with st.sidebar:
        st.title("📊 프로젝트 평가")
        st.divider()

        stage_keys  = [s[0] for s in STAGE_STEPS]
        current_idx = (
            stage_keys.index(st.session_state.app_stage)
            if st.session_state.app_stage in stage_keys else 0
        )
        for i, (_, label) in enumerate(STAGE_STEPS):
            if   i < current_idx:  st.success(f"✅ {label}")
            elif i == current_idx: st.info(f"▶ {label}")
            else:                  st.markdown(f"○ {label}")

        st.divider()
        st.caption("**OpenAI Usage (이번 세션)**")
        u = st.session_state.get("usage", {"input_tokens": 0, "output_tokens": 0})
        total = u["input_tokens"] + u["output_tokens"]
        st.caption(f"토큰: {total:,}")
        st.caption(f"↳ in {u['input_tokens']:,} / out {u['output_tokens']:,}")
        st.caption(f"추정 비용: **${_session_cost():.4f}**")
        st.caption("※ gpt-4o / gpt-4o-mini 혼합 요율 기준")

        st.divider()
        if st.button("↺ 초기화", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


# ─── Stage: idle ─────────────────────────────────────────────────────────────

def render_idle() -> None:
    st.header("Stage 1: 루브릭 & 학생 명단 입력")
    st.caption("평가 기준과 GitHub 계정이 포함된 학생 명단을 업로드하세요.")

    if "error_message" in st.session_state:
        st.error(st.session_state.pop("error_message"))

    with st.form("config_form"):
        rubric_guidelines = st.text_area(
            "루브릭 가이드라인",
            placeholder=(
                "예:\n"
                "- 기여도: 팀원별 역할 분담과 실질적 기여 내용\n"
                "- 완성도: 핵심 기능 구현 여부, README 충실도\n"
                "- 코드 품질: 가독성, 모듈화, 주석\n"
                "※ 수치 랭킹 없이 기여도 중심 정성 평가"
            ),
            height=200,
        )
        roster_file = st.file_uploader(
            "학생 명단 (CSV 또는 JSON)",
            type=["csv", "json"],
            help="필수 컬럼: student_id, name, github_id, repo_name",
        )
        st.caption("📎 형식 참고: `roster/sample_roster.csv`")
        submitted = st.form_submit_button("🚀 평가 시작", type="primary")

    if submitted:
        if not rubric_guidelines.strip():
            st.error("루브릭 가이드라인을 입력하세요.")
            return
        if roster_file is None:
            st.error("학생 명단 파일을 업로드하세요.")
            return
        try:
            roster = _parse_roster(roster_file)
        except Exception as e:
            st.error(f"명단 파일 파싱 오류: {e}")
            return

        # Fresh graph + thread for each new evaluation
        st.session_state.graph      = None
        st.session_state.thread_id  = str(uuid.uuid4())
        st.session_state.project_state = {
            "rubric_guidelines": rubric_guidelines.strip(),
            "roster":            roster,
            "current_stage":     "",
            "overall_progress":  0,
            "status_message":    "",
            "review_status":     "pending",
            "rubric_prompt":     "",
            "crawled_data":      {},
            "summaries":         {},
            "evaluation_drafts": [],
            "output_dir":        None,
        }
        st.session_state.app_stage = "running"
        st.rerun()


# ─── Stage: running ──────────────────────────────────────────────────────────

def render_running() -> None:
    """Invoke the pipeline up to the HITL interrupt (or resume after revision)."""
    graph       = _get_graph()
    cfg         = _thread_config()
    input_state = st.session_state.project_state   # initial dict or None (resume)
    n_students  = len((input_state or {}).get("roster", []))

    with st.status("🤖 에이전트 실행 중...", expanded=True) as status:
        try:
            st.write("📋 루브릭 구조화 중 (gpt-4o-mini)…")
            if input_state:   # first run — crawling needed
                st.write(f"🔍 GitHub 크롤링 중 — {n_students}명의 레포지토리…")
                st.write("📝 프로젝트 요약 중 (gpt-4o-mini)…")
            else:             # re-evaluation — skip crawling
                st.write("♻️ 기존 요약 데이터로 평가 재생성 중…")
            st.write("🧠 평가 초안 생성 중 (gpt-4o, temperature=0.3)…")

            _invoke_with_tracking(graph, input_state, cfg)

            st.write("✅ 평가 초안 생성 완료.")
            status.update(label="생성 완료 — 교수자 검토 대기 중", state="complete")

            st.session_state.project_state = None
            st.session_state.app_stage     = "waiting_review"

        except Exception as exc:
            status.update(label="오류 발생", state="error")
            st.session_state.error_message = str(exc)
            st.session_state.app_stage     = "idle"

    st.rerun()


# ─── Stage: waiting_review ───────────────────────────────────────────────────

def render_waiting_review() -> None:
    """HITL: professor edits evaluation drafts, then approves or requests re-evaluation."""
    graph = _get_graph()
    cfg   = _thread_config()

    st.header("Stage 3: 평가 초안 검토 (HITL)")
    st.caption(
        "각 학생의 평가 내용을 직접 수정한 뒤 승인하거나, "
        "재생성을 요청하세요. 재생성 시 크롤링 없이 평가 단계만 재실행됩니다."
    )

    snapshot = graph.get_state(cfg)
    drafts: list[dict] = snapshot.values.get("evaluation_drafts", [])

    if not drafts:
        st.warning("평가 초안이 없습니다. 파이프라인을 다시 실행해 주세요.")
        if st.button("↺ 처음부터"):
            st.session_state.app_stage = "idle"
            st.rerun()
        return

    st.caption(f"총 **{len(drafts)}명** 평가 초안 | 항목을 클릭하여 직접 수정 가능")
    st.divider()

    edited_drafts: list[dict] = []

    for draft in drafts:
        sid   = draft["student_id"]
        name  = draft["name"]
        items = draft.get("feedback_items", {})

        with st.expander(f"**{name}** ({sid})", expanded=False):
            col_summary, col_eval = st.columns([1, 1], gap="medium")

            with col_summary:
                st.markdown("**📄 프로젝트 요약**")
                new_summary = st.text_area(
                    label="요약",
                    value=draft.get("summary", ""),
                    height=280,
                    key=f"_summary_{sid}",
                    label_visibility="collapsed",
                )

            with col_eval:
                st.markdown("**📊 루브릭 항목별 피드백**")
                new_items: dict = {}
                for item, feedback in items.items():
                    new_items[item] = st.text_area(
                        label=item,
                        value=feedback,
                        height=80,
                        key=f"_fb_{sid}_{item}",
                    )
                st.markdown("**💬 종합 의견**")
                new_overall = st.text_area(
                    label="종합",
                    value=draft.get("overall_feedback", ""),
                    height=120,
                    key=f"_overall_{sid}",
                    label_visibility="collapsed",
                )

            edited_drafts.append({
                **draft,
                "summary":          new_summary,
                "feedback_items":   new_items,
                "overall_feedback": new_overall,
            })

    st.divider()
    col_approve, col_revise = st.columns(2, gap="medium")
    approve_clicked = col_approve.button(
        "✅ 승인 및 저장", type="primary", use_container_width=True,
    )
    revise_clicked = col_revise.button(
        "✏️ 평가 재생성 요청", use_container_width=True,
        help="LLM이 평가 초안을 다시 작성합니다. GitHub 크롤링은 재실행되지 않습니다.",
    )

    if approve_clicked or revise_clicked:
        graph.update_state(
            cfg,
            {
                "evaluation_drafts": edited_drafts,
                "review_status":     "approved" if approve_clicked else "needs_revision",
            },
        )
        if approve_clicked:
            st.session_state.app_stage = "exporting"
        else:
            st.session_state.project_state = None   # resume from checkpoint
            st.session_state.app_stage     = "running"
        st.rerun()


# ─── Stage: exporting ────────────────────────────────────────────────────────

def render_exporting() -> None:
    """Resume graph after HITL approval: human_review → export_evaluation → END."""
    graph = _get_graph()
    cfg   = _thread_config()

    with st.status("📄 리포트를 저장하고 있습니다...", expanded=True) as status:
        try:
            result = _invoke_with_tracking(graph, None, cfg)
            status.update(label="저장 완료!", state="complete")
            st.session_state.project_state = result
            st.session_state.app_stage     = "done"
        except Exception as exc:
            status.update(label="오류 발생", state="error")
            st.session_state.error_message = str(exc)
            st.session_state.app_stage     = "idle"
    st.rerun()


# ─── Stage: done ─────────────────────────────────────────────────────────────

def render_done() -> None:
    """Show final evaluation reports with per-student download buttons."""
    graph = _get_graph()
    cfg   = _thread_config()

    st.header("Stage 5: 완료")
    st.success("✅ 프로젝트 평가가 완료되었습니다!")

    final_state = graph.get_state(cfg)
    output_dir  = final_state.values.get("output_dir", "")
    drafts: list[dict] = final_state.values.get("evaluation_drafts", [])

    if output_dir:
        st.info(f"저장 경로: `{output_dir}`")

    # Combined report download
    combined_path = Path(output_dir) / "_combined.md" if output_dir else None
    if combined_path and combined_path.exists():
        st.download_button(
            label="⬇ 전체 평가 통합본 다운로드",
            data=combined_path.read_bytes(),
            file_name="_combined_evaluation.md",
            mime="text/markdown",
            use_container_width=True,
        )

    st.divider()
    st.subheader(f"학생별 평가 결과 ({len(drafts)}명)")

    for draft in drafts:
        sid  = draft["student_id"]
        name = draft["name"]

        with st.expander(f"**{name}** ({sid})", expanded=False):
            col_content, col_dl = st.columns([6, 1])

            with col_content:
                st.markdown(f"**📄 프로젝트 요약**\n\n{draft.get('summary', '')}")
                st.divider()
                st.markdown("**📊 루브릭 항목별 피드백**")
                for item, fb in draft.get("feedback_items", {}).items():
                    st.markdown(f"**{item}**\n\n{fb}")
                st.divider()
                st.markdown(f"**💬 종합 의견**\n\n{draft.get('overall_feedback', '')}")

            with col_dl:
                report_path = (
                    Path(output_dir) / f"{sid}_{name.replace(' ', '_')}.md"
                    if output_dir else None
                )
                if report_path and report_path.exists():
                    st.download_button(
                        label="⬇",
                        data=report_path.read_bytes(),
                        file_name=report_path.name,
                        mime="text/markdown",
                        key=f"_dl_{sid}",
                        help=f"{name} 개별 리포트 다운로드",
                    )

    st.divider()
    if st.button("🔄 새 평가 시작", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="프로젝트 평가 에이전트",
        page_icon="📊",
        layout="wide",
    )
    _init_session_state()
    render_sidebar()

    st.title("📊 프로젝트 평가 에이전트")

    stage = st.session_state.app_stage
    if   stage == "idle":           render_idle()
    elif stage == "running":        render_running()
    elif stage == "waiting_review": render_waiting_review()
    elif stage == "exporting":      render_exporting()
    elif stage == "done":           render_done()


if __name__ == "__main__":
    main()
