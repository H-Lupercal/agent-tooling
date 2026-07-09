from __future__ import annotations

from dataclasses import asdict, dataclass

from conductor.config import Ladder, Tier


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


def pricing_verified(ladder: Ladder) -> bool:
    return any(
        tier.enabled != "never"
        and (tier.input_usd_per_mtok > 0 or tier.cached_input_usd_per_mtok > 0 or tier.output_usd_per_mtok > 0)
        for tier in ladder.tiers
    )


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
