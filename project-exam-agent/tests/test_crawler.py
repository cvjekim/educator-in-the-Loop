"""
Tests for GitHub crawler utilities (src/github/crawler.py).
Uses monkeypatching to avoid real HTTP calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.github.crawler as crawler_module
from src.github.crawler import crawl_repo


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mock_tree(paths: list[str]) -> list[dict]:
    return [{"path": p, "type": "blob", "size": 100} for p in paths]


def _make_entry(github_id="student1", repo_name="my-project") -> dict:
    return {
        "student_id": "student001",
        "name": "합성학생",
        "github_id": github_id,
        "repo_name": repo_name,
    }


# ─── get_repo_tree ────────────────────────────────────────────────────────────

class TestGetRepoTree:
    def test_returns_blobs_only(self, monkeypatch):
        fake = {"tree": [
            {"path": "README.md", "type": "blob", "size": 500},
            {"path": "src",       "type": "tree", "size": 0},
            {"path": "main.py",   "type": "blob", "size": 200},
        ]}
        monkeypatch.setattr(crawler_module, "_get", lambda url: fake)
        result = crawler_module.get_repo_tree("u", "r")
        assert all(item["type"] == "blob" for item in result)
        assert len(result) == 2

    def test_returns_empty_on_api_failure(self, monkeypatch):
        monkeypatch.setattr(crawler_module, "_get", lambda url: None)
        assert crawler_module.get_repo_tree("u", "r") == []


# ─── crawl_repo ───────────────────────────────────────────────────────────────

class TestCrawlRepo:
    def _patch(self, monkeypatch, tree, file_contents: dict):
        monkeypatch.setattr(crawler_module, "get_repo_tree", lambda gid, repo: tree)
        monkeypatch.setattr(
            crawler_module, "get_file_content",
            lambda gid, repo, path: file_contents.get(path, "")
        )

    def test_readme_is_collected(self, monkeypatch):
        self._patch(monkeypatch,
            tree=_mock_tree(["README.md", "main.py"]),
            file_contents={"README.md": "# Project", "main.py": "x=1"},
        )
        result = crawl_repo(_make_entry())
        assert "Project" in result["readme"]

    def test_source_files_collected(self, monkeypatch):
        self._patch(monkeypatch,
            tree=_mock_tree(["README.md", "main.py", "utils.py"]),
            file_contents={"README.md": "# R", "main.py": "import os", "utils.py": "def f(): pass"},
        )
        result = crawl_repo(_make_entry())
        assert len(result["files"]) == 2

    def test_has_required_outputs_true(self, monkeypatch):
        self._patch(monkeypatch,
            tree=_mock_tree(["README.md", "main.py"]),
            file_contents={"README.md": "# R", "main.py": "x=1"},
        )
        assert crawl_repo(_make_entry())["has_required_outputs"] is True

    def test_has_required_outputs_false_when_no_readme(self, monkeypatch):
        self._patch(monkeypatch,
            tree=_mock_tree(["main.py"]),
            file_contents={"main.py": "x=1"},
        )
        assert crawl_repo(_make_entry())["has_required_outputs"] is False

    def test_empty_on_api_failure(self, monkeypatch):
        monkeypatch.setattr(crawler_module, "get_repo_tree", lambda gid, repo: [])
        result = crawl_repo(_make_entry())
        assert result["readme"] == ""
        assert result["files"] == []
        assert result["has_required_outputs"] is False

    def test_unsupported_extensions_skipped(self, monkeypatch):
        self._patch(monkeypatch,
            tree=_mock_tree(["README.md", "image.png", "model.pkl"]),
            file_contents={"README.md": "# R", "image.png": "bin", "model.pkl": "bin"},
        )
        result = crawl_repo(_make_entry())
        paths = [f["path"] for f in result["files"]]
        assert "image.png" not in paths
        assert "model.pkl" not in paths

    def test_max_files_limit(self, monkeypatch):
        many = [f"file_{i}.py" for i in range(30)]
        self._patch(monkeypatch,
            tree=_mock_tree(["README.md"] + many),
            file_contents={p: f"# {p}" for p in ["README.md"] + many},
        )
        result = crawl_repo(_make_entry())
        assert len(result["files"]) <= crawler_module._MAX_FILES


# ─── export_evaluation helpers ───────────────────────────────────────────────

class TestExportEvaluation:
    def test_render_report_contains_name(self):
        from src.graph.nodes.export_evaluation import _render_report
        draft = {
            "student_id": "student001",
            "name": "합성학생",
            "summary": "프로젝트 요약",
            "feedback_items": {"기여도": "적극적 기여"},
            "overall_feedback": "전반적으로 우수",
        }
        report = _render_report(draft)
        assert "합성학생" in report
        assert "기여도" in report
        assert "전반적으로 우수" in report

    def test_render_report_no_scores(self):
        from src.graph.nodes.export_evaluation import _render_report
        draft = {
            "student_id": "student001",
            "name": "합성학생",
            "summary": "",
            "feedback_items": {},
            "overall_feedback": "좋습니다",
        }
        report = _render_report(draft)
        # Should not contain numeric score patterns like "10점", "90점"
        import re
        assert not re.search(r"\d+점", report)
