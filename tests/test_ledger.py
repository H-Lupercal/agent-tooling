import multiprocessing
import tempfile
import unittest
from pathlib import Path

from tests.helpers import restore_env, set_env


def _write_events(home: str, run_id: str, start: int, count: int) -> None:
    import os

    os.environ["CODEX_CONDUCTOR_HOME"] = home
    from conductor.ledger import append_event

    for index in range(start, start + count):
        append_event(run_id, {"event": "probe", "i": index})


class LedgerTests(unittest.TestCase):
    def test_append_read_aggregate(self):
        from conductor.ledger import active_spawns, append_event, read_events, same_tier_root_spawns, spent_usd

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(CODEX_CONDUCTOR_HOME=tmp)
            try:
                append_event("run", {"event": "spawn_approved", "tier": "standard", "task_name": "a", "caller_depth": 0})
                append_event("run", {"event": "spawn_approved", "tier": "standard", "task_name": "b", "caller_depth": 0})
                append_event("run", {"event": "subagent_start", "tier": "standard", "thread_id": "child"})
                append_event("run", {"event": "cost_recorded", "usd": 0.5})
                events = read_events("run")

                self.assertEqual(len(events), 4)
                self.assertEqual(spent_usd(events), 0.5)
                self.assertEqual(same_tier_root_spawns(events), 0)
                self.assertEqual(len(active_spawns(events)["standard"]), 1)
            finally:
                restore_env(old)

    def test_flock_keeps_concurrent_writes_valid(self):
        from conductor.ledger import read_events

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(CODEX_CONDUCTOR_HOME=tmp)
            try:
                procs = [
                    multiprocessing.Process(target=_write_events, args=(tmp, "run", 0, 200)),
                    multiprocessing.Process(target=_write_events, args=(tmp, "run", 200, 200)),
                ]
                for proc in procs:
                    proc.start()
                for proc in procs:
                    proc.join()
                    self.assertEqual(proc.exitcode, 0)

                self.assertEqual(len(read_events("run")), 400)
            finally:
                restore_env(old)


if __name__ == "__main__":
    unittest.main()
