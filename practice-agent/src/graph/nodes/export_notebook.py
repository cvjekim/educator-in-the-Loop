"""
Node: export_notebook
Copies the approved temporary .ipynb to the subject's notebooks/ directory
using a timestamped filename. The original source file is never overwritten.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app import PracticeState


def export_notebook(state: PracticeState) -> dict:
    src = Path(state["output_path"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    subject_dir = Path("subjects") / state["subject"] / "notebooks"
    subject_dir.mkdir(parents=True, exist_ok=True)

    dest = subject_dir / f"{src.stem}_{timestamp}.ipynb"
    shutil.copy2(src, dest)

    return {
        "current_stage": "export_notebook",
        "overall_progress": 100,
        "status_message": f"저장 완료 → {dest}",
        "output_path": str(dest),
    }
