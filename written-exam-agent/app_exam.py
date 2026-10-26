"""
Deprecated entry point. Use: streamlit run app.py

This file is kept for backward compatibility only.
"""
import os as _os

with open(_os.path.join(_os.path.dirname(__file__), "app.py"), encoding="utf-8") as _f:
    exec(compile(_f.read(), "app.py", "exec"), globals())  # noqa: S102

# ─── State Definition ────────────────────────────────────────────────────────

class QuestionParam(TypedDict):
    """A single question-type configuration."""
    question_type: str   # "single_choice" | "short_answer" | "open_answer"
    count: int


class ExamState(TypedDict):
    """Full state carried through the LangGraph pipeline."""
    subject_name: str
    parameters: list[QuestionParam]   # question types and counts per type
    questions: list[dict]             # generated question objects
    rubrics: list[dict]               # grading rubric per question
    final_output: Optional[dict]      # formatted document content
    review_status: str                # "pending" | "approved" | "needs_revision"
    feedback: str                     # professor's revision notes (empty if approved)


# Node functions are imported from nodes.py (see top of file).

# ─── Conditional Routing ─────────────────────────────────────────────────────

def route_after_review(state: ExamState) -> str:
    if state.get("review_status") == "approved":
        return "format_exam"
    return "generate_questions"


# ─── Graph Assembly ───────────────────────────────────────────────────────────

checkpointer = MemorySaver()


def build_graph():
    workflow = StateGraph(ExamState)
    workflow.add_node("generate_questions", generate_questions)
    workflow.add_node("draft_rubric", draft_rubric)
    workflow.add_node("human_review", human_review)
    workflow.add_node("format_exam", format_exam)
    workflow.set_entry_point("generate_questions")
    workflow.add_edge("generate_questions", "draft_rubric")
    workflow.add_edge("draft_rubric", "human_review")
    workflow.add_conditional_edges(
        "human_review",
        route_after_review,
        {"format_exam": "format_exam", "generate_questions": "generate_questions"},
    )
    workflow.add_edge("format_exam", END)
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )


graph = build_graph()


# ─── Helpers ─────────────────────────────────────────────────────────────────

_TYPE_LABEL = {
    "single_choice": "객관식",
    "short_answer":  "단답형",
    "open_answer":   "서술형",
}


def get_available_subjects() -> list[str]:
    subjects_dir = os.path.join(os.path.dirname(__file__), "subjects")
    if not os.path.isdir(subjects_dir):
        return []
    return sorted(
        d for d in os.listdir(subjects_dir)
        if os.path.isdir(os.path.join(subjects_dir, d))
    )


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _clear_review_state() -> None:
    """Delete all session-state keys written during the waiting_review stage."""
    for key in list(st.session_state.keys()):
        if key.startswith("_review_"):
            del st.session_state[key]


def _empty_criteria_df() -> pd.DataFrame:
    """Return an empty DataFrame with the correct columns for the criteria editor."""
    return pd.DataFrame(
        {"points": pd.Series(dtype="int64"), "description": pd.Series(dtype="str")}
    )


# ─── Streamlit Page Config ────────────────────────────────────────────────────

st.set_page_config(
    page_title="시험 문제 생성 에이전트",
    page_icon="📝",
    layout="wide",
)

# ── Session-state initialisation ─────────────────────────────────────────────
#
# exam_state:  initial ExamState dict on first run; None afterwards so that
#              the running stage calls graph.invoke(None, cfg) to *resume*
#              from the LangGraph checkpoint rather than starting over.
#
if "app_stage"   not in st.session_state: st.session_state.app_stage   = "idle"
if "thread_id"   not in st.session_state: st.session_state.thread_id   = str(uuid.uuid4())
if "exam_state"  not in st.session_state: st.session_state.exam_state  = None

# ── Sidebar — step progress tracker ──────────────────────────────────────────

STAGE_STEPS = [
    ("idle",           "1. 과목 및 파라미터 입력"),
    ("running",        "2. 문제 및 루브릭 생성 중"),
    ("waiting_review", "3. 검토 및 승인"),
    ("formatting",     "4. 문서 포매팅 중"),
    ("done",           "5. 완료"),
]

with st.sidebar:
    st.title("📝 시험 문제 생성")
    st.divider()

    stage_keys  = [s[0] for s in STAGE_STEPS]
    current_idx = stage_keys.index(st.session_state.app_stage) \
                  if st.session_state.app_stage in stage_keys else 0

    for i, (_, label) in enumerate(STAGE_STEPS):
        if   i < current_idx: st.success(f"✅ {label}")
        elif i == current_idx: st.info(f"▶ {label}")
        else:                  st.markdown(f"○ {label}")

    st.divider()
    if st.button("처음으로 초기화", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("📝 시험 문제 생성 에이전트")


# ════════════════════════════════════════════════════════════════════════════
# STAGE: idle — Input form
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.app_stage == "idle":

    # Show any error from a previous run (e.g. API failure)
    if "error_message" in st.session_state:
        st.error(st.session_state.pop("error_message"))

    st.subheader("과목 및 문제 유형 설정")
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
        submitted = st.form_submit_button("🚀 문제 생성 시작", use_container_width=True, type="primary")

    if submitted:
        if n_single + n_short + n_open == 0:
            st.error("최소 한 가지 유형에서 1문제 이상 설정해 주세요.")
        else:
            params: list[QuestionParam] = []
            if n_single > 0: params.append({"question_type": "single_choice", "count": int(n_single)})
            if n_short  > 0: params.append({"question_type": "short_answer",  "count": int(n_short)})
            if n_open   > 0: params.append({"question_type": "open_answer",   "count": int(n_open)})

            st.session_state.thread_id  = str(uuid.uuid4())
            st.session_state.exam_state = {
                "subject_name": subject_name,
                "parameters":   params,
                "questions":    [],
                "rubrics":      [],
                "final_output": None,
                "review_status": "pending",
                "feedback":     "",
            }
            st.session_state.app_stage = "running"
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE: running — Invoke / resume the graph up to the HITL interrupt
#
# Key invariant:
#   exam_state is NOT None  →  first invocation, pass as input to start fresh
#   exam_state is     None  →  revision run, pass None to resume from checkpoint
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.app_stage == "running":
    with st.status("🤖 문제 및 루브릭을 생성하고 있습니다...", expanded=True) as status:
        try:
            st.write("강의 자료를 분석하는 중...")
            cfg         = thread_config(st.session_state.thread_id)
            input_state = st.session_state.exam_state   # None → resume

            graph.invoke(input_state, config=cfg)
            # graph pauses before human_review; state is persisted in checkpointer

            st.write("문제 생성 완료. 교수님의 검토를 기다립니다.")
            status.update(label="생성 완료 — 검토 대기 중", state="complete")

            # Mark as None so any future revision run resumes instead of restarts
            st.session_state.exam_state = None
            st.session_state.app_stage  = "waiting_review"

        except Exception as exc:
            status.update(label=f"오류 발생", state="error")
            st.session_state.error_message = str(exc)
            st.session_state.app_stage     = "idle"

    st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE: waiting_review — HITL edit + approve / revise
#
# Session-state contract (all keys prefixed with "_review_"):
#   _review_loaded             bool   — set after the one-time checkpoint load
#   _review_questions          list   — original question list from checkpoint
#   _review_rubrics            list   — original rubric list from checkpoint
#   _review_q_content_{i}      str    — widget key for question text area
#   _review_rubric_criteria_{i} –     — widget key for criteria data editor
#   _review_rubric_keywords_{i} str   — widget key for keywords text area
#   _review_feedback           str    — widget key for feedback text area
#
# All keys are deleted atomically in _clear_review_state() when leaving this
# stage, so the next review cycle (after a revision) always starts fresh.
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.app_stage == "waiting_review":
    st.subheader("📋 생성된 문제 및 루브릭 검토")

    # ── One-time load from LangGraph checkpoint ───────────────────────────────
    if "_review_loaded" not in st.session_state:
        cfg      = thread_config(st.session_state.thread_id)
        snapshot = graph.get_state(cfg)
        qs = snapshot.values.get("questions", [])
        rs = snapshot.values.get("rubrics", [])

        st.session_state._review_questions = qs
        st.session_state._review_rubrics   = rs

        # Seed text-area widget keys with the LLM-generated content.
        # Streamlit respects these values on first render and tracks user
        # edits automatically via the key thereafter.
        for i, q in enumerate(qs):
            st.session_state[f"_review_q_content_{i}"] = q.get("content", "")
        for i, r in enumerate(rs):
            st.session_state[f"_review_rubric_keywords_{i}"] = "\n".join(
                r.get("keywords", [])
            )

        st.session_state._review_loaded = True

    questions: list[dict] = st.session_state._review_questions
    rubrics:   list[dict] = st.session_state._review_rubrics

    # ── Render editable cards (one per question) ──────────────────────────────
    st.caption(
        "각 문제와 루브릭을 직접 수정할 수 있습니다. "
        "완료 후 하단의 버튼으로 승인하거나 수정을 요청하세요."
    )

    # Collect data-editor return values in order (needed at submit time).
    edited_criteria_dfs: list[pd.DataFrame] = []

    if not questions:
        st.warning("생성된 문제가 없습니다. 설정을 확인 후 다시 시도하세요.")
    else:
        for i, q in enumerate(questions):
            r          = rubrics[i] if i < len(rubrics) else {}
            type_label = _TYPE_LABEL.get(q.get("question_type", ""), "기타")
            total_pts  = r.get("total_points", "?")

            with st.expander(
                f"문제 {q.get('number', i+1)} · {type_label} · {total_pts}점",
                expanded=True,
            ):
                col_q, col_r = st.columns([1, 1], gap="medium")

                # ── Left: question content text area ──────────────────────
                with col_q:
                    st.markdown("**✏️ 문제 내용**")
                    st.text_area(
                        label="문제 내용",
                        key=f"_review_q_content_{i}",
                        height=220,
                        label_visibility="collapsed",
                    )

                # ── Right: rubric criteria table + keywords ────────────────
                with col_r:
                    st.markdown("**📊 채점 기준**")
                    raw_criteria = r.get("criteria", [])
                    if raw_criteria:
                        criteria_df = pd.DataFrame(raw_criteria)
                        # Ensure points column is integer (not float)
                        if "points" in criteria_df.columns:
                            criteria_df["points"] = (
                                criteria_df["points"].fillna(0).astype(int)
                            )
                    else:
                        criteria_df = _empty_criteria_df()

                    edited_df = st.data_editor(
                        criteria_df,
                        key=f"_review_rubric_criteria_{i}",
                        column_config={
                            "points": st.column_config.NumberColumn(
                                "배점",
                                min_value=0,
                                step=1,
                                width="small",
                            ),
                            "description": st.column_config.TextColumn(
                                "채점 기준",
                                width="large",
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

    # ── Feedback text area ────────────────────────────────────────────────────
    st.markdown("##### 검토 의견")
    st.text_area(
        label="수정 요청 사항",
        key="_review_feedback",
        placeholder="수정이 필요한 내용을 구체적으로 입력해 주세요. (수정 요청 시 필수)",
        height=100,
        label_visibility="collapsed",
    )

    # ── Action buttons ────────────────────────────────────────────────────────
    col_approve, col_revise = st.columns(2, gap="medium")
    approve_clicked = col_approve.button(
        "✅ 승인 및 완료",
        use_container_width=True,
        type="primary",
        help="편집된 내용을 저장하고 최종 문서를 생성합니다.",
    )
    revise_clicked = col_revise.button(
        "✏️ 수정 요청",
        use_container_width=True,
        help="검토 의견을 바탕으로 문제를 다시 생성합니다.",
    )

    # ── Handle button actions ─────────────────────────────────────────────────
    if approve_clicked or revise_clicked:
        is_approved   = approve_clicked
        feedback_text = st.session_state.get("_review_feedback", "").strip()

        # Guard: revision requires feedback
        if not is_approved and not feedback_text:
            st.error("수정 요청 시 검토 의견을 반드시 입력해 주세요.")
            st.stop()

        # Collect all edited question content from session_state widget keys
        edited_questions: list[dict] = []
        for i, q in enumerate(questions):
            edited_q = dict(q)
            edited_q["content"] = st.session_state.get(
                f"_review_q_content_{i}", q.get("content", "")
            )
            edited_questions.append(edited_q)

        # Collect all edited rubrics from data-editor return values + keyword keys
        edited_rubrics: list[dict] = []
        for i, r in enumerate(rubrics):
            edited_r = dict(r)

            if i < len(edited_criteria_dfs):
                df = edited_criteria_dfs[i].copy()
                if "points" in df.columns:
                    df["points"] = df["points"].fillna(0).astype(int)
                edited_r["criteria"] = df.to_dict("records")

            raw_kw = st.session_state.get(f"_review_rubric_keywords_{i}", "")
            edited_r["keywords"] = [
                kw.strip() for kw in raw_kw.splitlines() if kw.strip()
            ]
            edited_rubrics.append(edited_r)

        # Push the professor's edits + decision into the LangGraph checkpoint.
        # The graph resumes from here in the next stage.
        cfg = thread_config(st.session_state.thread_id)
        graph.update_state(
            cfg,
            {
                "questions":     edited_questions,
                "rubrics":       edited_rubrics,
                "review_status": "approved" if is_approved else "needs_revision",
                "feedback":      "" if is_approved else feedback_text,
            },
        )

        # Clear all review-stage keys so the next cycle starts fresh
        _clear_review_state()

        st.session_state.app_stage = "formatting" if is_approved else "running"
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE: formatting — Resume graph (human_review → format_exam → END)
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.app_stage == "formatting":
    with st.status("📄 문서를 포매팅하고 있습니다...", expanded=True) as status:
        try:
            cfg    = thread_config(st.session_state.thread_id)
            result = graph.invoke(None, config=cfg)
            status.update(label="포매팅 완료!", state="complete")
            st.session_state.exam_state = result
            st.session_state.app_stage  = "done"
        except Exception as exc:
            status.update(label="오류 발생", state="error")
            st.session_state.error_message = str(exc)
            st.session_state.app_stage     = "idle"
    st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE: done — Show final documents
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.app_stage == "done":
    st.success("✅ 시험 문제 및 루브릭 생성이 완료되었습니다!")

    cfg          = thread_config(st.session_state.thread_id)
    final_state  = graph.get_state(cfg)
    final_output: Optional[dict] = final_state.values.get("final_output")
    subject_name_done: str = final_state.values.get("subject_name", "exam")

    if final_output:
        question_paper: str = final_output.get("question_paper", "")
        rubric_sheet:   str = final_output.get("rubric_sheet", "")
        combined: str = (
            "<!-- 문제지 -->\n\n"
            + question_paper
            + "\n\n---\n\n<!-- 채점 기준표 -->\n\n"
            + rubric_sheet
        )

        # ── Download buttons ─────────────────────────────────────────────────
        dl_col1, dl_col2, dl_col3 = st.columns(3)
        dl_col1.download_button(
            label="⬇️ 문제지 다운로드",
            data=question_paper,
            file_name=f"{subject_name_done}_question_paper.md",
            mime="text/markdown",
            use_container_width=True,
        )
        dl_col2.download_button(
            label="⬇️ 채점 기준표 다운로드",
            data=rubric_sheet,
            file_name=f"{subject_name_done}_rubric_sheet.md",
            mime="text/markdown",
            use_container_width=True,
        )
        dl_col3.download_button(
            label="⬇️ 통합본 다운로드",
            data=combined,
            file_name=f"{subject_name_done}_final_exam.md",
            mime="text/markdown",
            use_container_width=True,
        )

        # ── Tabbed preview ────────────────────────────────────────────────────
        tab_paper, tab_rubric = st.tabs(["📄 문제지 미리보기", "📋 채점 기준표 미리보기"])
        with tab_paper:
            st.markdown(question_paper)
        with tab_rubric:
            st.markdown(rubric_sheet)
    else:
        st.info("(최종 문서는 format_exam 노드 구현 후 여기에 표시됩니다)")

    if st.button("🔄 새 시험 만들기", use_container_width=True):
        st.session_state.app_stage  = "idle"
        st.session_state.thread_id  = None
        st.session_state.exam_state = None
        st.rerun()
