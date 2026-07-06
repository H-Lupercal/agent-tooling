import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES


class RolloutTests(unittest.TestCase):
    def test_reads_session_meta_and_latest_usage(self):
        from conductor.rollout import latest_usage, read_session_meta

        root = FIXTURES / "rollout_root.jsonl"
        child = FIXTURES / "rollout_subagent.jsonl"

        self.assertEqual(read_session_meta(root).thread_id, "root-run")
        self.assertIsNone(read_session_meta(root).parent_thread_id)
        self.assertEqual(read_session_meta(child).thread_source, "subagent")
        self.assertEqual(read_session_meta(child).parent_thread_id, "root-run")
        self.assertEqual(latest_usage(root).total_tokens, 2500)
        self.assertEqual(latest_usage(child).input_tokens, 17425)

    def test_find_rollout_by_thread_id(self):
        from conductor.rollout import find_rollout

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = root / "2026" / "07" / "06"
            day.mkdir(parents=True)
            target = day / "rollout-2026-07-06T00-00-00-child-thread.jsonl"
            target.write_text((FIXTURES / "rollout_subagent.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

            self.assertEqual(find_rollout("child-thread", root), target)


if __name__ == "__main__":
    unittest.main()
