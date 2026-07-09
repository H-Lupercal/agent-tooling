from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, strategies as st

from toolbelt.catalog import load_catalog_v2
from toolbelt.errors import StalePlanError
from toolbelt.planner import build_plan_v2, validate_plan_binding
from toolbelt.schemas import CapabilitySnapshot, EvidenceV2, PlanV2


NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _capabilities(*, installed: tuple[str, ...] = ()) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        provider="combined",
        status="known",
        installed=installed,
    )


def _evidence(source: str = "pyproject.toml") -> list[EvidenceV2]:
    return [
        EvidenceV2(
            type="test",
            key="pytest",
            detail="pytest dependency",
            source=source,
            strength="strong",
        ),
        EvidenceV2(
            type="lang",
            key="python",
            detail="Python source",
            source=source,
            strength="weak",
        ),
    ]


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=['pytest']\n",
        encoding="utf-8",
    )
    return tmp_path


@given(items=st.permutations(_evidence()))
def test_plan_is_order_independent(items: list[EvidenceV2]) -> None:
    with TemporaryDirectory() as directory:
        root = _repo(Path(directory))
        catalog = load_catalog_v2()
        first = build_plan_v2(
            root,
            list(items),
            catalog,
            _capabilities(),
            allow_network=True,
            now=NOW,
        )
        second = build_plan_v2(
            root,
            list(reversed(items)),
            catalog,
            _capabilities(),
            allow_network=True,
            now=NOW,
        )

        assert first.model_dump_json() == second.model_dump_json()
        assert first.plan_id != "0" * 64
        assert all(action.steps and action.verify and action.rollback for action in first.actions)


def test_changed_repository_rejects_plan(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()
    plan = build_plan_v2(
        root,
        _evidence(),
        catalog,
        capabilities,
        allow_network=True,
        now=NOW,
    )
    (root / "pyproject.toml").write_text("[project]\nname='changed'\n", encoding="utf-8")

    with pytest.raises(StalePlanError, match="repository content"):
        validate_plan_binding(plan, root, catalog, capabilities, now=NOW)


def test_changed_capabilities_and_expiry_reject_plan(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    plan = build_plan_v2(
        root,
        _evidence(),
        catalog,
        _capabilities(),
        allow_network=True,
        now=NOW,
        ttl=timedelta(minutes=5),
    )

    with pytest.raises(StalePlanError, match="capability"):
        validate_plan_binding(
            plan,
            root,
            catalog,
            _capabilities(installed=("ruff",)),
            now=NOW,
        )
    with pytest.raises(StalePlanError, match="expired"):
        validate_plan_binding(
            plan,
            root,
            catalog,
            _capabilities(),
            now=NOW + timedelta(minutes=6),
        )


def test_tampered_plan_id_is_rejected(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()
    plan = build_plan_v2(
        root,
        _evidence(),
        catalog,
        capabilities,
        allow_network=True,
        now=NOW,
    )
    tampered = PlanV2.model_validate(
        {**plan.model_dump(mode="json"), "plan_id": "f" * 64}
    )

    with pytest.raises(StalePlanError, match="plan digest"):
        validate_plan_binding(tampered, root, catalog, capabilities, now=NOW)


def test_planning_is_read_only(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    build_plan_v2(
        root,
        _evidence(),
        load_catalog_v2(),
        _capabilities(),
        allow_network=True,
        now=NOW,
    )
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    assert after == before
    assert not (root / ".toolbelt").exists()
