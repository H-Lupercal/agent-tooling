from __future__ import annotations

from collections.abc import Iterable

from toolbelt.adapters.base import InventoryRunner, JsonInventoryAdapter
from toolbelt.schemas import CapabilitySnapshot, CapabilityStatus, Provider


def combine_capabilities(
    snapshots: Iterable[CapabilitySnapshot],
) -> CapabilitySnapshot:
    collected = tuple(snapshots)
    if not collected:
        return CapabilitySnapshot(
            schema_version=2,
            provider=Provider.COMBINED,
            status=CapabilityStatus.UNKNOWN,
            errors=("no provider inventories were collected",),
        )
    errors = tuple(
        sorted(
            {
                f"{snapshot.provider.value}: {message}"
                for snapshot in collected
                for message in snapshot.errors
            }
        )
    )
    return CapabilitySnapshot(
        schema_version=2,
        provider=Provider.COMBINED,
        status=(
            CapabilityStatus.UNKNOWN
            if any(
                snapshot.status is CapabilityStatus.UNKNOWN for snapshot in collected
            )
            else CapabilityStatus.KNOWN
        ),
        native=tuple(
            sorted({item for snapshot in collected for item in snapshot.native})
        ),
        installed=tuple(
            sorted({item for snapshot in collected for item in snapshot.installed})
        ),
        managed=tuple(
            sorted({item for snapshot in collected for item in snapshot.managed})
        ),
        errors=errors,
    )


def inventory_capabilities(
    adapters: Iterable[JsonInventoryAdapter],
    *,
    runner: InventoryRunner,
) -> CapabilitySnapshot:
    return combine_capabilities(
        adapter.inventory(runner=runner) for adapter in adapters
    )


__all__ = ["combine_capabilities", "inventory_capabilities"]
