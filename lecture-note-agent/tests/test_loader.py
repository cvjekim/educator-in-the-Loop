"""
Tests for the context loader module.

Focus: correct file selection per subject config, non-empty extraction for valid files.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.context.loader import load_subject_context


class TestLoadSubjectContext:
    def test_returns_empty_string_for_missing_config(self):
        with patch("src.context.loader._read_subject_config", return_value={}):
            result = load_subject_context("unknown-subject", week=1)
        assert isinstance(result, str)

    def test_skips_nonexistent_paths(self, tmp_path):
        config = {"reference_paths": [str(tmp_path / "missing.pdf")]}
        with patch("src.context.loader._read_subject_config", return_value=config):
            result = load_subject_context("any-subject", week=1)
        assert result == ""

    def test_extracts_text_from_valid_pdf(self, tmp_path):
        fake_pdf = tmp_path / "ref.pdf"
        fake_pdf.touch()
        config = {"reference_paths": [str(fake_pdf)]}
        with (
            patch("src.context.loader._read_subject_config", return_value=config),
            patch("src.context.loader._extract_pdf", return_value="extracted text") as mock_pdf,
        ):
            result = load_subject_context("any-subject", week=1)
        mock_pdf.assert_called_once()
        assert "extracted text" in result
