"""Package only public backend runtime source, never private working directories."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'artifacts/backend'
AGENTS = ('manager-agent', 'lecture-note-agent', 'practice-agent', 'written-exam-agent', 'project-exam-agent')


def prepare():
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ('apps', *AGENTS):
        target = DEST / name
        if target.is_symlink():
            raise ValueError('Backend staging must not contain symlinks')
        if target.exists():
            shutil.rmtree(target)
    for folder in ('apps/api', *(a+'/src' for a in AGENTS), *(a+'/prompts' for a in AGENTS)):
        for source in (ROOT / folder).rglob('*'):
            if source.is_file() and not source.is_symlink() and '__pycache__' not in source.parts and (source.suffix == '.py' or ('prompts' in source.parts and source.suffix == '.md')):
                target = DEST / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for name in ('apps/__init__.py', 'pyproject.toml', 'vercel.json'):
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (DEST / '.vercelignore').write_text('.agents/\n.claude/\n.codex/\n.env*\n*.log\n')
    return DEST


if __name__ == '__main__':
    print(prepare())
