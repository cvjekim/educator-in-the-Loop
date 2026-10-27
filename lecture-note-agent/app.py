"""
Lecture Note Agent — Streamlit entry point.

Pipeline: guide_content → load_context → draft_content
          → [HITL] human_review
          → analysis_content → format_output
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional, TypedDict

import streamlit as st
from src.state_types import DraftOutline, LectureState

# ---------------------------------------------------------------------------
# LectureState — single source of truth for the LangGraph StateGraph
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Available subjects (from subjects/ directory)
# ---------------------------------------------------------------------------

SUBJECTS = sorted(p.name for p in (Path(__file__).parent / "subjects").glob("*") if p.is_dir()) or ["sample-course"]

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    defaults: dict = {
        "ui_stage": "input",        # "input" | "review" | "output"
        "graph_state": None,        # LectureState dict after graph run
        "graph": None,              # compiled LangGraph (holds MemorySaver)
        "thread_id": None,          # LangGraph checkpoint thread id
        "edited_outline": None,     # professor-edited outline from Stage 2
        "final_output": "",         # accumulated streaming output
        "usage": {                  # cumulative token/cost tracking
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

# gpt-4o-mini pricing (USD per 1M tokens, as of 2025)
_PRICE_INPUT_PER_1M = 0.150
_PRICE_OUTPUT_PER_1M = 0.600


def _invoke_with_tracking(graph, input_state, config: dict):
    """Wrap graph.invoke with UsageMetadataCallbackHandler and accumulate session usage."""
    from langchain_core.callbacks import UsageMetadataCallbackHandler

    cb = UsageMetadataCallbackHandler()
    tracked_config = {**config, "callbacks": [cb]}
    result = graph.invoke(input_state, tracked_config)

    for meta in cb.usage_metadata.values():
        st.session_state.usage["input_tokens"] += meta.get("input_tokens", 0)
        st.session_state.usage["output_tokens"] += meta.get("output_tokens", 0)

    return result


def _session_cost() -> float:
    u = st.session_state.usage
    return (
        u["input_tokens"] / 1_000_000 * _PRICE_INPUT_PER_1M
        + u["output_tokens"] / 1_000_000 * _PRICE_OUTPUT_PER_1M
    )


@st.cache_data(ttl=300)  # refresh from platform every 5 minutes
def _fetch_platform_usage(admin_key: str) -> dict:
    """
    Fetch month-to-date costs and this month's total tokens from OpenAI platform.
    Requires an Admin API key with usage.read scope.
    Create one at: https://platform.openai.com/settings/organization/admin-keys
    """
    import time
    import requests
    from datetime import date

    today = date.today()
    # Unix timestamp for the first day of this month (UTC midnight)
    start_ts = int(
        __import__("datetime").datetime(today.year, today.month, 1,
                                        tzinfo=__import__("datetime").timezone.utc
                                        ).timestamp()
    )

    headers = {"Authorization": f"Bearer {admin_key}"}
    result: dict = {
        "month_cost_usd": None,
        "input_tokens": None,
        "output_tokens": None,
        "error": None,
    }

    # ── Costs endpoint ────────────────────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.openai.com/v1/organization/costs",
            params={"start_time": start_ts, "bucket_width": "1d", "limit": 31},
            headers=headers,
            timeout=10,
        )
        if r.ok:
            total = 0.0
            for bucket in r.json().get("data", []):
                for res in bucket.get("results", []):
                    total += float(res.get("amount", {}).get("value", 0.0))
            result["month_cost_usd"] = total
        else:
            result["error"] = r.json().get("error", r.text)[:120]
    except Exception as e:
        result["error"] = str(e)[:120]

    # ── Token usage endpoint ──────────────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.openai.com/v1/organization/usage/completions",
            params={"start_time": start_ts, "bucket_width": "1d", "limit": 31},
            headers=headers,
            timeout=10,
        )
        if r.ok:
            in_tok = out_tok = 0
            for bucket in r.json().get("data", []):
                for res in bucket.get("results", []):
                    in_tok += res.get("input_tokens", 0)
                    out_tok += res.get("output_tokens", 0)
            result["input_tokens"] = in_tok
            result["output_tokens"] = out_tok
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _render_progress(state: LectureState) -> None:
    st.progress(state["overall_progress"], text=state["status_message"])


def _stage_badge(label: str, active: bool) -> str:
    return f"**→ {label}**" if active else label


# ---------------------------------------------------------------------------
# Stage 1 — Input form
# ---------------------------------------------------------------------------

def render_input_stage() -> None:
    st.header("Stage 1: Lecture Setup")
    st.caption("Fill in the details below. The agent will load your materials and draft an outline.")

    with st.form("lecture_input_form"):
        subject = st.selectbox("Subject", SUBJECTS)
        week = st.number_input("Week", min_value=1, max_value=16, value=1, step=1)
        topic = st.text_input("Topic", placeholder="e.g. Logistic Regression")
        guidelines = st.text_area(
            "Directional Guidelines (optional)",
            placeholder="e.g. Focus on clinical applications. Keep math minimal.",
            height=120,
        )
        submitted = st.form_submit_button("Generate Outline →", type="primary")

    if submitted:
        if not topic.strip():
            st.error("Topic is required.")
            return

        import uuid
        from src.graph.pipeline import build_graph

        initial_state: LectureState = {
            "subject": subject,
            "week": int(week),
            "topic": topic.strip(),
            "guidelines": guidelines.strip(),
            "current_stage": "guide_content",
            "overall_progress": 0,
            "status_message": "Starting pipeline…",
            "review_status": "pending",
            "raw_context": "",
            "draft_outline": None,
            "final_output": None,
        }

        thread_id = str(uuid.uuid4())
        graph = build_graph()
        config = {"configurable": {"thread_id": thread_id}}

        with st.status("Running Stage 1 — Outline & Trend Generation…", expanded=True) as status:
            st.write("📂 Loading lecture materials…")
            st.write("🌐 Collecting latest trends…")
            st.write("✏️ Drafting outline…")
            graph_state = _invoke_with_tracking(graph, initial_state, config)
            status.update(label="Outline ready for review.", state="complete")

        st.session_state.graph = graph
        st.session_state.thread_id = thread_id
        st.session_state.graph_state = graph_state
        st.session_state.ui_stage = "review"
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 2 — Human Review (HITL pause)
# ---------------------------------------------------------------------------

def render_review_stage() -> None:
    import pandas as pd
    from src.graph.nodes.human_review import FEEDBACK_MARKER

    state: LectureState = st.session_state.graph_state
    outline: Optional[DraftOutline] = state.get("draft_outline")

    st.header("Stage 2: 개요 검토 및 수정")
    st.caption(
        "슬라이드 제목을 직접 수정하거나, 하단에 피드백을 입력한 후 승인하세요. "
        "직접 수정과 피드백을 동시에 사용할 수 있습니다."
    )
    _render_progress(state)

    # --- Main slides: st.data_editor — one row per slide title ---
    st.subheader("메인 슬라이드 목차")
    st.caption("제목을 클릭하여 직접 수정하거나 행을 추가/삭제할 수 있습니다.")

    main_slides: List[str] = outline["main_slides"] if outline else []
    df_main = pd.DataFrame({"슬라이드 제목": pd.array(main_slides, dtype="string")})
    edited_df = st.data_editor(
        df_main,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="main_slides_editor",
        column_config={
            "슬라이드 제목": st.column_config.TextColumn(
                "슬라이드 제목",
                help="제목을 클릭하여 수정하세요.",
                width="large",
            )
        },
    )

    st.divider()

    # --- Intro slide: text_area ---
    st.subheader("인트로 슬라이드 (트렌드)")
    st.caption("최신 트렌드 기반 인트로 초안입니다. 직접 수정할 수 있습니다.")
    intro_text: str = outline["intro_slide"] if outline else ""
    edited_intro = st.text_area(
        "인트로 슬라이드",
        value=intro_text,
        height=220,
        label_visibility="collapsed",
    )

    st.divider()

    # --- Prompt-format feedback ---
    st.subheader("추가 피드백 (선택사항)")
    st.caption(
        "수정 지시를 자유롭게 입력하세요. "
        "직접 수정한 내용과 함께 AI가 반영합니다."
    )
    feedback = st.text_input(
        "피드백",
        placeholder="예: 3번 슬라이드 더 상세히. 트렌드 A 삭제. 전반적으로 임상 사례 위주로.",
        label_visibility="collapsed",
    )

    st.divider()
    col_approve, col_restart = st.columns([1, 4])
    with col_approve:
        approved = st.button("승인 및 생성 →", type="primary")
    with col_restart:
        restarted = st.button("↺ 처음부터")

    if approved:
        # Collect direct edits from data_editor
        edited_main_slides = [
            s.strip()
            for s in edited_df["슬라이드 제목"].dropna().tolist()
            if str(s).strip()
        ]

        edited_outline = DraftOutline(
            intro_slide=edited_intro,
            main_slides=edited_main_slides,
        )

        # Append feedback block so human_review node can detect and apply it
        updated_guidelines = state.get("guidelines", "")
        if feedback.strip():
            updated_guidelines = updated_guidelines + FEEDBACK_MARKER + feedback.strip()

        st.session_state.edited_outline = edited_outline

        graph = st.session_state.graph
        config = {"configurable": {"thread_id": st.session_state.thread_id}}
        graph.update_state(
            config,
            {
                "review_status": "approved",
                "draft_outline": edited_outline,
                "guidelines": updated_guidelines,
            },
        )

        with st.status("Running Stage 2 — Full Content Generation…", expanded=True) as status:
            st.write("🔍 Analysing approved outline…")
            st.write("📝 Writing slide content in Korean…")
            result = _invoke_with_tracking(graph, None, config)
            status.update(label="Generation complete.", state="complete")

        st.session_state.graph_state = result
        st.session_state.final_output = result.get("final_output", "")
        st.session_state.ui_stage = "output"
        st.rerun()

    if restarted:
        for key in ("ui_stage", "graph_state", "graph", "thread_id", "edited_outline", "final_output", "usage"):
            st.session_state.pop(key, None)
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 3 — Full output (streaming)
# ---------------------------------------------------------------------------

def render_output_stage() -> None:
    state: LectureState = st.session_state.graph_state

    st.header("Stage 3: Generated Lecture Notes")
    st.caption("Review the final Markdown output. Copy or download when ready.")

    _render_progress(state)

    output_placeholder = st.empty()

    if not st.session_state.final_output:
        st.session_state.final_output = state.get("final_output", "<!-- 출력 없음 -->")

    output_placeholder.markdown(st.session_state.final_output)

    st.divider()
    col_download, col_restart = st.columns([1, 4])
    with col_download:
        st.download_button(
            "⬇ Download Markdown",
            data=st.session_state.final_output,
            file_name=f"week{state['week']}_{state['topic'].replace(' ', '_')}.md",
            mime="text/markdown",
        )
    with col_restart:
        if st.button("↺ New Lecture"):
            for key in ("ui_stage", "graph_state", "thread_id", "edited_outline", "final_output"):
                st.session_state.pop(key, None)
            st.rerun()


# ---------------------------------------------------------------------------
# Sidebar — pipeline status
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.title("Lecture Note Agent")
        st.divider()

        ui_stage = st.session_state.get("ui_stage", "input")
        st.markdown(_stage_badge("1. Input & Outline", ui_stage == "input"))
        st.markdown(_stage_badge("2. Human Review", ui_stage == "review"))
        st.markdown(_stage_badge("3. Full Generation", ui_stage == "output"))

        st.divider()
        state: Optional[LectureState] = st.session_state.get("graph_state")
        if state:
            st.caption(f"**Subject**: {state['subject']}")
            st.caption(f"**Week**: {state['week']}  |  **Topic**: {state['topic']}")
            st.caption(f"**Node**: `{state['current_stage']}`")
            st.progress(state["overall_progress"])
            st.caption(state["status_message"])

        # ── OpenAI Usage ──────────────────────────────────────────────────
        st.divider()
        st.caption("**OpenAI Usage**")

        import os
        from dotenv import load_dotenv
        load_dotenv()

        # Session stats (locally tracked)
        u = st.session_state.get("usage", {"input_tokens": 0, "output_tokens": 0})
        sess_in = u["input_tokens"]
        sess_out = u["output_tokens"]
        sess_total = sess_in + sess_out
        sess_cost = _session_cost()

        admin_key = os.getenv("OPENAI_ADMIN_KEY", "").strip()
        if admin_key:
            platform = _fetch_platform_usage(admin_key)
            if platform["error"] and platform["month_cost_usd"] is None:
                st.caption(f"⚠️ Platform: {platform['error']}")
            else:
                m_cost = platform["month_cost_usd"] or 0.0
                m_in   = platform["input_tokens"]
                m_out  = platform["output_tokens"]
                m_tok  = (m_in or 0) + (m_out or 0)

                rest_cost = m_cost - sess_cost  # platform total minus this session

                # Total (platform month-to-date)
                st.caption(f"Total (this month): **${m_cost:.4f}**")
                if m_tok:
                    st.caption(f"↳ {m_tok:,} tokens (in {m_in:,} / out {m_out:,})")

                st.caption(f"This session: **${sess_cost:.4f}**")
                st.caption(f"↳ {sess_total:,} tokens (in {sess_in:,} / out {sess_out:,})")

                st.caption(f"Before session: **${rest_cost:.4f}**")

            col_refresh, _ = st.columns([1, 2])
            with col_refresh:
                if st.button("↺", help="Refresh platform data", key="refresh_usage"):
                    _fetch_platform_usage.clear()
                    st.rerun()
        else:
            # No admin key — show session only + setup hint
            st.caption(f"This session: **${sess_cost:.4f}**")
            st.caption(f"↳ {sess_total:,} tokens (in {sess_in:,} / out {sess_out:,})")
            st.caption(
                "ℹ️ Add `OPENAI_ADMIN_KEY` to `.env` to see\n"
                "platform totals. Create one at\n"
                "[platform.openai.com/settings/organization/admin-keys]"
                "(https://platform.openai.com/settings/organization/admin-keys) "
                "with `usage.read` scope."
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Lecture Note Agent",
        page_icon="📖",
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
