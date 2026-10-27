"""Reject private artifacts and credentials from the tracked public source tree."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT = {'.gitignore', '.dockerignore', '.env.example', 'compose.yaml', 'pyproject.toml', 'vercel.json', 'LICENSE'}
ALLOWED_TREES = {'apps', 'tests', 'scripts', '.github', 'manager-agent', 'lecture-note-agent', 'practice-agent', 'written-exam-agent', 'project-exam-agent'}
SOURCE_EXTENSIONS = {'.py', '.json', '.yaml', '.yml', '.ts', '.tsx', '.css', '.html', '.mjs'}
PRIVATE_PARTS = {'data', 'materials', 'uploads', 'evaluation', 'experiments', 'subjects', 'paper', 'papers', 'docs', 'skills', 'research-private', 'artifacts', 'node_modules', 'dist', '__pycache__', '.vercel'}
PATTERNS = [r'/Users/[A-Za-z0-9_. -]+/', r'/home/[A-Za-z0-9_.-]+/', r'[A-Za-z]:\\Users\\[^\\\s]+\\',
            r'sk-(?:proj-)?[A-Za-z0-9_-]{30,}', r'gh[pousr]_[A-Za-z0-9]{30,}',
            r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----']


def violations(path, text):
    parts = path.parts
    private_parts = set(parts) & PRIVATE_PARTS
    if len(parts) == 4 and parts[0].endswith('-agent') and parts[1:3] == ('src', 'materials') and path.suffix == '.py':
        private_parts.discard('materials')
    if private_parts:
        return ['private directory']
    if len(parts) == 1:
        allowed = str(path) in ALLOWED_ROOT
    else:
        allowed = parts[0] in ALLOWED_TREES and (path.suffix in SOURCE_EXTENSIONS or path.name in {'Dockerfile', 'requirements.txt'})
        if path.suffix == '.md':
            allowed = len(parts) == 3 and parts[0].endswith('-agent') and parts[1] == 'prompts'
    issues = [] if allowed else ['not an allowed source file']
    if any(re.search(pattern, text) for pattern in PATTERNS):
        issues.append('credential or personal absolute path')
    return issues


if __name__ == '__main__':
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    failures = []
    for name in filter(None, paths):
        path = ROOT / name
        if path.is_symlink():
            failures.append((name, ['symlink']))
        elif path.is_file():
            issues = violations(Path(name), path.read_text(errors='replace'))
            if issues:
                failures.append((name, issues))
    for name, issues in failures:
        print(name + ': ' + ', '.join(issues))
    print('Public source guard:', 'FAILED' if failures else 'passed')
    raise SystemExit(bool(failures))
