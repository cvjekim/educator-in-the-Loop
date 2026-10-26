"""
Tests for the trend archive module.

Focus: external behaviour (file creation, naming, limit enforcement, category validation).
No internal implementation details are tested.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from src.trends.archive import (
    enforce_limit,
    next_number,
    save_trend,
    VALID_CATEGORIES,
    MAX_FILES,
    TRENDS_DIR,
)


@pytest.fixture(autouse=True)
def tmp_trends_dir(tmp_path, monkeypatch):
    """Redirect TRENDS_DIR to a temporary directory for each test."""
    import src.trends.archive as archive_module
    monkeypatch.setattr(archive_module, "TRENDS_DIR", tmp_path)
    return tmp_path


class TestNextNumber:
    def test_returns_0001_when_empty(self, tmp_trends_dir):
        assert next_number() == "0001"

    def test_increments_from_last_file(self, tmp_trends_dir):
        (tmp_trends_dir / "0005_AI_20240101_some-topic.md").touch()
        assert next_number() == "0006"


class TestSaveTrend:
    def test_creates_file_with_correct_name_format(self, tmp_trends_dir):
        path = save_trend("AI", "20240101", "test-topic", "content")
        assert path.exists()
        assert path.name == "0001_AI_20240101_test-topic.md"

    def test_raises_on_invalid_category(self, tmp_trends_dir):
        with pytest.raises(ValueError, match="Invalid category"):
            save_trend("InvalidCat", "20240101", "topic", "content")

    def test_all_valid_categories_accepted(self, tmp_trends_dir):
        for i, category in enumerate(VALID_CATEGORIES):
            save_trend(category, f"2024010{i+1}", f"topic-{i}", "content")


class TestEnforceLimit:
    def test_deletes_oldest_when_over_limit(self, tmp_trends_dir):
        import src.trends.archive as archive_module
        monkeypatch_limit = 3

        # Create 4 files with ascending dates
        for i, date in enumerate(["20240101", "20240102", "20240103", "20240104"]):
            (tmp_trends_dir / f"{i+1:04d}_AI_{date}_topic.md").touch()

        with patch.object(archive_module, "MAX_FILES", monkeypatch_limit):
            enforce_limit()

        remaining = sorted(tmp_trends_dir.glob("*.md"))
        assert len(remaining) == monkeypatch_limit
        # Oldest (20240101) should be deleted
        assert not (tmp_trends_dir / "0001_AI_20240101_topic.md").exists()
