"""
Deprecated. All implementations moved to src/.
This module re-exports everything for backward compatibility.

New import paths:
  from src.materials.loader import load_syllabus, load_materials
  from src.utils.parser    import parse_questions_response, ...
  from src.graph.nodes.*   import generate_questions, draft_rubric, ...
"""

from src.materials.loader import (  # noqa: F401
    load_materials,
    load_syllabus,
    _parse_pdf,
    BASE_DIR,
    SUBJECTS_DIR,
)
from src.utils.parser import (  # noqa: F401
    build_params_description,
    format_questions_for_rubric,
    parse_questions_response,
    parse_rubrics_response,
)
from src.graph.nodes.generate_questions import generate_questions  # noqa: F401
from src.graph.nodes.draft_rubric import draft_rubric              # noqa: F401
from src.graph.nodes.human_review import human_review              # noqa: F401
from src.graph.nodes.format_exam import (  # noqa: F401
    format_exam,
    build_question_paper,
    build_rubric_sheet,
)
