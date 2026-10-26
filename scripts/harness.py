"""Repository checks and isolated legacy-agent regression runner (stdlib only)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ("manager-agent", "lecture-note-agent", "practice-agent",
          "written-exam-agent", "project-exam-agent")


def test_environment():
    env = os.environ.copy()
    # Remove inherited provider credentials; dotenv must not restore local keys.
    for key in list(env):
        if any(part in key for part in ("API_KEY", "TOKEN", "SECRET")):
            env.pop(key)
    env.update(OPENAI_API_KEY="offline-test-key", AGENT_STUB_MODE="true",
               PYTHON_DOTENV_DISABLED="1", LANGCHAIN_TRACING_V2="false",
               LANGSMITH_TRACING="false", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=str(ROOT / "scripts"))
    env.pop("PYTEST_ADDOPTS", None)
    return env


def check():
    errors = []
    skills = list((ROOT / "skills").glob("*/SKILL.md"))
    if len(skills) != 5:
        errors.append("Expected five repository skills")
    for file in skills:
        content = file.read_text()
        header = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: (.+)\n---\n", content)
        if not header or header[1] != file.parent.name:
            errors.append(f"Invalid skill frontmatter: {file.relative_to(ROOT)}")
    for file in (ROOT / "docs/phase2").glob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", file.read_text()):
            if "://" not in target and not (file.parent / target.split("#")[0]).exists():
                errors.append(f"Broken link: {file.name}: {target}")
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                             "tests/harness", "-v"], cwd=ROOT)
    for error in errors:
        print(error, file=sys.stderr)
    return int(bool(errors) or result.returncode != 0)


def run_tests(agents, timeout):
    output = ROOT / "artifacts/tests"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for agent in agents:
        started = time.monotonic()
        junit = output / f"{agent}.xml"
        junit.unlink(missing_ok=True)  # Do not mistake an old report for this run.
        command = [sys.executable, "-m", "pytest", "-p", "offline_pytest", "tests/",
                   "-q", f"--junitxml={junit}"]
        print(f"Running {agent} ...", flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT / agent, env=test_environment(),
                                    capture_output=True, text=True, timeout=timeout)
            code, log = result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired as exc:
            code = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            log = (stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout)
            log += (stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr)
            log += f"\nSuite timed out after {timeout}s\n"
        (output / f"{agent}.log").write_text(log)
        print(log[-3000:], flush=True)
        results.append({"agent": agent, "exit_code": code,
                        "seconds": round(time.monotonic() - started, 2),
                        "mode": "mocked-regression", "junit": junit.exists()})
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return int(any(result["exit_code"] != 0 for result in results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    test = sub.add_parser("test")
    test.add_argument("--agent", choices=AGENTS, action="append")
    test.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.command == "check":
        return check()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return run_tests(args.agent or AGENTS, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
