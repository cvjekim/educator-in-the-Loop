"""
tests/test_nodes.py
Unit tests for material-loading helpers, generate_questions, and draft_rubric.
Run with: pytest tests/test_nodes.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.materials.loader as loader
from src.materials.loader import load_materials, load_syllabus
from src.utils.parser import (
    build_params_description,
    format_questions_for_rubric,
    parse_questions_response,
    parse_rubrics_response,
)
from src.graph.nodes.generate_questions import generate_questions
from src.graph.nodes.draft_rubric import draft_rubric
from src.graph.nodes.format_exam import (
    format_exam,
    build_question_paper,
    build_rubric_sheet,
)

# ─── Constants ────────────────────────────────────────────────────────────────

MOCK_SUBJECT = "DeepLearning"


@pytest.fixture(autouse=True)
def synthetic_materials(tmp_path, monkeypatch):
    """Regression tests must not require publishing private course materials."""
    subject = tmp_path / "subjects" / MOCK_SUBJECT
    (subject / "materials").mkdir(parents=True)
    (subject / "syllabus.md").write_text("딥러닝과 로지스틱 회귀의 기초", encoding="utf-8")
    (subject / "materials" / "sample.md").write_text("시그모이드 Sigmoid 함수는 출력을 0과 1 사이로 제한합니다.", encoding="utf-8")
    monkeypatch.setattr(loader, "SUBJECTS_DIR", tmp_path / "subjects")

SAMPLE_QUESTIONS = [
    {
        "question_type": "single_choice",
        "number": 1,
        "content": (
            "1. 시그모이드 함수 $\\sigma(x) = \\frac{1}{1+e^{-x}}$ 의 출력 범위는?\n"
            "① $(-\\infty, +\\infty)$\n"
            "② $(0, 1)$\n"
            "③ $[-1, 1]$\n"
            "④ $(0, +\\infty)$\n"
            "⑤ $\\{0, 1\\}$"
        ),
        "model_answer": "② 시그모이드 함수는 모든 실수를 $(0, 1)$ 범위로 압축합니다.",
    },
    {
        "question_type": "short_answer",
        "number": 2,
        "content": "2. 로지스틱 회귀에서 경사 하강법의 보폭을 결정하는 하이퍼파라미터의 명칭은?",
        "model_answer": "학습률 (Learning Rate)",
    },
    {
        "question_type": "open_answer",
        "number": 3,
        "content": (
            "3. 로지스틱 회귀의 결정 경계(Decision Boundary)가 형성되는 원리를 설명하고, "
            "이진 분류에서 예측 확률 $\\hat{y}$를 클래스 레이블로 변환하는 기준을 "
            "수식과 함께 서술하시오."
        ),
        "model_answer": (
            "결정 경계는 $\\sigma(z) = 0.5$, 즉 $z = 0$인 초평면으로, "
            "양쪽에서 클래스가 나뉩니다. "
            "$\\hat{y} \\geq 0.5 \\Rightarrow$ 클래스 1, "
            "$\\hat{y} < 0.5 \\Rightarrow$ 클래스 0."
        ),
    },
]

SAMPLE_RUBRICS = [
    {
        "question_number": 1,
        "question_type": "single_choice",
        "total_points": 5,
        "criteria": [
            {"points": 5, "description": "정답(②) 선택"},
            {"points": 0, "description": "오답 또는 미응답"},
        ],
        "keywords": ["시그모이드", "$(0, 1)$"],
    },
    {
        "question_number": 2,
        "question_type": "short_answer",
        "total_points": 10,
        "criteria": [
            {"points": 10, "description": "학습률(Learning Rate) 정확히 작성"},
            {"points": 5, "description": "의미는 맞으나 용어가 부정확한 경우 (예: '스텝 크기')"},
            {"points": 0, "description": "오답 또는 미응답"},
        ],
        "keywords": ["학습률", "Learning Rate"],
    },
    {
        "question_number": 3,
        "question_type": "open_answer",
        "total_points": 20,
        "criteria": [
            {
                "points": 20,
                "description": (
                    "결정 경계 원리, 수식 $\\sigma(z)=0.5 \\Leftrightarrow z=0$, "
                    "예측 규칙 모두 정확히 서술"
                ),
            },
            {
                "points": 14,
                "description": "원리와 수식은 맞으나 예측 규칙($\\hat{y}$ 임계값)이 불완전",
            },
            {
                "points": 7,
                "description": "시그모이드 역할 이해하나 결정 경계 수식 $z=0$ 누락",
            },
            {"points": 0, "description": "오답 또는 미응답"},
        ],
        "keywords": ["결정 경계", "$z = 0$", "시그모이드", "$\\sigma(z) = 0.5$"],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
#  load_syllabus
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadSyllabus:
    def test_returns_non_empty_string_for_existing_subject(self):
        content = load_syllabus(MOCK_SUBJECT)
        assert isinstance(content, str)
        assert len(content) > 0

    def test_content_contains_expected_korean_text(self):
        content = load_syllabus(MOCK_SUBJECT)
        assert "로지스틱" in content or "딥러닝" in content

    def test_missing_subject_returns_empty_string(self):
        content = load_syllabus("__does_not_exist_xyz__")
        assert content == ""

    def test_missing_subject_does_not_raise(self):
        try:
            load_syllabus("__does_not_exist_xyz__")
        except Exception as exc:
            pytest.fail(f"load_syllabus raised unexpectedly: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
#  load_materials
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadMaterials:
    def test_returns_non_empty_string_for_mock_subject(self):
        content = load_materials(MOCK_SUBJECT)
        assert isinstance(content, str)
        assert len(content) > 0

    def test_includes_filename_header(self):
        content = load_materials(MOCK_SUBJECT)
        assert "[파일:" in content

    def test_parses_md_file_content(self):
        content = load_materials(MOCK_SUBJECT)
        assert "시그모이드" in content or "Sigmoid" in content

    def test_missing_subject_returns_empty_string(self):
        content = load_materials("__does_not_exist_xyz__")
        assert content == ""

    def test_missing_subject_does_not_raise(self):
        try:
            load_materials("__does_not_exist_xyz__")
        except Exception as exc:
            pytest.fail(f"load_materials raised unexpectedly: {exc}")

    def test_corrupt_pdf_returns_error_tag_not_exception(self, tmp_path, monkeypatch):
        """A corrupt PDF must not crash the pipeline — it returns an error tag."""
        mat_dir = tmp_path / "subjects" / "FakeSubject" / "materials"
        mat_dir.mkdir(parents=True)
        (mat_dir / "bad.pdf").write_bytes(b"this is not a real pdf")

        monkeypatch.setattr(loader, "SUBJECTS_DIR", tmp_path / "subjects")

        content = load_materials("FakeSubject")
        assert "PDF 파싱 오류" in content or content.strip() == ""

    def test_unsupported_file_extension_is_skipped(self, tmp_path, monkeypatch):
        """Files with unsupported extensions (.pptx, .docx) are silently ignored."""
        mat_dir = tmp_path / "subjects" / "FakeSubject" / "materials"
        mat_dir.mkdir(parents=True)
        (mat_dir / "slides.pptx").write_bytes(b"fake pptx")

        monkeypatch.setattr(loader, "SUBJECTS_DIR", tmp_path / "subjects")

        content = load_materials("FakeSubject")
        assert content == ""

    def test_txt_file_is_parsed(self, tmp_path, monkeypatch):
        mat_dir = tmp_path / "subjects" / "TxtSubject" / "materials"
        mat_dir.mkdir(parents=True)
        (mat_dir / "notes.txt").write_text("경사 하강법 노트", encoding="utf-8")

        monkeypatch.setattr(loader, "SUBJECTS_DIR", tmp_path / "subjects")

        content = load_materials("TxtSubject")
        assert "경사 하강법 노트" in content


# ══════════════════════════════════════════════════════════════════════════════
#  build_params_description
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildParamsDescription:
    def test_all_types_appear_in_output(self):
        params = [
            {"question_type": "single_choice", "count": 5},
            {"question_type": "short_answer", "count": 3},
            {"question_type": "open_answer", "count": 2},
        ]
        desc = build_params_description(params)
        assert "객관식" in desc
        assert "단답형" in desc
        assert "서술형" in desc

    def test_counts_appear_in_output(self):
        params = [
            {"question_type": "single_choice", "count": 7},
            {"question_type": "open_answer", "count": 4},
        ]
        desc = build_params_description(params)
        assert "7" in desc
        assert "4" in desc

    def test_unknown_type_uses_raw_key(self):
        params = [{"question_type": "essay", "count": 1}]
        desc = build_params_description(params)
        assert "essay" in desc

    def test_empty_params_returns_empty_string(self):
        assert build_params_description([]) == ""


# ══════════════════════════════════════════════════════════════════════════════
#  parse_questions_response
# ══════════════════════════════════════════════════════════════════════════════

class TestParseQuestionsResponse:
    def test_parses_bare_json_array(self):
        raw = json.dumps(SAMPLE_QUESTIONS)
        result = parse_questions_response(raw)
        assert result == SAMPLE_QUESTIONS

    def test_parses_json_fenced_with_json_tag(self):
        raw = f"```json\n{json.dumps(SAMPLE_QUESTIONS)}\n```"
        result = parse_questions_response(raw)
        assert result == SAMPLE_QUESTIONS

    def test_parses_json_fenced_without_tag(self):
        raw = f"```\n{json.dumps(SAMPLE_QUESTIONS)}\n```"
        result = parse_questions_response(raw)
        assert result == SAMPLE_QUESTIONS

    def test_parses_json_with_surrounding_prose(self):
        raw = f"아래는 출제된 문제입니다:\n{json.dumps(SAMPLE_QUESTIONS)}\n감사합니다."
        result = parse_questions_response(raw)
        assert isinstance(result, list)
        assert len(result) == len(SAMPLE_QUESTIONS)

    def test_raises_on_completely_invalid_input(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_questions_response("이것은 JSON이 전혀 아닙니다.")

    def test_result_has_required_keys(self):
        raw = json.dumps(SAMPLE_QUESTIONS)
        result = parse_questions_response(raw)
        for q in result:
            assert "question_type" in q
            assert "number" in q
            assert "content" in q
            assert "model_answer" in q


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_state(**overrides) -> dict:
    base = {
        "subject_name": MOCK_SUBJECT,
        "parameters": [{"question_type": "single_choice", "count": 1}],
        "questions": [],
        "rubrics": [],
        "final_output": None,
        "review_status": "pending",
        "feedback": "",
    }
    base.update(overrides)
    return base


def _mock_llm(data: list[dict], target: str):
    """Patch ChatOpenAI in the given module path with a canned JSON response."""
    mock_response = MagicMock()
    mock_response.content = json.dumps(data)
    mock_instance = MagicMock()
    mock_instance.invoke.return_value = mock_response
    return patch(f"{target}.ChatOpenAI", return_value=mock_instance), mock_instance


# ══════════════════════════════════════════════════════════════════════════════
#  generate_questions  (LLM mocked)
# ══════════════════════════════════════════════════════════════════════════════

_GEN_TARGET = "src.graph.nodes.generate_questions"


class TestGenerateQuestions:
    def test_returns_questions_list(self):
        ctx, _ = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            result = generate_questions(_make_state())
        assert "questions" in result
        assert isinstance(result["questions"], list)
        assert len(result["questions"]) == len(SAMPLE_QUESTIONS)

    def test_questions_have_required_keys(self):
        ctx, _ = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            result = generate_questions(_make_state())
        for q in result["questions"]:
            assert "question_type" in q
            assert "number" in q
            assert "content" in q
            assert "model_answer" in q

    def test_resets_rubrics_on_regeneration(self):
        stale_rubric = [{"content": "old rubric"}]
        state = _make_state(rubrics=stale_rubric, review_status="needs_revision")
        ctx, _ = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            result = generate_questions(state)
        assert result["rubrics"] == []

    def test_feedback_is_included_in_llm_call(self):
        feedback = "서술형 문제를 더 심화 수준으로 출제해주세요."
        state = _make_state(
            parameters=[{"question_type": "open_answer", "count": 1}],
            review_status="needs_revision",
            feedback=feedback,
        )
        ctx, mock_instance = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            generate_questions(state)
        messages = mock_instance.invoke.call_args[0][0]
        human_content = messages[1].content
        assert feedback in human_content

    def test_empty_feedback_omits_feedback_section(self):
        state = _make_state(feedback="")
        ctx, mock_instance = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            generate_questions(state)
        messages = mock_instance.invoke.call_args[0][0]
        human_content = messages[1].content
        assert "수정 요청" not in human_content

    def test_missing_syllabus_does_not_raise(self):
        state = _make_state(subject_name="__no_syllabus_subject__")
        ctx, _ = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            result = generate_questions(state)
        assert "questions" in result

    def test_missing_materials_does_not_raise(self):
        state = _make_state(subject_name="__no_materials_subject__")
        ctx, _ = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx:
            result = generate_questions(state)
        assert "questions" in result

    def test_uses_gpt4o_model(self):
        ctx, _ = _mock_llm(SAMPLE_QUESTIONS, _GEN_TARGET)
        with ctx as MockChatOpenAI:
            generate_questions(_make_state())
        init_kwargs = MockChatOpenAI.call_args.kwargs
        assert init_kwargs.get("model") == "gpt-4o"


# ══════════════════════════════════════════════════════════════════════════════
#  format_questions_for_rubric
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatQuestionsForRubric:
    def test_includes_question_numbers(self):
        result = format_questions_for_rubric(SAMPLE_QUESTIONS)
        assert "문제 1" in result
        assert "문제 2" in result
        assert "문제 3" in result

    def test_includes_korean_type_labels(self):
        result = format_questions_for_rubric(SAMPLE_QUESTIONS)
        assert "객관식" in result
        assert "단답형" in result
        assert "서술형" in result

    def test_includes_question_content(self):
        result = format_questions_for_rubric(SAMPLE_QUESTIONS)
        assert "시그모이드" in result
        assert "하이퍼파라미터" in result

    def test_includes_model_answers(self):
        result = format_questions_for_rubric(SAMPLE_QUESTIONS)
        assert "학습률" in result
        assert "결정 경계" in result

    def test_empty_list_returns_empty_string(self):
        assert format_questions_for_rubric([]) == ""

    def test_multiple_questions_are_separated(self):
        result = format_questions_for_rubric(SAMPLE_QUESTIONS)
        assert result.count("[문제") == len(SAMPLE_QUESTIONS)
        assert "\n\n" in result


# ══════════════════════════════════════════════════════════════════════════════
#  parse_rubrics_response  (alias smoke-tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestParseRubricsResponse:
    def test_parses_bare_json_array(self):
        raw = json.dumps(SAMPLE_RUBRICS)
        result = parse_rubrics_response(raw)
        assert result == SAMPLE_RUBRICS

    def test_parses_fenced_json(self):
        raw = f"```json\n{json.dumps(SAMPLE_RUBRICS)}\n```"
        result = parse_rubrics_response(raw)
        assert result == SAMPLE_RUBRICS


# ══════════════════════════════════════════════════════════════════════════════
#  draft_rubric  (LLM mocked)
# ══════════════════════════════════════════════════════════════════════════════

_RUB_TARGET = "src.graph.nodes.draft_rubric"


class TestDraftRubric:
    def test_returns_rubrics_list(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        assert "rubrics" in result
        assert isinstance(result["rubrics"], list)

    def test_rubric_count_matches_question_count(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        assert len(result["rubrics"]) == len(SAMPLE_RUBRICS)

    def test_rubrics_have_required_keys(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        for rubric in result["rubrics"]:
            assert "question_number" in rubric
            assert "question_type" in rubric
            assert "total_points" in rubric
            assert "criteria" in rubric
            assert "keywords" in rubric

    def test_criteria_are_in_descending_point_order(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        for rubric in result["rubrics"]:
            pts = [c["points"] for c in rubric["criteria"]]
            assert pts == sorted(pts, reverse=True), (
                f"문제 {rubric['question_number']} criteria 순서 오류: {pts}"
            )

    def test_last_criterion_is_zero_points(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        for rubric in result["rubrics"]:
            last = rubric["criteria"][-1]["points"]
            assert last == 0, (
                f"문제 {rubric['question_number']}의 마지막 기준이 0점이 아닙니다: {last}"
            )

    def test_single_choice_has_exactly_two_criteria(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        sc_rubrics = [r for r in result["rubrics"] if r["question_type"] == "single_choice"]
        assert sc_rubrics, "객관식 루브릭이 없습니다."
        for r in sc_rubrics:
            assert len(r["criteria"]) == 2, (
                f"객관식 루브릭은 2단계여야 합니다: {r['criteria']}"
            )

    def test_open_answer_has_at_least_three_criteria(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        oa_rubrics = [r for r in result["rubrics"] if r["question_type"] == "open_answer"]
        assert oa_rubrics, "서술형 루브릭이 없습니다."
        for r in oa_rubrics:
            assert len(r["criteria"]) >= 3, (
                f"서술형 루브릭은 3단계 이상이어야 합니다: {r['criteria']}"
            )

    def test_empty_questions_returns_empty_rubrics_without_llm_call(self):
        with patch(f"{_RUB_TARGET}.ChatOpenAI") as MockLLM:
            result = draft_rubric(_make_state(questions=[]))
        assert result == {"rubrics": []}
        MockLLM.assert_not_called()

    def test_uses_lower_temperature_for_consistency(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx as MockChatOpenAI:
            draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        init_kwargs = MockChatOpenAI.call_args.kwargs
        assert init_kwargs.get("temperature") == 0.3

    def test_uses_gpt4o_model(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx as MockChatOpenAI:
            draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        init_kwargs = MockChatOpenAI.call_args.kwargs
        assert init_kwargs.get("model") == "gpt-4o"

    def test_question_content_passed_to_llm(self):
        ctx, mock_instance = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        messages = mock_instance.invoke.call_args[0][0]
        human_content = messages[1].content
        assert "시그모이드" in human_content
        assert "하이퍼파라미터" in human_content

    def test_model_answers_passed_to_llm(self):
        ctx, mock_instance = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        messages = mock_instance.invoke.call_args[0][0]
        human_content = messages[1].content
        assert "학습률" in human_content
        assert "결정 경계" in human_content

    def test_keywords_are_non_empty_list(self):
        ctx, _ = _mock_llm(SAMPLE_RUBRICS, _RUB_TARGET)
        with ctx:
            result = draft_rubric(_make_state(questions=SAMPLE_QUESTIONS))
        for rubric in result["rubrics"]:
            assert isinstance(rubric["keywords"], list)
            assert len(rubric["keywords"]) > 0, (
                f"문제 {rubric['question_number']}의 keywords가 비어 있습니다."
            )


# ══════════════════════════════════════════════════════════════════════════════
#  build_question_paper
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildQuestionPaper:
    def test_returns_string(self):
        assert isinstance(build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS), str)

    def test_header_contains_subject_name(self):
        assert MOCK_SUBJECT in build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)

    def test_total_question_count_in_header(self):
        result = build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)
        assert f"{len(SAMPLE_QUESTIONS)}문제" in result

    def test_section_labels_present(self):
        result = build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)
        assert "객관식" in result
        assert "단답형" in result
        assert "서술형" in result

    def test_question_content_included(self):
        result = build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)
        for q in SAMPLE_QUESTIONS:
            first_line = q["content"].splitlines()[0]
            assert first_line in result

    def test_model_answers_not_included(self):
        result = build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)
        for q in SAMPLE_QUESTIONS:
            assert q["model_answer"] not in result

    def test_section_ordering(self):
        result = build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)
        pos_single = result.find("객관식")
        pos_short  = result.find("단답형")
        pos_open   = result.find("서술형")
        assert pos_single < pos_short < pos_open

    def test_empty_questions_returns_placeholder(self):
        result = build_question_paper(MOCK_SUBJECT, [])
        assert MOCK_SUBJECT in result
        assert "없습니다" in result

    def test_name_and_student_id_blanks_present(self):
        result = build_question_paper(MOCK_SUBJECT, SAMPLE_QUESTIONS)
        assert "이름" in result
        assert "학번" in result


# ══════════════════════════════════════════════════════════════════════════════
#  build_rubric_sheet
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildRubricSheet:
    def test_returns_string(self):
        assert isinstance(build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS), str)

    def test_header_contains_subject_name(self):
        assert MOCK_SUBJECT in build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS)

    def test_total_points_calculated(self):
        expected_total = sum(r["total_points"] for r in SAMPLE_RUBRICS)
        result = build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS)
        assert f"{expected_total}점" in result

    def test_rubric_section_label_present(self):
        assert "루브릭:" in build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS)

    def test_criteria_descriptions_included(self):
        result = build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS)
        for rubric in SAMPLE_RUBRICS:
            for criterion in rubric["criteria"]:
                assert criterion["description"] in result

    def test_keywords_line_included(self):
        result = build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS)
        assert "핵심 키워드" in result
        assert "시그모이드" in result

    def test_question_content_included(self):
        result = build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, SAMPLE_RUBRICS)
        for q in SAMPLE_QUESTIONS:
            first_line = q["content"].splitlines()[0]
            assert first_line in result

    def test_empty_questions_returns_placeholder(self):
        result = build_rubric_sheet(MOCK_SUBJECT, [], [])
        assert MOCK_SUBJECT in result
        assert "없습니다" in result

    def test_empty_rubrics_gracefully_handled(self):
        result = build_rubric_sheet(MOCK_SUBJECT, SAMPLE_QUESTIONS, [])
        assert isinstance(result, str)
        assert MOCK_SUBJECT in result


# ══════════════════════════════════════════════════════════════════════════════
#  format_exam  (Node 4)
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatExam:
    def _run(self, **overrides):
        return format_exam(_make_state(**overrides))

    def test_returns_final_output_key(self):
        assert "final_output" in self._run(questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)

    def test_final_output_has_question_paper(self):
        assert "question_paper" in self._run(questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)["final_output"]

    def test_final_output_has_rubric_sheet(self):
        assert "rubric_sheet" in self._run(questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)["final_output"]

    def test_question_paper_is_non_empty_string(self):
        qp = self._run(questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)["final_output"]["question_paper"]
        assert isinstance(qp, str) and len(qp) > 0

    def test_rubric_sheet_is_non_empty_string(self):
        rs = self._run(questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)["final_output"]["rubric_sheet"]
        assert isinstance(rs, str) and len(rs) > 0

    def test_subject_name_in_question_paper(self):
        result = self._run(subject_name=MOCK_SUBJECT, questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)
        assert MOCK_SUBJECT in result["final_output"]["question_paper"]

    def test_subject_name_in_rubric_sheet(self):
        result = self._run(subject_name=MOCK_SUBJECT, questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)
        assert MOCK_SUBJECT in result["final_output"]["rubric_sheet"]

    def test_empty_state_does_not_raise(self):
        result = format_exam({})
        assert "final_output" in result
        assert "question_paper" in result["final_output"]
        assert "rubric_sheet" in result["final_output"]

    def test_returns_only_final_output_key(self):
        result = self._run(questions=SAMPLE_QUESTIONS, rubrics=SAMPLE_RUBRICS)
        assert list(result.keys()) == ["final_output"]
