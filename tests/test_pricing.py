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

        zero_price = DEFAULT_CONFIG.replace("input_usd_per_mtok = 10.0", "input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("cached_input_usd_per_mtok = 1.0", "cached_input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("output_usd_per_mtok = 30.0", "output_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("input_usd_per_mtok = 2.0", "input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("cached_input_usd_per_mtok = 0.2", "cached_input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("output_usd_per_mtok = 6.0", "output_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("input_usd_per_mtok = 0.5", "input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("cached_input_usd_per_mtok = 0.05", "cached_input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("output_usd_per_mtok = 1.5", "output_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("input_usd_per_mtok = 0.2", "input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("cached_input_usd_per_mtok = 0.02", "cached_input_usd_per_mtok = 0.0")
        zero_price = zero_price.replace("output_usd_per_mtok = 0.6", "output_usd_per_mtok = 0.0")

        with tempfile.TemporaryDirectory() as tmp:
            ladder = load_ladder(write_config(Path(tmp) / "conductor.toml", zero_price))
            usage = TokenUsage(1_000_000, 0, 0, 0, 1_000_000)

            self.assertFalse(pricing_verified(ladder))
            self.assertEqual(estimate_usd(usage, ladder.tiers[0], ladder), 5.0)


if __name__ == "__main__":
    unittest.main()
