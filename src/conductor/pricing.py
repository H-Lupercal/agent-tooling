from __future__ import annotations

from dataclasses import asdict, dataclass

from conductor.config import Ladder, Tier
from conductor.schemas import RawUsage


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int

    def as_dict(self) -> dict:
        return asdict(self)


def cost_usd(usage: TokenUsage, tier: Tier) -> float:
    billable_input = max(usage.input_tokens - usage.cached_input_tokens, 0)
    return (
        billable_input * tier.input_usd_per_mtok / 1_000_000
        + usage.cached_input_tokens * tier.cached_input_usd_per_mtok / 1_000_000
        + usage.output_tokens * tier.output_usd_per_mtok / 1_000_000
    )


def raw_usage_cost_usd(usage: RawUsage, tier: Tier) -> float:
    """Price canonical usage without double-billing cached input tokens."""

    uncached_input = max(
        usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens,
        0,
    )
    return (
        uncached_input * tier.pricing.input_usd_per_mtok / 1_000_000
        + usage.cache_read_tokens * tier.pricing.cache_read_usd_per_mtok / 1_000_000
        + usage.cache_write_tokens * tier.pricing.cache_write_usd_per_mtok / 1_000_000
        + usage.output_tokens * tier.pricing.output_usd_per_mtok / 1_000_000
    )


def tier_pricing_available(tier: Tier) -> bool:
    pricing = tier.pricing
    return all(
        value > 0
        for value in (
            pricing.input_usd_per_mtok,
            pricing.cache_read_usd_per_mtok,
            pricing.cache_write_usd_per_mtok,
            pricing.output_usd_per_mtok,
        )
    )


def pricing_verified(ladder: Ladder) -> bool:
    configured = [tier for tier in ladder.tiers if tier.enabled != "never"]
    return bool(configured) and all(tier_pricing_available(tier) for tier in configured)


def estimate_usd(usage: TokenUsage, tier: Tier, ladder: Ladder) -> float:
    if pricing_verified(ladder):
        return cost_usd(usage, tier)
    return usage.total_tokens / 1_000_000 * tier.relative_cost_weight * 0.05


def token_usage_from_dict(raw: dict | None) -> TokenUsage | None:
    if not isinstance(raw, dict):
        return None
    try:
        return TokenUsage(
            input_tokens=int(raw.get("input_tokens", 0)),
            cached_input_tokens=int(raw.get("cached_input_tokens", 0)),
            output_tokens=int(raw.get("output_tokens", 0)),
            reasoning_output_tokens=int(raw.get("reasoning_output_tokens", 0)),
            total_tokens=int(raw.get("total_tokens", 0)),
        )
    except (TypeError, ValueError):
        return None
