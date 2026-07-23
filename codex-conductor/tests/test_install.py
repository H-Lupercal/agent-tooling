import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


class InstallTests(unittest.TestCase):
    def test_codex_hook_hashes_match_runtime_normalization(self):
        from conductor.install import _codex_hook_trust_entries, _render_hooks_json

        hooks_path = Path("/opt/conductor/hooks.json")
        with patch("conductor.install.sys.executable", "/usr/bin/python3"):
            entries = _codex_hook_trust_entries(
                hooks_path, _render_hooks_json(Path("/opt/conductor/hooks"))
            )

        self.assertEqual(
            entries[f"{hooks_path}:pre_tool_use:0:0"],
            "sha256:ceae1d8444392b1a494c0d71237d3541a0db4771de8790b2d1f533cd6c90f779",
        )
        self.assertEqual(
            entries[f"{hooks_path}:post_tool_use:0:0"],
            "sha256:c75f6a1633d9663b0641eb7b7c816c623fdeaa902c938ab5c024c3b98a30cca0",
        )

    def test_install_trusts_generated_codex_hooks_and_replaces_stale_state(self):
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            hooks_path = codex_home / "hooks.json"
            stale_key = f"{hooks_path}:pre_tool_use:0:0"
            unrelated_key = "/tmp/other-hooks.json:pre_tool_use:0:0"
            (codex_home / "config.toml").write_text(
                "\n".join(
                    (
                        f'[hooks.state."{stale_key}"]',
                        'trusted_hash = "sha256:stale"',
                        "",
                        f'[hooks.state."{unrelated_key}"]',
                        'trusted_hash = "sha256:keep"',
                        "",
                    )
                ),
                encoding="utf-8",
            )

            install(codex_home=codex_home, agents_path=Path(tmp) / "AGENTS.md")

            config = tomllib.loads((codex_home / "config.toml").read_text())
            states = config["hooks"]["state"]
            conductor_states = {
                key: value
                for key, value in states.items()
                if key.startswith(str(hooks_path))
            }
            self.assertEqual(len(conductor_states), 5)
            self.assertTrue(
                all(
                    value["trusted_hash"].startswith("sha256:")
                    and value["trusted_hash"] != "sha256:stale"
                    for value in conductor_states.values()
                )
            )
            self.assertEqual(states[unrelated_key]["trusted_hash"], "sha256:keep")

    def test_policy_template_uses_installed_package(self):
        from conductor.install import _render_policy

        project_root = Path("/tmp/public checkout/codex-conductor")
        policy = _render_policy(project_root)

        self.assertIn("conductor status --last --pretty", policy)
        self.assertIn("conductor report --last", policy)
        self.assertNotIn("python3 -m conductor.", policy)
        self.assertNotIn("PYTHONPATH=", policy)
        self.assertNotIn(str(project_root), policy)
        self.assertNotIn("{{PROJECT_ROOT}}", policy)

    def test_install_idempotent_uninstall_and_conflict(self):
        from conductor.errors import InstallationConflictError
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
            self.assertIn(
                str(codex_home / "conductor" / "hooks" / "pre_tool_use.py"), pre_cmd
            )
            self.assertNotIn("PYTHONPATH=", pre_cmd)

            install(codex_home=codex_home, agents_path=agents_path)
            self.assertEqual(
                config_once, (codex_home / "config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                hooks_once, (codex_home / "hooks.json").read_text(encoding="utf-8")
            )
            self.assertEqual(agents_once, agents_path.read_text(encoding="utf-8"))

            uninstall(codex_home=codex_home, agents_path=agents_path)
            self.assertNotIn(
                "codex-conductor managed",
                (codex_home / "config.toml").read_text(encoding="utf-8"),
            )
            self.assertFalse((codex_home / "hooks.json").exists())
            self.assertNotIn(
                "codex-conductor policy", agents_path.read_text(encoding="utf-8")
            )

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text(
                "[agents]\nmax_threads = 1\n", encoding="utf-8"
            )
            with self.assertRaises(InstallationConflictError):
                install(codex_home=codex_home, agents_path=Path(tmp) / "AGENTS.md")

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text(
                "# >>> codex-conductor managed >>>\n[agents]\n", encoding="utf-8"
            )
            with self.assertRaises(InstallationConflictError):
                install(codex_home=codex_home, agents_path=Path(tmp) / "AGENTS.md")


if __name__ == "__main__":
    unittest.main()
