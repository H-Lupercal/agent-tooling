import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, restore_env, set_env, write_config, write_models_cache


class ConfigTests(unittest.TestCase):
    def test_valid_default_loads_and_auto_tiers_follow_models_cache(self):
        from conductor.config import enabled_tiers, load_ladder

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = write_config(root / "conductor.toml")
            models = write_models_cache(root / "models.json", ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"])

            ladder = load_ladder(cfg)

            self.assertEqual([tier.name for tier in ladder.tiers], ["frontier", "standard", "mini", "spark"])
            self.assertEqual(enabled_tiers(ladder, models), [0, 1, 2])

    def test_env_budget_override_wins(self):
        from conductor.config import load_ladder

        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp) / "conductor.toml")
            old = set_env(CONDUCTOR_RUN_USD_CAP="1.25")
            try:
                self.assertEqual(load_ladder(cfg).budget.run_usd_cap, 1.25)
            finally:
                restore_env(old)

    def test_validation_errors_have_exact_messages(self):
        from conductor.config import ConfigError, load_ladder

        cases = [
            ("name = \"frontier\"", "name = \"standard\"", "duplicate tier name: standard"),
            ("model = \"gpt-5.5\"", "model = \"gpt-5.4\"", "duplicate model: gpt-5.4"),
            ("enabled = \"always\"", "enabled = \"sometimes\"", "tier frontier: enabled must be always|auto|never"),
            ("max_concurrent = 2", "max_concurrent = 0", "tier frontier: max_concurrent must be >= 1"),
            ("input_usd_per_mtok = 10.0", "input_usd_per_mtok = -1.0", "tier frontier: negative price"),
            ("run_usd_cap = 10.00", "run_usd_cap = 0", "budget.run_usd_cap must be > 0"),
            ("max_depth = 3", "max_depth = 6", "policy.max_depth must be in 1..5"),
        ]
        for old, new, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                cfg = write_config(Path(tmp) / "conductor.toml", DEFAULT_CONFIG.replace(old, new, 1))
                with self.assertRaisesRegex(ConfigError, message):
                    load_ladder(cfg)

    def test_task_classes_must_partition(self):
        from conductor.config import ConfigError, load_ladder

        text = DEFAULT_CONFIG.replace(
            'task_classes = ["implementation", "refactor", "debug", "cross_module_change"]',
            'task_classes = ["implementation", "tests", "debug", "cross_module_change"]',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp) / "conductor.toml", text)
            with self.assertRaisesRegex(ConfigError, "task class tests assigned to multiple tiers: standard, mini"):
                load_ladder(cfg)


if __name__ == "__main__":
    unittest.main()
