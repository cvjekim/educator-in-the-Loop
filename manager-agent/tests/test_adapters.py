"""
Tests for sub-agent adapters (stub mode).

AGENT_STUB_MODE=true (default) — adapters return mock data without invoking
actual sub-agents.
"""

import os
import pytest

# Ensure stub mode for tests
os.environ.setdefault("AGENT_STUB_MODE", "true")

import src.adapters.lecture_adapter as lecture_adapter
import src.adapters.practice_adapter as practice_adapter
import src.adapters.exam_adapter as exam_adapter
import src.adapters.project_adapter as project_adapter


_PAYLOAD = {
    "task_type": "lecture",
    "week": 3,
    "subject": "machine-learning",
    "context": "SVM과 커널 트릭",
    "syllabus": "테스트 강의 계획서",
    "rubric_guidelines": "",
}


class TestLectureAdapter:
    def test_returns_success(self):
        result = lecture_adapter.run(_PAYLOAD)
        assert result["success"] is True

    def test_output_not_empty(self):
        result = lecture_adapter.run(_PAYLOAD)
        assert result["output"]


class TestPracticeAdapter:
    def test_returns_success(self):
        result = practice_adapter.run(_PAYLOAD)
        assert result["success"] is True

    def test_output_not_empty(self):
        result = practice_adapter.run(_PAYLOAD)
        assert result["output"]


class TestExamAdapter:
    def test_returns_success(self):
        result = exam_adapter.run(_PAYLOAD)
        assert result["success"] is True

    def test_output_not_empty(self):
        result = exam_adapter.run(_PAYLOAD)
        assert result["output"]


class TestProjectAdapter:
    def test_returns_success(self):
        result = project_adapter.run(_PAYLOAD)
        assert result["success"] is True

    def test_output_not_empty(self):
        result = project_adapter.run(_PAYLOAD)
        assert result["output"]


class TestBaseStub:
    def test_stub_mode_flag(self):
        from src.adapters.base import STUB_MODE
        assert STUB_MODE is True

    def test_stub_result_structure(self):
        from src.adapters.base import stub_result
        r = stub_result("lecture", 1, "AI")
        assert "success" in r
        assert "output" in r
        assert "note" in r
