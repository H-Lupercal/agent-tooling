from dataclasses import replace

import pytest

from install_rehearsal.models import FileDelta, Receipt, receipt_from_dict, receipt_to_dict, receipt_to_json


def test_receipt_json_is_canonical_and_round_trips() -> None:
    receipt = Receipt.example(run_id="run-1")

    first = receipt_to_json(receipt)
    second = receipt_to_json(receipt)

    assert first == second
    assert first.endswith("\n")
    assert '"trust_label":"REHEARSAL_NOT_SANDBOXED"' in first
    assert receipt_from_dict(receipt_to_dict(receipt)) == receipt


@pytest.mark.parametrize("path", ["/etc/passwd", "../escape", "dir\\windows"])
def test_file_delta_rejects_non_relative_posix_paths(path: str) -> None:
    with pytest.raises(ValueError, match="relative POSIX"):
        FileDelta(path=path, change="created", before=None, after=None)


def test_receipt_rejects_changed_trust_label() -> None:
    with pytest.raises(ValueError, match="trust label"):
        replace(Receipt.example(run_id="run-1"), trust_label="sandboxed")  # type: ignore[arg-type]

