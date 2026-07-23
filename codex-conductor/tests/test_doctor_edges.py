from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conductor import doctor


def _collector() -> tuple[list[tuple[str, str, str]], object]:
    results: list[tuple[str, str, str]] = []

    def collect(name: str, status: str, detail: str) -> None:
        results.append((name, status, detail))

    return results, collect


@pytest.mark.parametrize(
    ("payload", "settings", "detail"),
    [
        ("not-json", False, "Expecting value"),
        (json.dumps([]), False, "root must be a JSON object"),
        (json.dumps({"hooks": {}}), False, "file is not owned"),
        (
            json.dumps({"_managed_by": "codex-conductor"}),
            False,
            "file is not owned",
        ),
        (json.dumps({"hooks": []}), True, "hooks object is missing"),
    ],
)
def test_json_hook_validation_rejects_malformed_roots(
    tmp_path: Path, payload: str, settings: bool, detail: str
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(payload, encoding="utf-8")
    results, collect = _collector()

    doctor._check_json_hooks(
        collect,
        path,
        tmp_path / "hooks",
        expected=("SessionStart",),
        settings=settings,
    )

    assert results[0][:2] == (
        "settings_hooks" if settings else "hooks_json",
        "fail",
    )
    assert detail in results[0][2]


def test_json_hook_validation_reports_missing_and_correlated_events(
    tmp_path: Path,
) -> None:
    hooks_dir = tmp_path / "hooks"
    path = tmp_path / "hooks.json"
    path.write_text(
        json.dumps(
            {
                "description": "Managed by codex-conductor",
                "hooks": {
                    "SessionStart": "not-a-list",
                    "PreToolUse": [None, {"hooks": [None, {}]}],
                    "PostToolUse": [
                        {"hooks": [{"command": f"python {hooks_dir}/lifecycle.py"}]}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    results, collect = _collector()

    doctor._check_json_hooks(
        collect,
        path,
        hooks_dir,
        expected=("SessionStart", "PreToolUse", "PostToolUse"),
        settings=False,
    )

    assert results == [
        ("hooks_json", "fail", "missing events: SessionStart, PreToolUse")
    ]


def test_wrapper_and_policy_read_errors_are_hard_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    for module in ("pre_tool_use", "lifecycle", "session_start"):
        (hooks_dir / f"{module}.py").write_text(
            f"from conductor.hooks.{module} import main\n", encoding="utf-8"
        )
    policy = tmp_path / "AGENTS.md"
    policy.write_text("policy", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_selected(path: Path, *args: object, **kwargs: object) -> str:
        if path.name in {"lifecycle.py", "AGENTS.md"}:
            raise OSError(f"cannot read {path.name}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_selected)
    results, collect = _collector()

    doctor._check_wrappers(collect, hooks_dir)
    doctor._check_block(collect, policy, "start", "end", "policy_block")

    assert results[0] == ("hook_wrappers", "fail", "invalid: lifecycle.py")
    assert results[1][:2] == ("policy_block", "fail")
    assert "cannot read AGENTS.md" in results[1][2]


@pytest.mark.parametrize(
    ("completed", "minimum", "maximum", "expected_status"),
    [
        (subprocess.CompletedProcess([], 0, "codex 1.4.2", ""), "1.0", "2.0", "ok"),
        (subprocess.CompletedProcess([], 0, "codex 2.0", ""), "1.0", "2.0", "fail"),
        (subprocess.CompletedProcess([], 1, "", "bad version"), "1.0", None, "warn"),
        (subprocess.CompletedProcess([], 0, "unknown", ""), "1.0", None, "warn"),
    ],
)
def test_cli_version_check_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[str],
    minimum: str,
    maximum: str | None,
    expected_status: str,
) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _provider: "/bin/provider")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *_args, **_kwargs: completed)
    results, collect = _collector()

    doctor._check_cli_version(collect, "codex", minimum, maximum)

    assert results[0][0] == "provider_cli"
    assert results[0][1] == expected_status


def test_cli_version_check_handles_missing_executable_and_subprocess_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, collect = _collector()
    monkeypatch.setattr(doctor.shutil, "which", lambda _provider: None)
    doctor._check_cli_version(collect, "claude", "1.0", None)
    assert results == [("provider_cli", "warn", "claude executable not found")]

    monkeypatch.setattr(doctor.shutil, "which", lambda _provider: "/bin/provider")

    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("provider", 3)

    monkeypatch.setattr(doctor.subprocess, "run", fail_run)
    doctor._check_cli_version(collect, "claude", "1.0", None)
    assert results[-1][0:2] == ("provider_cli", "warn")


def test_codex_hook_runtime_rejects_stale_conductor_trust_hash(tmp_path: Path) -> None:
    from conductor.install import install

    home = tmp_path / ".codex"
    install(codex_home=home, agents_path=tmp_path / "AGENTS.md")
    config_path = home / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'trusted_hash = "sha256:',
            'trusted_hash = "sha256:stale-',
            1,
        ),
        encoding="utf-8",
    )
    results, collect = _collector()

    doctor._check_codex_hook_runtime(collect, config_path, home / "hooks.json")

    assert results[-1][0:2] == ("hook_runtime", "fail")
    assert "inactive" in results[-1][2]


def test_main_renders_json_and_human_reports(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = {
        "provider": "codex",
        "checks": [{"name": "example", "status": "ok", "detail": "ready"}],
        "notes": [],
        "ok": True,
    }
    monkeypatch.setattr(doctor, "run_checks", lambda *_args, **_kwargs: report)

    assert doctor.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report

    report["ok"] = False
    assert doctor.main([]) == 1
    assert "overall: FAIL" in capsys.readouterr().out


def test_run_checks_reports_config_and_contract_load_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_config(_path: Path) -> None:
        raise ValueError("invalid configuration")

    def fail_contract(_name: str) -> None:
        raise ValueError("invalid contract")

    monkeypatch.setattr(doctor, "load_config", fail_config)
    monkeypatch.setattr(doctor, "load_contract", fail_contract)

    report = doctor.run_checks(
        "unsupported-provider",
        home=tmp_path / ".codex",
        policy_path=tmp_path / "AGENTS.md",
    )
    statuses = {item["name"]: item for item in report["checks"]}

    assert report["provider"] == "codex"
    assert statuses["config"]["status"] == "fail"
    assert statuses["contract"]["status"] == "fail"
    assert "invalid configuration" in statuses["config"]["detail"]
    assert "invalid contract" in statuses["contract"]["detail"]


def test_run_checks_rejects_contract_mode_below_configured_minimum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conductor.install import install
    from conductor.schemas import OperatingMode

    home = tmp_path / ".codex"
    policy = tmp_path / "AGENTS.md"
    install(codex_home=home, agents_path=policy)
    monkeypatch.setattr(
        doctor, "contract_mode", lambda _contract: OperatingMode.UNSUPPORTED
    )

    report = doctor.run_checks("codex", home=home, policy_path=policy)
    statuses = {item["name"]: item["status"] for item in report["checks"]}

    assert statuses["mode"] == "fail"
    assert statuses["policy_canary"] == "ok"


def test_run_checks_reports_store_integrity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conductor.install import install

    home = tmp_path / ".codex"
    policy = tmp_path / "AGENTS.md"
    install(codex_home=home, agents_path=policy)
    database = home / "conductor" / "state" / "conductor.db"
    database.parent.mkdir(parents=True)
    database.touch()

    class BrokenStore:
        def __init__(self, _path: Path) -> None:
            pass

        def integrity_check(self) -> str:
            return "database disk image is malformed"

    monkeypatch.setattr(doctor, "Store", BrokenStore)
    report = doctor.run_checks("codex", home=home, policy_path=policy)
    store = next(item for item in report["checks"] if item["name"] == "store")

    assert store["status"] == "fail"
    assert "malformed" in store["detail"]


def test_run_checks_accepts_an_empty_healthy_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conductor.install import install

    home = tmp_path / ".codex"
    policy = tmp_path / "AGENTS.md"
    install(codex_home=home, agents_path=policy)
    database = home / "conductor" / "state" / "conductor.db"
    database.parent.mkdir(parents=True)
    database.touch()

    class EmptyStore:
        def __init__(self, _path: Path) -> None:
            pass

        def integrity_check(self) -> str:
            return "ok"

        def schema_version(self) -> int:
            return 1

        def journal_mode(self) -> str:
            return "wal"

        def latest_run_id(self) -> None:
            return None

    monkeypatch.setattr(doctor, "Store", EmptyStore)
    report = doctor.run_checks("codex", home=home, policy_path=policy)
    statuses = {item["name"]: item["status"] for item in report["checks"]}

    assert statuses["store"] == "ok"
    assert "run_context" not in statuses
