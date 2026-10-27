"""
Notebook I/O utilities.
Wraps nbformat for .ipynb load / cell splitting / reassembly / save.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Tuple

import nbformat

from src.state_types import NotebookCell


def load_notebook(path: str) -> nbformat.NotebookNode:
    """Load a .ipynb file and return the parsed notebook object."""
    with open(path, "r", encoding="utf-8") as f:
        return nbformat.read(f, as_version=4)


def split_cells(notebook: nbformat.NotebookNode) -> Tuple[List[NotebookCell], List[NotebookCell]]:
    """
    Split notebook cells into code cells and markdown cells.

    Returns:
        (code_cells, markdown_cells) — both lists preserve original cell index.
    """
    code_cells: List[NotebookCell] = []
    markdown_cells: List[NotebookCell] = []

    for idx, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            code_cells.append({
                "index": idx,
                "cell_type": "code",
                "source": cell.source,
                "outputs": list(cell.get("outputs", [])),
            })
        elif cell.cell_type == "markdown":
            markdown_cells.append({
                "index": idx,
                "cell_type": "markdown",
                "source": cell.source,
                "outputs": [],
            })

    return code_cells, markdown_cells


def assemble_and_save(
    source_nb: nbformat.NotebookNode,
    revised_code_cells: List[NotebookCell],
    formatted_markdown_cells: List[NotebookCell],
) -> str:
    """
    Merge revised code cells and formatted markdown cells back into the
    original notebook cell order. Saves to a temp file and returns its path.
    The caller is responsible for copying to a permanent location.
    """
    revised_map = {c["index"]: c for c in revised_code_cells}
    markdown_map = {c["index"]: c for c in formatted_markdown_cells}

    new_cells = []
    for idx, cell in enumerate(source_nb.cells):
        if idx in revised_map:
            new_cell = nbformat.v4.new_code_cell(source=revised_map[idx]["source"])
        elif idx in markdown_map:
            new_cell = nbformat.v4.new_markdown_cell(source=markdown_map[idx]["source"])
        else:
            new_cell = cell
        new_cells.append(new_cell)

    new_nb = nbformat.v4.new_notebook(cells=new_cells)
    new_nb.metadata = source_nb.metadata

    tmp = tempfile.NamedTemporaryFile(suffix=".ipynb", delete=False, mode="w", encoding="utf-8")
    nbformat.write(new_nb, tmp)
    tmp.close()

    return tmp.name
