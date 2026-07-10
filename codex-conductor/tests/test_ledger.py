from __future__ import annotations

from pathlib import Path


def test_v1_event_ledger_is_not_part_of_the_runtime_contract(tmp_path: Path) -> None:
    import conductor.ledger as ledger
    from conductor.store import Store

    store = Store(tmp_path / "conductor.db")

    assert "legacy_events" not in store.table_names()
    assert not hasattr(ledger, "append_event")
    assert not hasattr(ledger, "read_events")
    assert not hasattr(store, "append_legacy_event")
