from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_executor_v2 import NOW, _fixture
from toolbelt.doctor import doctor_report, inspect_state, status_report
from toolbelt.errors import ValidationError
from toolbelt.executor import Executor
from toolbelt.schemas import CapabilitySnapshot


def test_distribution_doctor_is_strict_ready_without_project() -> None:
    report = doctor_report(strict=True)

    assert report["ready"] is True
    assert report["distribution"]["catalog_loaded"] is True
    assert report["project"] is None


def test_project_warnings_are_truthful_and_strictly_enforced(tmp_path: Path) -> None:
    capabilities = CapabilitySnapshot(
        provider="combined",
        status="unknown",
        errors=("inventory unavailable",),
    )

    normal = doctor_report(root=tmp_path, capabilities=capabilities)
    strict = doctor_report(root=tmp_path, capabilities=capabilities, strict=True)

    assert normal["ready"] is True
    assert strict["ready"] is False
    failed_codes = {check["code"] for check in strict["checks"] if not check["ok"]}
    assert failed_codes >= {"DECLARATION", "CAPABILITY_INVENTORY"}
    assert not (tmp_path / ".toolbelt").exists()


def test_managed_project_doctor_and_status_validate_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, catalog, capabilities, _, _ = _fixture(tmp_path)
    monkeypatch.setenv("TOOLBELT_CATALOG", catalog.source)
    result = Executor().apply(plan, tmp_path, catalog, capabilities, now=NOW)
    assert result.state == "succeeded"

    report = doctor_report(root=tmp_path, capabilities=capabilities, strict=True)
    status = status_report(tmp_path)

    assert report["ready"] is True
    assert report["project"]["state"]["integrity"] == "ok"
    assert status["state"]["transaction_count"] == 1
    assert status["declaration"]["tools"][0]["tool_id"] == "fixture"


def test_corrupt_state_is_rejected(tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite3"
    state.write_bytes(b"not sqlite")

    with pytest.raises(ValidationError, match="cannot inspect"):
        inspect_state(state)
