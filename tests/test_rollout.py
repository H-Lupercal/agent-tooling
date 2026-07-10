import json
import os
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
            target.write_text(
                (FIXTURES / "rollout_subagent.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            self.assertEqual(find_rollout("child-thread", root), target)

    def test_bounded_readers_reject_missing_malformed_and_mixed_model_data(self):
        from conductor.rollout import (
            claude_transcript_usage,
            find_rollout,
            latest_usage,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(latest_usage(root / "missing.jsonl"))
            self.assertIsNone(latest_usage(root))
            self.assertIsNone(find_rollout("", root))
            self.assertIsNone(find_rollout("missing", root / "absent"))

            malformed = root / "malformed.jsonl"
            malformed.write_text("not json\n", encoding="utf-8")
            self.assertIsNone(latest_usage(malformed))
            self.assertIsNone(claude_transcript_usage(malformed))

            mixed = root / "mixed.jsonl"
            mixed.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "model": model,
                                "usage": {"input_tokens": 1, "output_tokens": 1},
                            },
                        }
                    )
                    for model in ("model-a", "model-b")
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertIsNone(claude_transcript_usage(mixed))

            negative = root / "negative.jsonl"
            negative.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "model-a",
                            "usage": {"input_tokens": -1},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertIsNone(claude_transcript_usage(negative))

    def test_session_metadata_reader_is_bounded_and_never_follows_symlinks(self):
        from conductor.rollout import read_session_meta

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oversized = root / "oversized.jsonl"
            oversized.write_text("{" + ("x" * 70_000) + "}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unavailable or oversized"):
                read_session_meta(oversized)

            link = root / "linked.jsonl"
            try:
                os.symlink(FIXTURES / "rollout_root.jsonl", link)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(ValueError, "unavailable or oversized"):
                read_session_meta(link)

    def test_find_rollout_falls_back_to_validated_session_metadata(self):
        from conductor.rollout import find_rollout

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = root / "rollout-newest.jsonl"
            malformed.write_text("{}\n", encoding="utf-8")
            target = root / "rollout-unrelated-name.jsonl"
            target.write_text(
                (FIXTURES / "rollout_subagent.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            self.assertEqual(find_rollout("child-thread", root), target)


if __name__ == "__main__":
    unittest.main()
