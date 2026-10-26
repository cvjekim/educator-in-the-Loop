"""Build an isolated Vercel Build Output API v3 package; never deploy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DEMO = """<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>강의 준비 서비스 · 배포 연결 확인</title>
<main><h1>2차 개발 배포 연결 확인</h1>
<p>Vercel 정적 preview 하네스의 연결 확인 페이지입니다.</p>
<p>사용자 서비스는 개발 예정입니다. 로그인, 업로드, RAG, 에이전트 실행 기능은 제공하지 않습니다.</p>
<p>실제 강의자료와 사용자 정보는 이 페이지에 포함되지 않습니다.</p></main></html>
"""


def prepare(target, root=ROOT):
    staging = root / "artifacts/preview"
    source = root / "apps/web/dist"
    if target == "web":
        if not (source / "index.html").is_file():
            raise ValueError("Build apps/web first: dist/index.html is missing")
        for path in source.rglob("*"):
            if path.is_symlink() or path.name.startswith(".") or path.suffix in (".pem", ".key"):
                raise ValueError(f"Unexpected private file or symlink in web output: {path.name}")
    # Fixed generated location only; rebuilding removes stale assets/project metadata.
    if staging.is_symlink() or (root / "artifacts").is_symlink():
        raise ValueError("Staging directory must not be a symlink")
    if staging.exists():
        shutil.rmtree(staging)
    output = staging / ".vercel/output"
    static = output / "static"
    static.mkdir(parents=True)
    if target == "demo":
        (static / "index.html").write_text(DEMO)
    else:
        shutil.copytree(source, static, dirs_exist_ok=True)
    config = {"version": 3, "routes": [{"handle": "filesystem"},
                                      {"src": "/.*", "dest": "/index.html"}]}
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    return staging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("demo", "web"), default="demo")
    args = parser.parse_args()
    try:
        print(prepare(args.target))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
