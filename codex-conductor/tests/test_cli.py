import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    DEFAULT_CONFIG,
    restore_env,
    set_env,
    write_config,
    write_models_cache,
)


class CliTests(unittest.TestCase):
    def test_status_dispatch_returns_json(self):
        from conductor.cli import main
        from conductor.store import Store

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"),
                CODEX_CONDUCTOR_CONFIG=str(
                    write_config(Path(tmp) / "c.toml", DEFAULT_CONFIG)
                ),
                CODEX_MODELS_CACHE=str(write_models_cache(Path(tmp) / "m.json", [])),
            )
            try:
                Store(Path(tmp) / "home" / "state" / "conductor.db").create_run(
                    "run-1",
                    provider="codex",
                    generation=1,
                    mode="admission",
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = main(["status", "--run", "run-1"])
                self.assertEqual(rc, 0)
                self.assertIn("run_id", buf.getvalue())

                report = io.StringIO()
                with contextlib.redirect_stdout(report):
                    rc = main(["report", "--run", "run-1", "--json"])
                self.assertEqual(rc, 0)
                self.assertIn("total_usd", report.getvalue())

                recovery = io.StringIO()
                with contextlib.redirect_stdout(recovery):
                    rc = main(["recover", "--run", "run-1", "--json"])
                self.assertEqual(rc, 0)
                self.assertIn("recoverable", recovery.getvalue())
            finally:
                restore_env(old)

    def test_gc_dispatch(self):
        from conductor.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main(["gc"])
                self.assertEqual(rc, 0)
            finally:
                restore_env(old)

    def test_help_returns_zero(self):
        from conductor import __version__
        from conductor.cli import main

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--help"]), 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--version"]), 0)
        self.assertEqual(output.getvalue().strip(), f"conductor {__version__}")

    def test_install_and_migration_dispatch(self):
        from conductor.cli import main
        from tests.helpers import FIXTURES

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "install",
                            "--dry-run",
                            "--codex-home",
                            str(root / ".codex"),
                            "--agents-path",
                            str(root / "AGENTS.md"),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "migrate-v1",
                            str(FIXTURES / "v1-conductor.toml"),
                            str(root / "candidate.toml"),
                        ]
                    ),
                    0,
                )
            self.assertTrue((root / "candidate.toml").exists())

    def test_no_args_and_unknown_command_return_two(self):
        from conductor.cli import main

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 2)
            self.assertEqual(main(["frobnicate"]), 2)


if __name__ == "__main__":
    unittest.main()
