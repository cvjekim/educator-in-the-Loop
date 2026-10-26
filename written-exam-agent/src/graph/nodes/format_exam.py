"""
Node: format_exam
Formats approved questions and rubrics into two Markdown documents:
  - question_paper: student-facing (questions only, no answers)
  - rubric_sheet:   professor-facing (questions + inline rubric + keywords)
"""

from __future__ import annotations

# Canonical display labels
_SECTION_LABEL: dict[str, str] = {
    "single_choice": "객관식 (5지선다)",
    "short_answer":  "단답형",
    "open_answer":   "서술형",
}
_SHORT_LABEL: dict[str, str] = {
    "single_choice": "객관식",
    "short_answer":  "단답형",
    "open_answer":   "서술형",
}
# Fixed section ordering: objective → short → essay
_SECTION_ORDER = ["single_choice", "short_answer", "open_answer"]


def build_question_paper(subject_name: str, questions: list[dict]) -> str:
    """
    Build the student-facing question paper (questions only, no answers).
    Questions are grouped by type in canonical order with a header.
    """
    if not questions:
        return f"# {subject_name} 시험 문제지\n\n(출제된 문제가 없습니다)\n"

    by_type: dict[str, list[dict]] = {t: [] for t in _SECTION_ORDER}
    for q in questions:
        qtype = q.get("question_type", "")
        if qtype not in by_type:
            by_type[qtype] = []
        by_type[qtype].append(q)

    lines: list[str] = [
        f"# {subject_name} 시험 문제지",
        "",
        f"**총 문항 수:** {len(questions)}문제"
        "  |  **이름:** _____________"
        "  |  **학번:** _____________",
        "",
        "---",
        "",
    ]

    section_num = 1
    ordered_types = _SECTION_ORDER + [t for t in by_type if t not in _SECTION_ORDER]
    for qtype in ordered_types:
        group = by_type.get(qtype, [])
        if not group:
            continue
        label = _SECTION_LABEL.get(qtype, qtype)
        lines += [f"## {section_num}부. {label}", ""]
        section_num += 1
        for q in group:
            lines.append(q.get("content", ""))
            lines += ["", "---", ""]

    return "\n".join(lines).rstrip() + "\n"


def build_rubric_sheet(
    subject_name: str,
    questions: list[dict],
    rubrics: list[dict],
) -> str:
    """
    Build the professor-facing answer key.
    Each question is followed immediately by its rubric in AGENT.MD format.
    """
    if not questions:
        return f"# {subject_name} 채점 기준표\n\n(출제된 문제가 없습니다)\n"

    total_pts = sum(
        rubrics[i].get("total_points", 0) if i < len(rubrics) else 0
        for i in range(len(questions))
    )

    lines: list[str] = [
        f"# {subject_name} 채점 기준표",
        "",
        f"**총 배점:** {total_pts}점  |  **총 문항 수:** {len(questions)}문제",
        "",
    ]

    for i, q in enumerate(questions):
        r        = rubrics[i] if i < len(rubrics) else {}
        num      = q.get("number", i + 1)
        qtype    = q.get("question_type", "")
        type_lbl = _SHORT_LABEL.get(qtype, qtype)
        q_pts    = r.get("total_points", "?")

        lines += ["---", ""]
        lines.append(f"**문제 {num}** [{type_lbl} · {q_pts}점]")
        lines += ["", q.get("content", ""), ""]

        criteria = r.get("criteria", [])
        if criteria:
            lines.append("루브릭:")
            for c in criteria:
                lines.append(f"{c.get('points', '?')}점: {c.get('description', '')}")
            lines.append("")

        keywords = r.get("keywords", [])
        if keywords:
            lines.append(f"핵심 키워드: {', '.join(str(k) for k in keywords)}")
            lines.append("")

    lines.append("---")
    return "\n".join(lines).rstrip() + "\n"


def format_exam(state: dict) -> dict:
    """
    State reads:  subject_name, questions, rubrics
    State writes: final_output → {question_paper, rubric_sheet}
    """
    subject_name: str        = state.get("subject_name", "시험")
    questions:    list[dict] = state.get("questions", [])
    rubrics:      list[dict] = state.get("rubrics", [])

    return {
        "final_output": {
            "question_paper": build_question_paper(subject_name, questions),
            "rubric_sheet":   build_rubric_sheet(subject_name, questions, rubrics),
        }
    }
