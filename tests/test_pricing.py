import tempfile
import unittest
import re
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


if __name__ == "__main__":
    unittest.main()
