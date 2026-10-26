"""
Integration test: full pipeline from guide_content → format_output.

Key design decisions:
  - Patch `_get_llm` per node module (not `ChatOpenAI` class) so the
    module-level `_llm` cache never interferes.
  - `reset_llm_globals` fixture (autouse) ensures `_llm = None` before
    every test — belt-and-suspenders.
  - Stage 2 resume uses the correct LangGraph pattern:
      graph.update_state(config, updates)
      graph.invoke(None, config)

Tested without a live OpenAI key.
"""

from __future__ import annotations

import importlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

# ── Stub content ──────────────────────────────────────────────────────────────

_STUB_INTRO = (
    "## 최신 트렌드 소개\n\n"
    "- LangGraph 멀티에이전트 협업 프레임워크의 등장\n"
    "- 합성 벤치마크 예시"
)
_STUB_MAIN_JOINED = (
    "## 머신러닝 기본 개념\n"
    "## 지도학습과 비지도학습\n"
    "## 성능 평가 지표"
)
_STUB_BULLETS = (
    "- 데이터에서 패턴을 학습하는 알고리즘 집합\n"
    "- 분류·회귀·군집화 세 가지 대표 유형\n"
    "- 교재 기반 핵심 내용 정리"
)
_STUB_FORMATTED = (
    "## 기본 개념\n\n"
    "- 데이터에서 패턴을 학습하는 알고리즘 집합\n\n"
    "## 주요 유형\n\n"
    "- 분류·회귀·군집화 세 가지 대표 유형"
)
_STUB_REVISED_JSON = (
    '{"intro_slide": "## 트렌드\\n- 항목A", '
    '"main_slides": ["## 슬라이드1", "## 슬라이드2"]}'
)

_LLM_NODE_PATHS = [
    "src.graph.nodes.draft_content",
    "src.graph.nodes.human_review",
    "src.graph.nodes.analysis_content",
    "src.graph.nodes.format_output",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_llm(response: str) -> MagicMock:
    """Return a mock that mimics `_get_llm()` returning an LLM instance."""
    mock_llm = MagicMock()
    msg = MagicMock()
    msg.content = response
    mock_llm.invoke.return_value = msg
    return mock_llm


def _make_draft_mock_llm() -> MagicMock:
    """
    draft_content makes two invoke calls (intro, then possibly main).
    Return _STUB_INTRO for the first call, _STUB_MAIN_JOINED for the second.
    """
    mock_llm = MagicMock()

    def side_effect(messages):
        # Detect intro vs main call from system message content
        sys_content = messages[0].content if messages else ""
        if "인트로" in sys_content or "트렌드" in sys_content:
            msg = MagicMock()
            msg.content = _STUB_INTRO
            return msg
        msg = MagicMock()
        msg.content = _STUB_MAIN_JOINED
        return msg

    mock_llm.invoke.side_effect = side_effect
    return mock_llm


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def synthetic_course(tmp_path, monkeypatch):
    """Use synthetic files; mock PDF extraction, keep config/graph logic real."""
    monkeypatch.chdir(tmp_path)
    subject = tmp_path / "subjects/sample-course"
    subject.mkdir(parents=True)
    (subject / "guideline.pdf").touch()
    notes = subject / "notes"
    notes.mkdir()
    (notes / "sample.pdf").touch()
    (subject / "configuration.md").write_text(
        "- sylabus.pdf : synthetic-syllabus.pdf\n"
        "- /previous-lecture-notes\n"
        f"  - folder path : {notes}\n"
        "  - week 1 : sample.pdf\n"
        "  - week 5 : sample.pdf\n",
        encoding="utf-8",
    )
    trend_dir = tmp_path / "data/trends"
    trend_dir.mkdir(parents=True)
    (trend_dir / "0001_AI_20260101_synthetic.md").write_text(
        "- Number: 0001\n- Date: 20260101\n- Topic: Synthetic teaching example\n"
        "- Category: AI\n- Summary: A synthetic trend for regression tests.\n",
        encoding="utf-8",
    )
    guide = importlib.import_module("src.graph.nodes.guide_content")
    loader = importlib.import_module("src.context.loader")
    monkeypatch.setattr(guide, "_read_pdf", lambda path: "1주차: 합성 개요\n5주차: 합성 머신러닝")
    monkeypatch.setattr(loader, "_extract_pdf", lambda path: "머신러닝 성능 평가 지도학습 합성 교재. " * 40)


@pytest.fixture(autouse=True)
def reset_llm_globals():
    """
    Reset the module-level _llm singletons before (and after) every test.
    Without this, the first real or mocked instance leaks into later tests.
    """
    for path in _LLM_NODE_PATHS:
        mod = importlib.import_module(path)
        mod._llm = None
    yield
    for path in _LLM_NODE_PATHS:
        mod = importlib.import_module(path)
        mod._llm = None


@pytest.fixture()
def initial_state() -> dict:
    return {
        "subject": "sample-course",
        "week": 5,
        "topic": "머신러닝과 성능 평가",
        "guidelines": "",   # blank → guide_content auto-fills from guideline.pdf
        "current_stage": "",
        "overall_progress": 0,
        "status_message": "",
        "review_status": "pending",
        "raw_context": "",
        "draft_outline": None,
        "final_output": None,
    }


@pytest.fixture()
def thread_config() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPipelineIntegration:

    # ── 1. Graph compiles ─────────────────────────────────────────────────────

    def test_graph_compiles(self):
        """Graph should build without errors and expose all expected nodes."""
        from src.graph.pipeline import build_graph
        g = build_graph()
        for expected in (
            "guide_content", "load_context", "draft_content",
            "human_review", "analysis_content", "format_output",
        ):
            assert expected in g.nodes, f"Node '{expected}' missing from graph"

    # ── 2. Stage 1: runs to interrupt ─────────────────────────────────────────

    def test_stage1_runs_and_pauses(self, initial_state, thread_config):
        """
        Stage 1 should run guide_content → load_context → draft_content
        and pause BEFORE human_review.  State must have a valid draft_outline.
        """
        from src.graph.pipeline import build_graph

        with (
            patch("src.graph.nodes.draft_content._get_llm",
                  return_value=_make_draft_mock_llm()),
            patch("src.graph.nodes.analysis_content._get_llm",
                  return_value=_make_mock_llm(_STUB_BULLETS)),
            patch("src.graph.nodes.format_output._get_llm",
                  return_value=_make_mock_llm(_STUB_FORMATTED)),
        ):
            graph = build_graph()
            result = graph.invoke(initial_state, thread_config)

        # Pipeline should stop at draft_content (just before human_review)
        assert result["current_stage"] == "draft_content"
        assert result["overall_progress"] == 50

        # guidelines must be auto-extracted from guideline.pdf
        assert result["guidelines"] != "", "guidelines should be auto-filled"

        # draft_outline must be fully populated
        outline = result["draft_outline"]
        assert outline is not None
        assert outline["intro_slide"] != ""
        assert isinstance(outline["main_slides"], list)
        assert len(outline["main_slides"]) > 0, (
            f"main_slides is empty; got: {outline['main_slides']}"
        )

    # ── 3. Stage 2: resume after HITL ─────────────────────────────────────────

    def test_stage2_resume_completes(self, initial_state, thread_config):
        """
        After Stage 1 pauses, update state with professor edits then resume
        with invoke(None).  Pipeline should reach format_output.
        """
        from app import DraftOutline
        from src.graph.nodes.human_review import FEEDBACK_MARKER
        from src.graph.pipeline import build_graph

        with (
            patch("src.graph.nodes.draft_content._get_llm",
                  return_value=_make_draft_mock_llm()),
            patch("src.graph.nodes.human_review._get_llm",
                  return_value=_make_mock_llm(_STUB_REVISED_JSON)),
            patch("src.graph.nodes.analysis_content._get_llm",
                  return_value=_make_mock_llm(_STUB_BULLETS)),
            patch("src.graph.nodes.format_output._get_llm",
                  return_value=_make_mock_llm(_STUB_FORMATTED)),
        ):
            graph = build_graph()

            # ── Stage 1: run to interrupt ──
            graph.invoke(initial_state, thread_config)

            # ── Stage 2: professor edits and approves ──
            edited_outline = DraftOutline(
                intro_slide=_STUB_INTRO,
                main_slides=["## 머신러닝 기본 개념", "## 성능 평가 지표"],
            )
            graph.update_state(
                thread_config,
                {
                    "review_status": "approved",
                    "draft_outline": edited_outline,
                    "guidelines": FEEDBACK_MARKER + "임상 사례 위주로 작성",
                },
            )
            result = graph.invoke(None, thread_config)

        assert result["current_stage"] == "format_output"
        assert result["overall_progress"] == 100
        assert result["review_status"] == "approved"
        final = result.get("final_output", "")
        assert final, "final_output should be non-empty"
        assert "주차" in final, "document title must appear in final_output"

    # ── 4. No-feedback path ───────────────────────────────────────────────────

    def test_no_feedback_outline_passthrough(self, initial_state, thread_config):
        """
        When the professor provides only direct edits (no FEEDBACK_MARKER),
        human_review should NOT call the LLM and the outline passes through.
        """
        from app import DraftOutline
        from src.graph.pipeline import build_graph

        hr_mock = _make_mock_llm(_STUB_REVISED_JSON)

        with (
            patch("src.graph.nodes.draft_content._get_llm",
                  return_value=_make_draft_mock_llm()),
            patch("src.graph.nodes.human_review._get_llm", return_value=hr_mock),
            patch("src.graph.nodes.analysis_content._get_llm",
                  return_value=_make_mock_llm(_STUB_BULLETS)),
            patch("src.graph.nodes.format_output._get_llm",
                  return_value=_make_mock_llm(_STUB_FORMATTED)),
        ):
            graph = build_graph()
            graph.invoke(initial_state, thread_config)

            edited = DraftOutline(
                intro_slide="## 트렌드\n- 항목A",
                main_slides=["## 슬라이드1", "## 슬라이드2"],
            )
            # No FEEDBACK_MARKER → human_review skips LLM
            graph.update_state(
                thread_config,
                {"review_status": "approved", "draft_outline": edited},
            )
            result = graph.invoke(None, thread_config)

        # human_review LLM should not have been called
        hr_mock.invoke.assert_not_called()
        assert result["current_stage"] == "format_output"
        assert result["overall_progress"] == 100

    # ── 5. Isolated unit tests (no LLM) ──────────────────────────────────────

    def test_trend_files_parseable(self):
        """data/trends/*.md must match naming convention and have required fields."""
        from pathlib import Path
        from src.trends.archive import _FILENAME_RE, _parse_trend_file

        trend_dir = Path("data/trends")
        md_files = [f for f in trend_dir.glob("*.md") if f.name != ".gitkeep"]
        assert md_files, "No trend files found in data/trends/"

        for f in md_files:
            assert _FILENAME_RE.match(f.name), (
                f"{f.name} does not match naming convention"
            )
            data = _parse_trend_file(f)
            assert data.get("topic"), f"{f.name}: missing Topic field"
            assert data.get("category"), f"{f.name}: missing Category field"
            assert data.get("date"), f"{f.name}: missing Date field"

    def test_subject_config_loads(self):
        """sample-course configuration.md must parse to a non-empty dict."""
        from src.utils.subject_config import load_config

        cfg = load_config("sample-course")
        assert cfg["syllabus"], "syllabus path should be non-empty"
        assert cfg["previous_note_paths"], "previous_note_paths should be non-empty"

    def test_guide_content_autofills_guidelines(self):
        """guide_content with blank guidelines extracts from guideline.pdf."""
        from src.graph.nodes.guide_content import guide_content

        state = {
            "subject": "sample-course", "week": 1,
            "topic": "합성 과목 개요", "guidelines": "",
            "current_stage": "", "overall_progress": 0,
            "status_message": "", "review_status": "pending",
            "raw_context": "", "draft_outline": None, "final_output": None,
        }
        result = guide_content(state)
        assert result["guidelines"], "guidelines should be auto-extracted"
        assert "강의계획서" in result["guidelines"]
        assert "합성 개요" in result["guidelines"]
        assert "합성 머신러닝" not in result["guidelines"]
        assert result["current_stage"] == "guide_content"
        assert result["overall_progress"] == 15

    def test_format_output_parses_draft(self):
        """_parse_sections must split the intermediate draft on --- correctly."""
        from src.graph.nodes.format_output import _parse_sections

        draft = (
            "## 인트로 슬라이드 (트렌드)\n\n- 트렌드A\n\n"
            "---\n\n"
            "## 슬라이드1\n\n- 불릿1\n- 불릿2\n\n"
            "---\n\n"
            "## 슬라이드2\n\n- 불릿A"
        )
        sections = _parse_sections(draft)
        assert len(sections) == 3
        assert "인트로" in sections[0][0]
        assert "슬라이드1" in sections[1][0]
        assert "불릿1" in sections[1][1]

    def test_human_review_feedback_extraction(self):
        """FEEDBACK_MARKER is correctly extracted from guidelines string."""
        from src.graph.nodes.human_review import FEEDBACK_MARKER, _extract_feedback

        g = "기존 지침" + FEEDBACK_MARKER + "슬라이드 3 확장. 트렌드 A 제거."
        assert _extract_feedback(g) == "슬라이드 3 확장. 트렌드 A 제거."
        assert _extract_feedback("no marker here") == ""
