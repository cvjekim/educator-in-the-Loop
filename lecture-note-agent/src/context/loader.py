"""
Context loader — extracts and merges text from lecture materials.

Reads subjects/{subject}/configuration.md to resolve file paths,
then extracts text from PDFs (pdfplumber) and PPTs (python-pptx).
"""

from pathlib import Path


def load_subject_context(subject: str, week: int) -> str:
    """Return merged text from all reference materials for the given subject/week."""
    config = _read_subject_config(subject)
    texts: list[str] = []

    for path in config.get("reference_paths", []):
        p = Path(path)
        if not p.exists():
            continue
        if p.suffix.lower() == ".pdf":
            texts.append(_extract_pdf(p))
        elif p.suffix.lower() in (".pptx", ".ppt"):
            texts.append(_extract_pptx(p))

    prev_note = config.get("previous_note_paths", {}).get(week)
    if prev_note and Path(prev_note).exists():
        p = Path(prev_note)
        if p.suffix.lower() == ".pdf":
            texts.append(_extract_pdf(p))

    return "\n\n".join(texts)


def _read_subject_config(subject: str) -> dict:
    """Parse subjects/{subject}/configuration.md into a usable dict."""
    from src.utils.subject_config import load_config
    try:
        return load_config(subject)
    except FileNotFoundError:
        return {"reference_paths": [], "previous_note_paths": {}}


def _extract_pdf(path: Path) -> str:
    """Extract all text from a PDF using pdfplumber."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )


def _extract_pptx(path: Path) -> str:
    """Extract all text frames from a PPTX file."""
    from pptx import Presentation
    prs = Presentation(str(path))
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    return "\n".join(texts)
