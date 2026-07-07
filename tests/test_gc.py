import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import restore_env, set_env


def _make_runs(root: Path, runs: list[tuple[str, float]]) -> Path:
    state = root / "state"
    state.mkdir(parents=True)
    for name, age_days in runs:
        run_dir = state / name
        run_dir.mkdir()
        (run_dir / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
        stamp = time.time() - age_days * 86400
        os.utime(run_dir, (stamp, stamp))
    return state


class GcTests(unittest.TestCase):
    def test_keep_newest_removes_the_rest(self):
        from conductor.gc import prune

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_runs(Path(tmp), [("old", 10), ("mid", 5), ("new", 1)])
            removed, kept = prune(state, keep=2, older_than_days=None)
            self.assertEqual(removed, ["old"])
            self.assertEqual(set(kept), {"new", "mid"})

    def test_older_than_days(self):
        from conductor.gc import prune

        with tempfile.TemporaryDirectory() as tmp:
            state = _make_runs(Path(tmp), [("old", 10), ("new", 1)])
            removed, kept = prune(state, keep=None, older_than_days=7)
            self.assertEqual(removed, ["old"])
            self.assertEqual(kept, ["new"])

    def test_dry_run_via_main_keeps_dirs(self):
        from conductor.gc import main

        with tempfile.TemporaryDirectory() as tmp:
            _make_runs(Path(tmp) / "home", [("old", 10), ("new", 1)])
            old = set_env(CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main(["--keep", "1", "--dry-run"])
                self.assertEqual(rc, 0)
                self.assertTrue((Path(tmp) / "home" / "state" / "old").exists())
            finally:
                restore_env(old)


if __name__ == "__main__":
    unittest.main()
