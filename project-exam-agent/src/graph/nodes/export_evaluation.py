"""
Node: export_evaluation
Saves the approved evaluation drafts as Markdown reports.
One file per student + one combined report, under output/{timestamp}/.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _render_report(draft: dict) -> str:
    lines = [
        f"# 프로젝트 평가 — {draft['name']} ({draft['student_id']})",
        "",
        "## 프로젝트 요약",
        draft.get("summary", ""),
        "",
        "## 루브릭 항목별 피드백",
    ]
    for item, feedback in draft.get("feedback_items", {}).items():
        lines += [f"### {item}", feedback, ""]

    lines += ["## 종합 의견", draft.get("overall_feedback", ""), ""]
    return "\n".join(lines)


def export_evaluation(state: dict) -> dict:
    """
    State reads:  evaluation_drafts
    State writes: output_dir (path to saved reports)
    """
    drafts: list[dict] = state.get("evaluation_drafts", [])

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("output") / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    combined_parts = [f"# 프로젝트 평가 종합 — {timestamp}\n"]

    for draft in drafts:
        report   = _render_report(draft)
        filename = f"{draft['student_id']}_{draft['name'].replace(' ', '_')}.md"
        (output_dir / filename).write_text(report, encoding="utf-8")
        combined_parts.append(report)

    combined_path = output_dir / "_combined.md"
    combined_path.write_text("\n\n---\n\n".join(combined_parts), encoding="utf-8")

    return {
        "current_stage": "export_evaluation",
        "overall_progress": 100,
        "status_message": f"리포트 저장 완료 → {output_dir}",
        "output_dir": str(output_dir),
    }
