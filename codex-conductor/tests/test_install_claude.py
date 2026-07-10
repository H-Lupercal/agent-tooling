import json
import tempfile
import unittest
from pathlib import Path


class ClaudeInstallTests(unittest.TestCase):
    def test_install_merges_settings_preserves_foreign_hooks_and_uninstalls_cleanly(
        self,
    ):
        from conductor.install import install, uninstall

        with tempfile.TemporaryDirectory() as tmp:
            claude_home = Path(tmp) / ".claude"
            claude_home.mkdir()
            settings_path = claude_home / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "model": "opus",
                        "hooks": {
                            "Notification": [],
                            "SessionStart": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/usr/local/bin/foreign-session",
                                        }
                                    ]
                                }
                            ],
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/usr/local/bin/foreign-pre",
                                        }
                                    ],
                                }
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            written = install(provider="claude", claude_home=claude_home)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            hooks = settings["hooks"]
            commands = [
                hook["command"]
                for groups in hooks.values()
                for group in groups
                for hook in group.get("hooks", [])
            ]
            wrapper = claude_home / "conductor" / "hooks" / "pre_tool_use.py"
            wrapper_text = wrapper.read_text(encoding="utf-8")

            self.assertIn(claude_home / "settings.json", written)
            self.assertEqual(settings["model"], "opus")
            self.assertIn("/usr/local/bin/foreign-session", commands)
            self.assertIn("/usr/local/bin/foreign-pre", commands)
            self.assertIn("SubagentStart", hooks)
            self.assertIn("SubagentStop", hooks)
            self.assertEqual(hooks["PreToolUse"][-1]["matcher"], "Task")
            self.assertIn(
                "--provider claude", hooks["PreToolUse"][-1]["hooks"][0]["command"]
            )
            self.assertIn("CODEX_CONDUCTOR_HOME", wrapper_text)
            self.assertIn(str(claude_home / "conductor"), wrapper_text)
            self.assertTrue(
                (claude_home / "CLAUDE.md")
                .read_text(encoding="utf-8")
                .count("codex-conductor policy")
                >= 2
            )

            install(provider="claude", claude_home=claude_home)
            self.assertEqual(
                len(
                    json.loads(settings_path.read_text(encoding="utf-8"))["hooks"][
                        "PreToolUse"
                    ]
                ),
                2,
            )

            uninstall(provider="claude", claude_home=claude_home)
            uninstalled = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(
                list(uninstalled["hooks"]["SessionStart"]),
                [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/usr/local/bin/foreign-session",
                            }
                        ]
                    }
                ],
            )
            self.assertEqual(
                list(uninstalled["hooks"]["PreToolUse"]),
                [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "/usr/local/bin/foreign-pre"}
                        ],
                    }
                ],
            )
            self.assertEqual(uninstalled["hooks"]["Notification"], [])
            self.assertNotIn("SubagentStart", uninstalled["hooks"])
            self.assertNotIn("SubagentStop", uninstalled["hooks"])
            self.assertNotIn(
                "codex-conductor policy",
                (claude_home / "CLAUDE.md").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
