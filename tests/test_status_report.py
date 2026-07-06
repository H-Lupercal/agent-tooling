import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, PROJECT_ROOT, restore_env, set_env, write_config, write_models_cache


class StatusReportTests(unittest.TestCase):
    def test_status_json_and_report_output(self):
        from conductor.ledger import append_event
        from conductor.report import build_report, render_human
        from conductor.status import build_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(root / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(root / "conductor.toml", DEFAULT_CONFIG)),
                CODEX_MODELS_CACHE=str(write_models_cache(root / "models.json", ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"])),
            )
            try:
                append_event("run", {"event": "run_started"})
                append_event("run", {"event": "spawn_approved", "tier": "standard", "model": "gpt-5.4"})
                append_event("run", {"event": "cost_recorded", "tier": "standard", "model": "gpt-5.4", "tokens": {"input_tokens": 1000, "cached_input_tokens": 100, "output_tokens": 100, "reasoning_output_tokens": 10, "total_tokens": 1100}, "usd": 0.01, "estimated": False})

                status = build_status("run")
                self.assertEqual(status["cap_usd"], 10.0)
                self.assertEqual(status["enabled_tiers"][0]["name"], "frontier")
                report = build_report("run")
                text = render_human(report)
                self.assertIn("standard", text)
                self.assertIn("TOTAL", text)
                self.assertIn("savings_pct", text)
            finally:
                restore_env(old)

    def test_unverified_report_points_to_active_config_path(self):
        from conductor.report import build_report, render_human

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".claude" / "conductor" / "conductor.toml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text((PROJECT_ROOT / "config" / "conductor.claude.toml").read_text(encoding="utf-8"), encoding="utf-8")
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(root / ".claude" / "conductor"),
                CODEX_CONDUCTOR_CONFIG=str(config_path),
            )
            try:
                text = render_human(build_report("none"))

                self.assertIn(f"PRICING UNVERIFIED - edit {config_path}", text)
                self.assertNotIn("~/.codex/conductor/conductor.toml", text)
            finally:
                restore_env(old)


if __name__ == "__main__":
    unittest.main()
