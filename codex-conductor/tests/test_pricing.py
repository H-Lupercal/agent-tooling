import re
import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, write_config


class PricingTests(unittest.TestCase):
    def test_cached_token_math(self):
        from conductor.config import load_ladder
        from conductor.pricing import TokenUsage, cost_usd

        with tempfile.TemporaryDirectory() as tmp:
            ladder = load_ladder(write_config(Path(tmp) / "conductor.toml"))
            tier = ladder.tiers[0]
            usage = TokenUsage(17425, 4480, 328, 80, 17753)

            self.assertAlmostEqual(cost_usd(usage, tier), 0.14377, places=5)

    def test_pricing_verified_and_fallback_estimate(self):
        from conductor.config import load_ladder
        from conductor.pricing import TokenUsage, estimate_usd, pricing_verified
        from conductor.schemas import ConductorConfig

        zero_price = re.sub(
            r"^(input|cache_read|cache_write|output)_usd_per_mtok = .+$",
            lambda match: f"{match.group(1)}_usd_per_mtok = 0.0",
            DEFAULT_CONFIG,
            flags=re.MULTILINE,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ladder = load_ladder(write_config(Path(tmp) / "conductor.toml", zero_price))
            usage = TokenUsage(1_000_000, 0, 0, 0, 1_000_000)

            self.assertFalse(pricing_verified(ladder))
            self.assertEqual(estimate_usd(usage, ladder.tiers[0], ladder), 5.0)

        with tempfile.TemporaryDirectory() as tmp:
            ladder = load_ladder(write_config(Path(tmp) / "conductor.toml"))
            raw = ladder.model_dump(mode="python")
            raw["tiers"][1]["pricing"] = {
                key: 0.0 for key in raw["tiers"][1]["pricing"]
            }
            partially_configured = ConductorConfig.model_validate(raw)

            self.assertFalse(pricing_verified(partially_configured))

            raw = ladder.model_dump(mode="python")
            raw["tiers"][0]["pricing"]["cache_write_usd_per_mtok"] = 0.0
            missing_dimension = ConductorConfig.model_validate(raw)
            self.assertFalse(pricing_verified(missing_dimension))

    def test_verified_estimate_and_usage_parsing(self):
        from conductor.config import load_ladder
        from conductor.pricing import (
            TokenUsage,
            estimate_usd,
            token_usage_from_dict,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ladder = load_ladder(write_config(Path(tmp) / "conductor.toml"))
            usage = TokenUsage(1000, 100, 20, 5, 1020)
            self.assertEqual(usage.as_dict()["input_tokens"], 1000)
            self.assertAlmostEqual(
                estimate_usd(usage, ladder.tiers[0], ladder),
                0.0097,
                places=5,
            )

        self.assertIsNone(token_usage_from_dict(None))
        self.assertIsNone(token_usage_from_dict({"input_tokens": object()}))
        self.assertEqual(
            token_usage_from_dict(
                {
                    "input_tokens": "10",
                    "cached_input_tokens": 2,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 1,
                    "total_tokens": 13,
                }
            ),
            TokenUsage(10, 2, 3, 1, 13),
        )


if __name__ == "__main__":
    unittest.main()
