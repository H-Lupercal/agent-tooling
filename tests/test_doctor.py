import tempfile
import unittest
from pathlib import Path


class DoctorTests(unittest.TestCase):
    def test_codex_all_pass_after_install(self):
        from conductor.doctor import run_checks
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            agents = Path(tmp) / "AGENTS.md"
            install(codex_home=codex_home, agents_path=agents)
            report = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertTrue(report["ok"])
            self.assertEqual(statuses["hooks_json"], "ok")
            self.assertEqual(statuses["hook_wrappers"], "ok")
            self.assertEqual(statuses["models_cache"], "warn")

    def test_codex_missing_install_fails(self):
        from conductor.doctor import run_checks

        with tempfile.TemporaryDirectory() as tmp:
            report = run_checks("codex", home=Path(tmp) / ".codex", policy_path=Path(tmp) / "AGENTS.md")
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertFalse(report["ok"])
            self.assertEqual(statuses["hooks_json"], "fail")

    def test_claude_all_pass_after_install(self):
        from conductor.doctor import run_checks
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            claude_home = Path(tmp) / ".claude"
            claude_home.mkdir()
            claude_md = claude_home / "CLAUDE.md"
            install(provider="claude", claude_home=claude_home, claude_md_path=claude_md)
            report = run_checks("claude", home=claude_home, policy_path=claude_md)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertTrue(report["ok"])
            self.assertEqual(statuses["settings_hooks"], "ok")


if __name__ == "__main__":
    unittest.main()
