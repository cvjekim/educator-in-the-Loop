import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preview = load("prepare_preview")
harness = load("harness")
offline = load("offline_pytest")


class HarnessTests(unittest.TestCase):
    def test_demo_excludes_repository_files_and_cleans_stale_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text("PRIVATE=example")
            staging = preview.prepare("demo", root)
            (staging / "stale.txt").write_text("stale")
            preview.prepare("demo", root)
            files = {str(p.relative_to(staging)) for p in staging.rglob("*") if p.is_file()}
            self.assertEqual(files, {".vercel/output/config.json", ".vercel/output/static/index.html"})
            self.assertEqual(json.loads((staging / ".vercel/output/config.json").read_text())["version"], 3)

    def test_web_requires_real_build_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                preview.prepare("web", root)
            dist = root / "apps/web/dist"
            dist.mkdir(parents=True)
            (dist / "index.html").write_text("built app")
            (dist / "leak").symlink_to(root / ".env")
            with self.assertRaises(ValueError):
                preview.prepare("web", root)

    def test_web_copies_only_dist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dist = root / "apps/web/dist"
            dist.mkdir(parents=True)
            (dist / "index.html").write_text("built app")
            (root / "private.pdf").write_text("private")
            staging = preview.prepare("web", root)
            self.assertEqual((staging / ".vercel/output/static/index.html").read_text(), "built app")
            self.assertFalse((staging / ".vercel/output/static/private.pdf").exists())

    def test_runner_keeps_failure_and_continues_with_isolated_cwd(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(harness, "ROOT", Path(folder)):
            outcomes = [subprocess.CompletedProcess([], 1, "failure", ""),
                        subprocess.CompletedProcess([], 0, "pass", "")]
            with patch.object(harness.subprocess, "run", side_effect=outcomes) as run:
                self.assertEqual(harness.run_tests(["manager-agent", "practice-agent"], 3), 1)
            self.assertNotEqual(run.call_args_list[0].kwargs["cwd"], run.call_args_list[1].kwargs["cwd"])
            self.assertEqual(len(json.loads((Path(folder) / "artifacts/tests/summary.json").read_text())), 2)

    def test_timeout_is_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(harness, "ROOT", Path(folder)):
            with patch.object(harness.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 1)):
                self.assertEqual(harness.run_tests(["manager-agent"], 1), 1)

    def test_test_environment_disables_credentials_and_dotenv(self):
        with patch.dict(harness.os.environ, {"OPENAI_API_KEY": "real", "GITHUB_TOKEN": "real"}):
            env = harness.test_environment()
        self.assertEqual(env["OPENAI_API_KEY"], "offline-test-key")
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")

    def test_network_guard_rejects_external_before_connect(self):
        with self.assertRaises(RuntimeError):
            offline._guard(lambda *args: self.fail("Must not connect"))(None, ("example.com", 443))
        self.assertTrue(offline._local(("127.0.0.1", 1234)))


if __name__ == "__main__":
    unittest.main()
