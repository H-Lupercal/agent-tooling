import tempfile
import unittest
import json
from pathlib import Path


class InstallTests(unittest.TestCase):
    def test_policy_template_renders_checkout_path(self):
        from conductor.install import _render_policy

        project_root = Path("/tmp/public checkout/codex-conductor")
        policy = _render_policy(project_root)

        self.assertIn(
            "PYTHONPATH='/tmp/public checkout/codex-conductor' python3 -m conductor.status --pretty",
            policy,
        )
        self.assertIn(
            "PYTHONPATH='/tmp/public checkout/codex-conductor' python3 -m conductor.report --last",
            policy,
        )
        self.assertEqual(policy.count(str(project_root)), 2)
        self.assertNotIn("{{PROJECT_ROOT}}", policy)

    def test_install_idempotent_uninstall_and_conflict(self):
        from conductor.install import install, uninstall

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            agents_path = Path(tmp) / "AGENTS.md"
            agents_path.write_text("# AGENTS\n", encoding="utf-8")
            install(codex_home=codex_home, agents_path=agents_path)
            config_once = (codex_home / "config.toml").read_text(encoding="utf-8")
            hooks_once = (codex_home / "hooks.json").read_text(encoding="utf-8")
            agents_once = agents_path.read_text(encoding="utf-8")
            hooks = json.loads(hooks_once)
            pre_cmd = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertIn(str(codex_home / "conductor" / "hooks" / "pre_tool_use.py"), pre_cmd)
            self.assertNotIn("PYTHONPATH=", pre_cmd)

            install(codex_home=codex_home, agents_path=agents_path)
            self.assertEqual(config_once, (codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(hooks_once, (codex_home / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(agents_once, agents_path.read_text(encoding="utf-8"))

            uninstall(codex_home=codex_home, agents_path=agents_path)
            self.assertNotIn("codex-conductor managed", (codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertFalse((codex_home / "hooks.json").exists())
            self.assertNotIn("codex-conductor policy", agents_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text("[agents]\nmax_threads = 1\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                install(codex_home=codex_home, agents_path=Path(tmp) / "AGENTS.md")
            self.assertEqual(caught.exception.code, 2)

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text("# >>> codex-conductor managed >>>\n[agents]\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                install(codex_home=codex_home, agents_path=Path(tmp) / "AGENTS.md")
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
