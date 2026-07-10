from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from toolbelt.schemas import (
    CapabilitySnapshot,
    CapabilityStatus,
    CatalogToolV2,
    EvidenceStrength,
    EvidenceV2,
    InstallScope,
)


@dataclass(frozen=True, slots=True)
class Recommendation:
    tool_id: str
    actionable: bool
    why: str
    evidence: tuple[EvidenceV2, ...]
    missing_requirements: tuple[str, ...]
    allowed_operations: tuple[str, ...]
    confidence: float


def recommend(
    catalog: Iterable[CatalogToolV2],
    evidence: Iterable[EvidenceV2],
    capabilities: CapabilitySnapshot,
    *,
    allow_user_scope: bool = False,
    allow_network: bool = False,
) -> list[Recommendation]:
    inventory = tuple(evidence)
    by_match_key: dict[str, EvidenceV2] = {f"{item.type}:{item.key}": item for item in inventory}
    native = set(capabilities.native)
    installed = set(capabilities.installed)
    managed = set(capabilities.managed)
    available = native | installed
    recommendations: list[Recommendation] = []

    for tool in catalog:
        if not tool.enabled or native.intersection(tool.suppressed_by_capabilities):
            continue
        strong = _matched(
            tool.strong_evidence,
            by_match_key,
            {EvidenceStrength.STRONG, EvidenceStrength.REQUIRED},
        )
        weak = tuple(
            dict.fromkeys(
                (
                    *_matched(
                        tool.weak_evidence,
                        by_match_key,
                        {
                            EvidenceStrength.WEAK,
                            EvidenceStrength.STRONG,
                            EvidenceStrength.REQUIRED,
                        },
                    ),
                    *_matched(
                        tool.strong_evidence,
                        by_match_key,
                        {EvidenceStrength.WEAK},
                    ),
                )
            )
        )
        matched_by_key = {
            (item.type, item.key, item.source, item.detail): item for item in (*strong, *weak)
        }
        matched = tuple(matched_by_key[key] for key in sorted(matched_by_key))
        live_names = {tool.id}
        if tool.live_name is not None:
            live_names.add(tool.live_name)
        is_installed = bool(installed.intersection(live_names))
        is_managed = bool(managed.intersection(live_names))

        if is_installed and not is_managed:
            recommendations.append(
                Recommendation(
                    tool_id=tool.id,
                    actionable=bool(strong),
                    why=f"Detected existing unmanaged {tool.name}; choose how Toolbelt should treat it.",
                    evidence=matched,
                    missing_requirements=(),
                    allowed_operations=("adopt", "leave_unmanaged", "replace"),
                    confidence=0.9 if strong else 0.25,
                )
            )
            continue
        if is_managed:
            recommendations.append(
                Recommendation(
                    tool_id=tool.id,
                    actionable=bool(strong),
                    why=f"{tool.name} is already managed by Toolbelt.",
                    evidence=matched,
                    missing_requirements=(),
                    allowed_operations=("verify", "remove"),
                    confidence=1.0,
                )
            )
            continue
        if not strong and not weak:
            continue

        missing: list[str] = []
        if capabilities.status is CapabilityStatus.UNKNOWN:
            missing.append("capability_inventory_unknown")
        if tool.install.requires_network and not allow_network:
            missing.append("network_approval")
        if tool.install_scope is InstallScope.USER and not allow_user_scope:
            missing.append("user_scope_approval")
        for requirement in tool.required_capabilities:
            if requirement not in available:
                missing.append(f"capability:{requirement}")

        if strong:
            why = "Matched strong evidence: " + ", ".join(
                f"{item.type}:{item.key}" for item in strong
            )
            confidence = 0.9
        else:
            why = "Only weak evidence matched; no installation is authorized."
            confidence = 0.25
        actionable = bool(strong) and not missing
        recommendations.append(
            Recommendation(
                tool_id=tool.id,
                actionable=actionable,
                why=why,
                evidence=matched,
                missing_requirements=tuple(missing),
                allowed_operations=("install",) if actionable else (),
                confidence=confidence,
            )
        )

    return sorted(recommendations, key=lambda item: item.tool_id)


def _matched(
    keys: tuple[str, ...],
    evidence: dict[str, EvidenceV2],
    strengths: set[EvidenceStrength],
) -> tuple[EvidenceV2, ...]:
    return tuple(
        evidence[key] for key in keys if key in evidence and evidence[key].strength in strengths
    )


__all__ = ["Recommendation", "recommend"]
