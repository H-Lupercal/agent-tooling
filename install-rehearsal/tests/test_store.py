from pathlib import Path

import pytest

from install_rehearsal.models import Receipt
from install_rehearsal.store import ReceiptStore


def test_write_then_load_receipt(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    receipt = Receipt.example(run_id="run-1")

    store.write(receipt)

    assert store.load("run-1") == receipt
    assert store.latest().run_id == "run-1"


def test_recovery_marker_lists_and_clears_abandoned_profile(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "store")
    profile = tmp_path / "profile"

    store.mark_active("run-2", profile)
    assert store.abandoned_profiles() == {"run-2": profile}
    store.clear_active("run-2")
    assert store.abandoned_profiles() == {}


def test_store_rejects_unsafe_run_ids(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)

    with pytest.raises(ValueError, match="run ID"):
        store.load("../escape")
