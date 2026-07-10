from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

import toolbelt.planner as planner
from toolbelt.catalog import load_catalog_v2
from toolbelt.errors import StalePlanError, ValidationError
from toolbelt.planner import (
    build_explicit_plan_v2,
    build_plan_v2,
    read_plan_v2,
    validate_plan_binding,
    write_plan_v2,
)
from toolbelt.schemas import (
    ActionOperation,
    ActionStepV2,
    CapabilitySnapshot,
    EvidenceV2,
    PlanV2,
)

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
            allow_user_scope=True,
            now=NOW,
        )
        second = build_plan_v2(
            root,
            list(reversed(items)),
            catalog,
            _capabilities(),
            allow_network=True,
            allow_user_scope=True,
            now=NOW,
        )

        assert first.model_dump_json() == second.model_dump_json()
        assert first.actions
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
        allow_user_scope=True,
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
        allow_user_scope=True,
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
        allow_user_scope=True,
        now=NOW,
    )
    tampered = PlanV2.model_validate({**plan.model_dump(mode="json"), "plan_id": "f" * 64})

    with pytest.raises(StalePlanError, match="plan digest"):
        validate_plan_binding(tampered, root, catalog, capabilities, now=NOW)


def test_planning_is_read_only(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    build_plan_v2(
        root,
        _evidence(),
        load_catalog_v2(),
        _capabilities(),
        allow_network=True,
        now=NOW,
    )
    after = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    assert after == before
    assert not (root / ".toolbelt").exists()


def test_plan_round_trip_is_canonical_and_invalid_json_is_rejected(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    plan = build_plan_v2(
        root,
        _evidence(),
        load_catalog_v2(),
        _capabilities(),
        allow_network=True,
        now=NOW,
    )
    target = write_plan_v2(plan, root / ".toolbelt" / "plan.json")

    assert read_plan_v2(target) == plan
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(Exception, match="root must be an object"):
        read_plan_v2(target)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable-bit Git drift")
def test_git_mode_drift_is_bound_even_when_file_bytes_do_not_change(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
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
    os.chmod(root / "pyproject.toml", 0o755)

    with pytest.raises(StalePlanError, match="working-tree"):
        validate_plan_binding(plan, root, catalog, capabilities, now=NOW)


def test_repository_binding_limits_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    (root / "second.txt").write_text("second", encoding="utf-8")
    monkeypatch.setattr("toolbelt.planner._MAX_BOUND_FILES", 1)

    with pytest.raises(Exception, match="file limit"):
        build_plan_v2(
            root,
            _evidence(),
            load_catalog_v2(),
            _capabilities(),
            allow_network=True,
            now=NOW,
        )


def test_explicit_plan_rejects_commands_not_exactly_in_catalog(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()
    plan = build_plan_v2(
        root,
        _evidence(),
        catalog,
        capabilities,
        allow_network=True,
        allow_user_scope=True,
        now=NOW,
    )
    action = plan.actions[0]
    tampered = action.model_copy(
        update={"steps": (ActionStepV2(argv=("python", "-c", "print('tampered')")),)}
    )

    with pytest.raises(Exception, match="command contract"):
        build_explicit_plan_v2(
            root,
            catalog,
            capabilities,
            [tampered],
            now=NOW,
        )


@pytest.mark.parametrize("ttl", (timedelta(0), timedelta(days=8)))
def test_plan_builders_reject_unsafe_ttls(tmp_path: Path, ttl: timedelta) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()

    with pytest.raises(ValidationError, match="plan TTL"):
        build_plan_v2(root, _evidence(), catalog, capabilities, now=NOW, ttl=ttl)
    with pytest.raises(ValidationError, match="plan TTL"):
        build_explicit_plan_v2(root, catalog, capabilities, (), now=NOW, ttl=ttl)


def test_plan_reader_rejects_missing_oversized_and_invalid_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ValidationError, match="plan not found"):
        read_plan_v2(missing)

    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match="ten MiB"):
        read_plan_v2(oversized)

    invalid_utf8 = tmp_path / "invalid-utf8.json"
    invalid_utf8.write_bytes(b"\xff")
    with pytest.raises(ValidationError, match="invalid plan"):
        read_plan_v2(invalid_utf8)

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(ValidationError, match="invalid plan"):
        read_plan_v2(invalid_json)


def test_plan_root_and_timestamp_validation(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    symlink = tmp_path / "link"
    try:
        symlink.symlink_to(directory, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    with pytest.raises(ValidationError, match="symbolic link"):
        planner._validated_root(symlink)
    with pytest.raises(ValidationError, match="does not exist"):
        planner._validated_root(tmp_path / "absent")
    regular = tmp_path / "file"
    regular.write_text("data", encoding="utf-8")
    with pytest.raises(ValidationError, match="must be a directory"):
        planner._validated_root(regular)
    with pytest.raises(ValidationError, match="timezone-aware"):
        planner._aware_utc(datetime(2026, 7, 9, 12, 0))


def test_explicit_action_operations_preserve_catalog_contracts(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()
    install_plan = build_plan_v2(
        root,
        _evidence(),
        catalog,
        capabilities,
        allow_network=True,
        allow_user_scope=True,
        now=NOW,
    )
    action = install_plan.actions[0]

    for operation in (ActionOperation.ADOPT, ActionOperation.VERIFY):
        readonly = action.model_copy(update={"operation": operation, "steps": (), "rollback": ()})
        assert build_explicit_plan_v2(
            root, catalog, capabilities, (readonly,), now=NOW
        ).actions == (readonly,)

    removal = action.model_copy(
        update={
            "operation": ActionOperation.REMOVE,
            "steps": action.rollback,
            "verify": (),
            "rollback": action.steps,
        }
    )
    assert build_explicit_plan_v2(root, catalog, capabilities, (removal,), now=NOW).actions == (
        removal,
    )


def test_explicit_actions_reject_missing_or_changed_security_contracts(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()
    action = build_plan_v2(
        root,
        _evidence(),
        catalog,
        capabilities,
        allow_network=True,
        allow_user_scope=True,
        now=NOW,
    ).actions[0]

    missing = action.model_copy(update={"tool_version": "999.0"})
    with pytest.raises(ValidationError, match="no exact catalog contract"):
        build_explicit_plan_v2(root, catalog, capabilities, (missing,), now=NOW)

    changed = action.model_copy(update={"permissions": ()})
    with pytest.raises(ValidationError, match="security metadata"):
        build_explicit_plan_v2(root, catalog, capabilities, (changed,), now=NOW)

    class UnsupportedOperation:
        value = "unsupported"

    unsupported = SimpleNamespace(
        id="a9999",
        tool_id=action.tool_id,
        tool_version=action.tool_version,
        install_scope=action.install_scope,
        permissions=action.permissions,
        required_env=action.required_env,
        operation=UnsupportedOperation(),
    )
    with pytest.raises(ValidationError, match="unsupported operation"):
        planner._validate_action_contracts((unsupported,), catalog)


def test_plan_binding_rejects_all_repository_binding_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    cases = (
        ({"identity": "f" * 64}, "repository identity"),
        ({"content_digest": "e" * 64}, "repository content"),
        ({"git_head": "deadbeef"}, "Git HEAD"),
        ({"dirty_digest": "d" * 64}, "working-tree"),
    )
    for update, message in cases:
        binding = plan.repository.model_copy(update=update)
        monkeypatch.setattr(
            planner,
            "_repository_binding",
            lambda _root, value=binding: value,
        )
        with pytest.raises(StalePlanError, match=message):
            validate_plan_binding(plan, root, catalog, capabilities, now=NOW)


def test_plan_binding_rejects_catalog_tools_and_action_security_drift(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    catalog = load_catalog_v2()
    capabilities = _capabilities()
    plan = build_plan_v2(
        root,
        _evidence(),
        catalog,
        capabilities,
        allow_network=True,
        allow_user_scope=True,
        now=NOW,
    )

    changed_tools = plan.model_copy(update={"catalog_tools": {}})
    changed_tools = changed_tools.model_copy(
        update={"plan_id": planner.calculate_plan_id(changed_tools)}
    )
    with pytest.raises(StalePlanError, match="catalog tool versions"):
        validate_plan_binding(changed_tools, root, catalog, capabilities, now=NOW)

    changed_action = plan.actions[0].model_copy(update={"permissions": ()})
    changed_contract = plan.model_copy(update={"actions": (changed_action,)})
    changed_contract = changed_contract.model_copy(
        update={"plan_id": planner.calculate_plan_id(changed_contract)}
    )
    with pytest.raises(StalePlanError, match="security metadata"):
        validate_plan_binding(changed_contract, root, catalog, capabilities, now=NOW)

    corrupt_catalog = replace(catalog, digest="0" * 64)
    with pytest.raises(ValidationError, match="catalog object digest"):
        validate_plan_binding(plan, root, corrupt_catalog, capabilities, now=NOW)


def test_repository_content_digest_binds_symlinks_bytes_and_file_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    target = root / "target"
    target.write_text("target", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to("target")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    first = planner._repository_content_digest(root)
    link.unlink()
    link.symlink_to("pyproject.toml")
    assert planner._repository_content_digest(root) != first

    monkeypatch.setattr(planner, "_MAX_BOUND_BYTES", 1)
    with pytest.raises(ValidationError, match="byte limit"):
        planner._repository_content_digest(root)


def test_repository_content_digest_reports_scan_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)

    def fail_scandir(_path: Path):
        raise OSError("denied")

    monkeypatch.setattr(planner.os, "scandir", fail_scandir)
    with pytest.raises(ValidationError, match="cannot read repository entry"):
        planner._repository_content_digest(root)


def test_git_binding_and_runner_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = planner._run_git_bytes
    monkeypatch.setattr(planner, "_run_git", lambda *_args: None)
    assert planner._git_binding(tmp_path) == (None, None)

    monkeypatch.setattr(planner, "_run_git", lambda *_args: b"abc\n")
    monkeypatch.setattr(planner, "_run_git_bytes", lambda *_args: None)
    assert planner._git_binding(tmp_path) == ("abc", None)

    status = b"?? .toolbelt/state.sqlite3\0?? changed.txt\0"
    monkeypatch.setattr(planner, "_run_git_bytes", lambda *_args: status)
    assert planner._git_binding(tmp_path) == (
        "abc",
        planner.sha256(b"?? changed.txt").hexdigest(),
    )

    monkeypatch.setattr(
        planner.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert runner(tmp_path, "status") is None

    monkeypatch.setattr(
        planner.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, stdout=b"bad"),
    )
    assert runner(tmp_path, "status") is None

    monkeypatch.setattr(
        planner.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=b"x" * (1024 * 1024 + 1)
        ),
    )
    assert runner(tmp_path, "status") is None

    monkeypatch.setattr(
        planner.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout=b"ok"),
    )
    assert runner(tmp_path, "status") == b"ok"
