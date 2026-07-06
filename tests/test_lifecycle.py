import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, FIXTURES, restore_env, set_env, write_config


class LifecycleTests(unittest.TestCase):
    def test_start_stop_record_lifecycle_and_cost(self):
        from conductor.hooks.lifecycle import handle
        from conductor.ledger import read_events

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(Path(tmp) / "conductor.toml", DEFAULT_CONFIG)),
            )
            try:
                start = json.loads((FIXTURES / "hook_payloads" / "subagent_start.json").read_text(encoding="utf-8"))
                stop = json.loads((FIXTURES / "hook_payloads" / "subagent_stop.json").read_text(encoding="utf-8"))
                start["agent_transcript_path"] = str(FIXTURES / "rollout_subagent.jsonl")
                stop["agent_transcript_path"] = str(FIXTURES / "rollout_subagent.jsonl")

                handle(start)
                handle(stop)
                events = read_events("root-run")

                self.assertEqual([event["event"] for event in events], ["subagent_start", "subagent_stop", "cost_recorded"])
                self.assertEqual(events[-1]["tokens"]["total_tokens"], 17753)
                self.assertGreater(events[-1]["usd"], 0)
            finally:
                restore_env(old)


if __name__ == "__main__":
    unittest.main()
