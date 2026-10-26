"""
Tests for notebook I/O utilities (src/notebook/loader.py).
"""

import json
import tempfile
from pathlib import Path

import pytest
import nbformat

from src.notebook.loader import load_notebook, split_cells, assemble_and_save


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_notebook(tmp_path: Path) -> Path:
    nb = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell("# 소개\n실습 목적을 설명합니다."),
        nbformat.v4.new_code_cell("import pandas as pd\ndf = pd.DataFrame()"),
        nbformat.v4.new_markdown_cell("## 데이터 로드"),
        nbformat.v4.new_code_cell("df = pd.read_csv('data.csv')"),
    ])
    path = tmp_path / "sample.ipynb"
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    return path


# ---------------------------------------------------------------------------
# load_notebook
# ---------------------------------------------------------------------------

def test_load_notebook_returns_notebooknode(sample_notebook):
    nb = load_notebook(str(sample_notebook))
    assert isinstance(nb, nbformat.NotebookNode)
    assert len(nb.cells) == 4


# ---------------------------------------------------------------------------
# split_cells
# ---------------------------------------------------------------------------

def test_split_cells_counts(sample_notebook):
    nb = load_notebook(str(sample_notebook))
    code_cells, markdown_cells = split_cells(nb)
    assert len(code_cells) == 2
    assert len(markdown_cells) == 2


def test_split_cells_preserves_index(sample_notebook):
    nb = load_notebook(str(sample_notebook))
    code_cells, markdown_cells = split_cells(nb)
    # Markdown cells are at index 0 and 2
    assert {c["index"] for c in markdown_cells} == {0, 2}
    # Code cells are at index 1 and 3
    assert {c["index"] for c in code_cells} == {1, 3}


def test_split_cells_source_content(sample_notebook):
    nb = load_notebook(str(sample_notebook))
    code_cells, _ = split_cells(nb)
    assert "import pandas" in code_cells[0]["source"]


# ---------------------------------------------------------------------------
# assemble_and_save
# ---------------------------------------------------------------------------

def test_assemble_preserves_cell_count(sample_notebook):
    nb = load_notebook(str(sample_notebook))
    code_cells, markdown_cells = split_cells(nb)

    # Simulate revision: uppercase source
    revised = [{**c, "source": c["source"].upper()} for c in code_cells]
    formatted = [{**c, "source": c["source"] + " (formatted)"} for c in markdown_cells]

    output_path = assemble_and_save(nb, revised, formatted)
    result_nb = load_notebook(output_path)
    assert len(result_nb.cells) == 4


def test_assemble_applies_revisions(sample_notebook):
    nb = load_notebook(str(sample_notebook))
    code_cells, markdown_cells = split_cells(nb)

    revised = [{**c, "source": "# revised"} for c in code_cells]
    output_path = assemble_and_save(nb, revised, markdown_cells)

    result_nb = load_notebook(output_path)
    code_sources = [c.source for c in result_nb.cells if c.cell_type == "code"]
    assert all(s == "# revised" for s in code_sources)
