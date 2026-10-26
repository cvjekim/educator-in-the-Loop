"""Publication checks use synthetic names and never read private documents."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('public_guard', Path(__file__).resolve().parents[2] / 'scripts/public_source_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class PublicSourceTests(unittest.TestCase):
    def test_private_documents_and_materials_are_rejected(self):
        for name in ('paper/draft.md', 'proposal.docx', 'template.pdf', 'experiment_setup.md',
                     'docs/architecture.md', 'apps/api/subjects/notes.py', '.env', 'apps/web/.env',
                     'apps/web/data/roster.json'):
            with self.subTest(name=name):
                self.assertTrue(guard.violations(Path(name), 'synthetic'))

    def test_runtime_prompts_and_source_are_allowed(self):
        for name in ('apps/api/main.py', 'written-exam-agent/src/materials/loader.py', 'manager-agent/prompts/plan.md', '.env.example'):
            self.assertFalse(guard.violations(Path(name), 'synthetic'))

    def test_personal_paths_and_tokens_in_source_are_rejected(self):
        for content in ('/Users/' + 'sample/' + 'private', 'ghp_' + 'x' * 40):
            self.assertTrue(guard.violations(Path('apps/api/main.py'), content))
