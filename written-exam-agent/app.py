"""
Written Exam Agent — Streamlit entry point.

Pipeline: generate_questions → draft_rubric
          → [HITL] human_review
          → format_exam
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

import pandas as pd
import streamlit as st
from src.state_types import QuestionParam, ExamState
from dotenv import load_dotenv
from typing_extensions import TypedDict

load_dotenv()


# ─── State Definition ────────────────────────────────────────────────────────





# ─── Constants ───────────────────────────────────────────────────────────────

_TYPE_LABEL = {
    "single_choice": "객관식",
    "short_answer":  "단답형",
    "open_answer":   "서술형",
}

# gpt-4o pricing (USD per 1M tokens, as of 2025)
_PRICE_INPUT_PER_1M  = 2.50
_PRICE_OUTPUT_PER_1M = 10.00

STAGE_STEPS = [
    ("idle",           "1. 과목 및 파라미터 입력"),
    ("running",        "2. 문제 및 루브릭 생성 중"),
    ("waiting_review", "3. 검토 및 승인 (HITL)"),
    ("formatting",     "4. 문서 포매팅 중"),
    ("done",           "5. 완료"),
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_available_subjects() -> list[str]:
    subjects_dir = os.path.join(os.path.dirname(__file__), "subjects")
    if not os.path.isdir(subjects_dir):
        return []
    return sorted(
        d for d in os.listdir(subjects_dir)
        if os.path.isdir(os.path.join(subjects_dir, d))
    )


def _thread_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def _clear_review_state() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("_review_"):
            del st.session_state[key]


def _empty_criteria_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"points": pd.Series(dtype="int64"), "description": pd.Series(dtype="str")}
    )


# ─── Session state ────────────────────────────────────────────────────────────

def _init_session_state() -> None:
    defaults: dict = {
        "app_stage":   "idle",
        "thread_id":   str(uuid.uuid4()),
        "graph":       None,    # compiled LangGraph (holds MemorySaver)
        "exam_state":  None,
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


# ─── UI helpers ───────────────────────────────────────────────────────────────

def _stage_badge(label: str, active: bool) -> str:
    return f"**→ {label}**" if active else label


# ─── Sidebar ─────────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    with st.sidebar:
        st.title("📝 시험 문제 생성")
        st.divider()

        stage_keys  = [s[0] for s in STAGE_STEPS]
        current_idx = stage_keys.index(st.session_state.app_stage) \
                      if st.session_state.app_stage in stage_keys else 0

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
        st.caption("※ gpt-4o 기준 요율")

        st.divider()
        if st.button("↺ 처음으로 초기화", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


# ─── Stage: idle ─────────────────────────────────────────────────────────────

def render_idle() -> None:
    st.header("Stage 1: 과목 및 문제 유형 설정")
    st.caption("출제할 과목을 선택하고 문제 유형별 수량을 지정하세요.")

    if "error_message" in st.session_state:
        st.error(st.session_state.pop("error_message"))

    subjects = get_available_subjects()
    if not subjects:
        st.error("subjects/ 디렉토리에 등록된 과목이 없습니다.")
        st.stop()

    with st.form("exam_config_form"):
        subject_name = st.selectbox("과목 선택", subjects)
        st.markdown("#### 문제 유형별 출제 수")
        col1, col2, col3 = st.columns(3)
        n_single = col1.number_input("객관식 (5지선다)", min_value=0, max_value=20, value=5, step=1)
        n_short  = col2.number_input("단답형",           min_value=0, max_value=20, value=3, step=1)
        n_open   = col3.number_input("서술형",           min_value=0, max_value=10, value=2, step=1)
        submitted = st.form_submit_button(
            "🚀 문제 생성 시작", use_container_width=True, type="primary"
        )

    if submitted:
        if n_single + n_short + n_open == 0:
            st.error("최소 한 가지 유형에서 1문제 이상 설정해 주세요.")
            return

        params: list[QuestionParam] = []
        if n_single > 0: params.append({"question_type": "single_choice", "count": int(n_single)})
        if n_short  > 0: params.append({"question_type": "short_answer",  "count": int(n_short)})
        if n_open   > 0: params.append({"question_type": "open_answer",   "count": int(n_open)})

        # Fresh graph + thread for each new exam
        st.session_state.graph      = None  # force rebuild
        st.session_state.thread_id  = str(uuid.uuid4())
        st.session_state.exam_state = {
            "subject_name":  subject_name,
            "parameters":    params,
            "questions":     [],
            "rubrics":       [],
            "final_output":  None,
            "review_status": "pending",
            "feedback":      "",
        }
        st.session_state.app_stage = "running"
        st.rerun()


# ─── Stage: running ──────────────────────────────────────────────────────────

def render_running() -> None:
    """Invoke / resume the graph up to the HITL interrupt."""
    graph       = _get_graph()
    input_state = st.session_state.exam_state   # initial state or None (resume)
    cfg         = _thread_config()

    with st.status("🤖 문제 및 루브릭을 생성하고 있습니다...", expanded=True) as status:
        try:
            st.write("📚 강의 자료를 분석하는 중…")
            st.write("✏️ 문제 생성 중 (gpt-4o, temperature=0.7)…")
            st.write("📊 채점 루브릭 작성 중 (gpt-4o, temperature=0.3)…")
            _invoke_with_tracking(graph, input_state, cfg)
            st.write("✅ 생성 완료. 교수님의 검토를 기다립니다.")
            status.update(label="생성 완료 — 검토 대기 중", state="complete")

            st.session_state.exam_state = None   # consumed; resume via checkpointer
            st.session_state.app_stage  = "waiting_review"

        except Exception as exc:
            status.update(label="오류 발생", state="error")
            st.session_state.error_message = str(exc)
            st.session_state.app_stage     = "idle"

    st.rerun()


# ─── Stage: waiting_review ───────────────────────────────────────────────────

def render_waiting_review() -> None:
    """HITL: let the professor edit questions & rubrics, then approve or request revision."""
    graph = _get_graph()
    cfg   = _thread_config()

    st.header("Stage 3: 생성된 문제 및 루브릭 검토 (HITL)")
    st.caption(
        "각 문제와 루브릭을 직접 수정할 수 있습니다. "
        "완료 후 하단의 버튼으로 승인하거나 수정을 요청하세요."
    )

    # Load snapshot once per review session
    if "_review_loaded" not in st.session_state:
        snapshot = graph.get_state(cfg)
        qs = snapshot.values.get("questions", [])
        rs = snapshot.values.get("rubrics",   [])

        st.session_state._review_questions = qs
        st.session_state._review_rubrics   = rs
        for i, q in enumerate(qs):
            st.session_state[f"_review_q_content_{i}"] = q.get("content", "")
        for i, r in enumerate(rs):
            st.session_state[f"_review_rubric_keywords_{i}"] = "\n".join(r.get("keywords", []))
        st.session_state._review_loaded = True

    questions: list[dict] = st.session_state._review_questions
    rubrics:   list[dict] = st.session_state._review_rubrics

    edited_criteria_dfs: list[pd.DataFrame] = []

    if not questions:
        st.warning("생성된 문제가 없습니다. 설정을 확인 후 다시 시도하세요.")
    else:
        total_pts_sum = sum(r.get("total_points", 0) for r in rubrics)
        st.caption(f"총 {len(questions)}문제 | 총 배점: {total_pts_sum}점")
        st.divider()

        for i, q in enumerate(questions):
            r          = rubrics[i] if i < len(rubrics) else {}
            type_label = _TYPE_LABEL.get(q.get("question_type", ""), "기타")
            total_pts  = r.get("total_points", "?")

            with st.expander(
                f"문제 {q.get('number', i + 1)} · {type_label} · {total_pts}점",
                expanded=(i == 0),
            ):
                col_q, col_r = st.columns([1, 1], gap="medium")

                with col_q:
                    st.markdown("**✏️ 문제 내용**")
                    st.text_area(
                        label="문제 내용",
                        key=f"_review_q_content_{i}",
                        height=220,
                        label_visibility="collapsed",
                    )

                with col_r:
                    st.markdown("**📊 채점 기준**")
                    raw_criteria = r.get("criteria", [])
                    if raw_criteria:
                        criteria_df = pd.DataFrame(raw_criteria)
                        if "points" in criteria_df.columns:
                            criteria_df["points"] = criteria_df["points"].fillna(0).astype(int)
                    else:
                        criteria_df = _empty_criteria_df()

                    edited_df = st.data_editor(
                        criteria_df,
                        key=f"_review_rubric_criteria_{i}",
                        column_config={
                            "points": st.column_config.NumberColumn(
                                "배점", min_value=0, step=1, width="small",
                            ),
                            "description": st.column_config.TextColumn(
                                "채점 기준", width="large",
                            ),
                        },
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True,
                    )
                    edited_criteria_dfs.append(edited_df)

                    st.markdown("**🔑 필수 키워드** *(줄바꿈으로 구분)*")
                    st.text_area(
                        label="키워드",
                        key=f"_review_rubric_keywords_{i}",
                        height=90,
                        label_visibility="collapsed",
                    )

    st.divider()
    st.markdown("##### 검토 의견 (수정 요청 시 필수)")
    st.text_area(
        label="수정 요청 사항",
        key="_review_feedback",
        placeholder="수정이 필요한 내용을 구체적으로 입력해 주세요.",
        height=100,
        label_visibility="collapsed",
    )

    col_approve, col_revise = st.columns(2, gap="medium")
    approve_clicked = col_approve.button(
        "✅ 승인 및 완료", use_container_width=True, type="primary",
        help="편집된 내용을 저장하고 최종 문서를 생성합니다.",
    )
    revise_clicked = col_revise.button(
        "✏️ 수정 요청", use_container_width=True,
        help="검토 의견을 바탕으로 문제를 다시 생성합니다.",
    )

    if approve_clicked or revise_clicked:
        is_approved   = approve_clicked
        feedback_text = st.session_state.get("_review_feedback", "").strip()

        if not is_approved and not feedback_text:
            st.error("수정 요청 시 검토 의견을 반드시 입력해 주세요.")
            st.stop()

        # Collect inline edits
        edited_questions: list[dict] = []
        for i, q in enumerate(questions):
            eq = dict(q)
            eq["content"] = st.session_state.get(f"_review_q_content_{i}", q.get("content", ""))
            edited_questions.append(eq)

        edited_rubrics: list[dict] = []
        for i, r in enumerate(rubrics):
            er = dict(r)
            if i < len(edited_criteria_dfs):
                df = edited_criteria_dfs[i].copy()
                if "points" in df.columns:
                    df["points"] = df["points"].fillna(0).astype(int)
                er["criteria"] = df.to_dict("records")
            raw_kw = st.session_state.get(f"_review_rubric_keywords_{i}", "")
            er["keywords"] = [kw.strip() for kw in raw_kw.splitlines() if kw.strip()]
            edited_rubrics.append(er)

        graph.update_state(
            cfg,
            {
                "questions":     edited_questions,
                "rubrics":       edited_rubrics,
                "review_status": "approved" if is_approved else "needs_revision",
                "feedback":      "" if is_approved else feedback_text,
            },
        )

        _clear_review_state()
        if is_approved:
            st.session_state.app_stage = "formatting"
        else:
            # Resume from human_review → routes to generate_questions
            st.session_state.exam_state = None
            st.session_state.app_stage  = "running"
        st.rerun()


# ─── Stage: formatting ───────────────────────────────────────────────────────

def render_formatting() -> None:
    """Resume graph after HITL approval: human_review → format_exam → END."""
    graph = _get_graph()
    cfg   = _thread_config()

    with st.status("📄 문서를 포매팅하고 있습니다...", expanded=True) as status:
        try:
            result = _invoke_with_tracking(graph, None, cfg)
            status.update(label="포매팅 완료!", state="complete")
            st.session_state.exam_state = result
            st.session_state.app_stage  = "done"
        except Exception as exc:
            status.update(label="오류 발생", state="error")
            st.session_state.error_message = str(exc)
            st.session_state.app_stage     = "idle"
    st.rerun()


# ─── Stage: done ─────────────────────────────────────────────────────────────

def render_done() -> None:
    """Show final documents with download buttons."""
    graph = _get_graph()
    cfg   = _thread_config()

    st.header("Stage 5: 완료")
    st.success("✅ 시험 문제 및 루브릭 생성이 완료되었습니다!")

    final_state  = graph.get_state(cfg)
    final_output: Optional[dict] = final_state.values.get("final_output")
    subject_done: str            = final_state.values.get("subject_name", "exam")

    if final_output:
        question_paper: str = final_output.get("question_paper", "")
        rubric_sheet:   str = final_output.get("rubric_sheet",   "")
        combined: str = (
            "<!-- 문제지 -->\n\n"
            + question_paper
            + "\n\n---\n\n<!-- 채점 기준표 -->\n\n"
            + rubric_sheet
        )

        dl1, dl2, dl3 = st.columns(3)
        dl1.download_button(
            "⬇️ 문제지 다운로드",
            data=question_paper,
            file_name=f"{subject_done}_question_paper.md",
            mime="text/markdown",
            use_container_width=True,
        )
        dl2.download_button(
            "⬇️ 채점 기준표 다운로드",
            data=rubric_sheet,
            file_name=f"{subject_done}_rubric_sheet.md",
            mime="text/markdown",
            use_container_width=True,
        )
        dl3.download_button(
            "⬇️ 통합본 다운로드",
            data=combined,
            file_name=f"{subject_done}_final_exam.md",
            mime="text/markdown",
            use_container_width=True,
        )

        st.divider()
        tab_paper, tab_rubric = st.tabs(["📄 문제지 미리보기", "📋 채점 기준표 미리보기"])
        with tab_paper:
            st.markdown(question_paper)
        with tab_rubric:
            st.markdown(rubric_sheet)
    else:
        st.info("(최종 문서가 없습니다. 파이프라인을 다시 실행해 주세요.)")

    st.divider()
    if st.button("🔄 새 시험 만들기", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="시험 문제 생성 에이전트",
        page_icon="📝",
        layout="wide",
    )
    _init_session_state()
    render_sidebar()

    st.title("📝 시험 문제 생성 에이전트")

    stage = st.session_state.app_stage
    if   stage == "idle":           render_idle()
    elif stage == "running":        render_running()
    elif stage == "waiting_review": render_waiting_review()
    elif stage == "formatting":     render_formatting()
    elif stage == "done":           render_done()


if __name__ == "__main__":
    main()
