import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, FIXTURES, restore_env, set_env, write_config


class IdentityTests(unittest.TestCase):
    def test_resolves_root_run_id_depth_and_tier_from_payload_and_rollouts(self):
        from conductor.config import load_ladder
        from conductor.identity import resolve_caller

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            day = sessions / "2026" / "07" / "06"
            day.mkdir(parents=True)
            root_rollout = day / "rollout-root-run.jsonl"
            child_rollout = day / "rollout-child-thread.jsonl"
            shutil.copyfile(FIXTURES / "rollout_root.jsonl", root_rollout)
            shutil.copyfile(FIXTURES / "rollout_subagent.jsonl", child_rollout)
            ladder = load_ladder(write_config(root / "conductor.toml", DEFAULT_CONFIG))

            caller = resolve_caller(
                {"model": "gpt-5.4", "thread_id": "child-thread", "agent_transcript_path": str(child_rollout)},
                ladder,
                sessions,
            )

            self.assertEqual(caller.run_id, "root-run")
            self.assertEqual(caller.depth, 1)
            self.assertEqual(caller.tier_index, 1)

    def test_missing_identity_is_explicit(self):
        from conductor.config import load_ladder
        from conductor.identity import resolve_caller

        with tempfile.TemporaryDirectory() as tmp:
            ladder = load_ladder(write_config(Path(tmp) / "conductor.toml", DEFAULT_CONFIG))
            caller = resolve_caller({"model": "unknown", "thread_id": "child-thread"}, ladder, Path(tmp) / "sessions")

            self.assertIsNone(caller.run_id)
            self.assertIsNone(caller.tier_index)


if __name__ == "__main__":
    unittest.main()
