"""
Manager Agent — Streamlit entry point.

Pipeline:
    parse_course_plan → [interrupt_before] human_review
    → plan_dispatch → invoke_sub_agent → reflect_quality (loop)
    → collect_result → [loop: plan_dispatch | END]

Demonstrates:
    Loop       : remaining_tasks queue drives plan_dispatch → collect_result cycle
    Reflection : invoke_sub_agent → reflect_quality → retry if poor quality
    HITL       : professor approves parsed task list before dispatching
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from src.graph.state import ManagerState, TaskSpec  # noqa: F401 (re-exported)


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_session() -> None:
    defaults = {
        "graph": None,
        "thread_id": None,
        "stage": "idle",            # idle | parsing | waiting_review | dispatching | done
        "manager_state": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Manager Agent", layout="wide")
    _init_session()

    st.title("Manager Agent")
    st.caption("강의 계획서 기반 하위 에이전트 오케스트레이터")

    # --- Sidebar: input form ---
    with st.sidebar:
        st.header("입력")
        syllabus = st.text_area(
            "강의 계획서",
            placeholder="학기 전체 강의 계획서를 붙여넣으세요...",
            height=200,
        )
        rubric_guidelines = st.text_area(
            "프로젝트 평가 루브릭 가이드라인",
            placeholder="프로젝트 평가 기준을 입력하세요...",
            height=100,
        )
        max_reflections = st.number_input(
            "품질 재시도 최대 횟수", min_value=1, max_value=5, value=2
        )
        run_btn = st.button(
            "계획 분석 시작",
            type="primary",
            disabled=not syllabus.strip(),
        )

    # --- Main area ---
    stage = st.session_state["stage"]

    if stage == "idle":
        st.info("강의 계획서를 입력하고 '계획 분석 시작'을 클릭하세요.")

    if run_btn and syllabus.strip():
        import uuid
        from langgraph.checkpoint.memory import MemorySaver
        from src.graph.pipeline import build_graph

        checkpointer = MemorySaver()
        graph = build_graph(checkpointer)
        thread_id = str(uuid.uuid4())

        st.session_state["graph"] = graph
        st.session_state["thread_id"] = thread_id
        st.session_state["stage"] = "parsing"

        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "syllabus": syllabus,
            "rubric_guidelines": rubric_guidelines,
            "current_stage": "",
            "review_status": "pending",
            "feedback": "",
            "task_queue": [],
            "current_task": None,
            "remaining_tasks": [],
            "current_result": None,
            "reflection_count": 0,
            "max_reflections": max_reflections,
            "quality_flag": "ok",
            "quality_notes": "",
            "results": [],
        }

        with st.spinner("강의 계획서를 분석하는 중..."):
            for _ in graph.stream(initial_state, config):
                pass  # runs until interrupt_before=["human_review"]

        snapshot = graph.get_state(config)
        st.session_state["manager_state"] = snapshot.values
        st.session_state["stage"] = "waiting_review"
        st.rerun()

    # --- HITL: task plan review ---
    if stage == "waiting_review":
        state: ManagerState = st.session_state["manager_state"]
        st.subheader("작업 계획 검토")
        st.caption("분석된 작업 목록을 확인하고 승인하세요.")

        task_queue = state.get("task_queue", [])
        if task_queue:
            import pandas as pd
            df = pd.DataFrame(task_queue)
            edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("승인 — 에이전트 실행 시작", type="primary"):
                    graph = st.session_state["graph"]
                    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}
                    updated_tasks = edited_df.to_dict(orient="records")
                    graph.update_state(config, {
                        "review_status": "approved",
                        "task_queue": updated_tasks,
                        "remaining_tasks": updated_tasks,
                    })
                    st.session_state["stage"] = "dispatching"
                    st.rerun()
            with col2:
                feedback = st.text_input("피드백 (재분석 요청 시)")
                if st.button("재분석 요청"):
                    graph = st.session_state["graph"]
                    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}
                    graph.update_state(config, {
                        "review_status": "needs_revision",
                        "feedback": feedback,
                    })
                    with st.spinner("재분석 중..."):
                        for _ in graph.stream(None, config):
                            pass
                    snapshot = graph.get_state(config)
                    st.session_state["manager_state"] = snapshot.values
                    st.rerun()
        else:
            st.warning("분석된 작업이 없습니다. 강의 계획서를 확인하세요.")

    # --- Dispatching: run sub-agents ---
    if stage == "dispatching":
        graph = st.session_state["graph"]
        config = {"configurable": {"thread_id": st.session_state["thread_id"]}}

        with st.spinner("하위 에이전트 실행 중..."):
            for event in graph.stream(None, config):
                node_name = list(event.keys())[0] if event else ""
                st.write(f"⚙️ `{node_name}` 실행 중...")

        snapshot = graph.get_state(config)
        st.session_state["manager_state"] = snapshot.values
        st.session_state["stage"] = "done"
        st.rerun()

    # --- Done: show results ---
    if stage == "done":
        state: ManagerState = st.session_state["manager_state"]
        st.success("모든 작업이 완료되었습니다.")
        results = state.get("results", [])
        for i, r in enumerate(results):
            with st.expander(f"작업 {i+1}: [{r.get('task_type', '?')}] 주차 {r.get('week', '?')} — {r.get('subject', '')}"):
                st.write(r.get("output", ""))
                if r.get("quality_notes"):
                    st.caption(f"품질 검토: {r['quality_notes']}")


if __name__ == "__main__":
    main()
