import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, restore_env, set_env, write_config, write_models_cache


class CliTests(unittest.TestCase):
    def test_status_dispatch_returns_json(self):
        from conductor.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(Path(tmp) / "c.toml", DEFAULT_CONFIG)),
                CODEX_MODELS_CACHE=str(write_models_cache(Path(tmp) / "m.json", [])),
            )
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = main(["status", "--run", "none"])
                self.assertEqual(rc, 0)
                self.assertIn("run_id", buf.getvalue())
            finally:
                restore_env(old)

    def test_gc_dispatch(self):
        from conductor.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main(["gc", "--dry-run"])
                self.assertEqual(rc, 0)
            finally:
                restore_env(old)

    def test_help_returns_zero(self):
        from conductor.cli import main

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--help"]), 0)

    def test_no_args_and_unknown_command_return_two(self):
        from conductor.cli import main

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 2)
            self.assertEqual(main(["frobnicate"]), 2)


if __name__ == "__main__":
    unittest.main()
