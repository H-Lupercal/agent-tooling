import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import install_rehearsal.cli as cli_module
from install_rehearsal.cli import main
from install_rehearsal.models import (
    FileDelta,
    FileState,
    Receipt,
    RunResult,
    receipt_to_dict,
)
from install_rehearsal.store import ReceiptStore


def test_run_creates_receipt_and_json_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile_installer.py"

    code = main(
        [
            "--store",
            str(tmp_path / "store"),
            "run",
            "--json",
            "--",
            sys.executable,
            str(fixture),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["trust_label"] == "REHEARSAL_NOT_SANDBOXED"
    assert any(item["path"].endswith("example/config.toml") for item in payload["filesystem_delta"])
    assert ReceiptStore(tmp_path / "store").latest().run_id == payload["run_id"]


def test_run_preserves_caller_working_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile_installer.py"
    relative_fixture = tmp_path / "fixture.py"
    relative_fixture.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--store",
            str(tmp_path / "store"),
            "run",
            "--json",
            "--",
            sys.executable,
            relative_fixture.name,
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["run"]["exit_code"] == 0


def test_show_latest_renders_trust_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ReceiptStore(tmp_path)
    store.write(Receipt.example(run_id="run-1"))

    assert main(["--store", str(tmp_path), "show", "latest"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("REHEARSAL_NOT_SANDBOXED\n")
    assert "Run: run-1" in output


def test_compare_detects_semantic_delta(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = ReceiptStore(tmp_path)
    first_receipt = Receipt.example(run_id="run-1")
    created = FileState(
        kind="file",
        size=1,
        sha256="0" * 64,
        mode=None,
        symlink_target=None,
    )
    second_receipt = replace(
        first_receipt,
        run_id="run-2",
        filesystem_delta=(FileDelta("new.txt", "created", None, created),),
    )
    store.write(first_receipt)
    store.write(second_receipt)

    assert main(["--store", str(tmp_path), "compare", "run-1", "run-2"]) == 1
    assert "created in second" in capsys.readouterr().out


def test_compare_ignores_identity_and_timestamp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ReceiptStore(tmp_path)
    first = Receipt.example(run_id="run-1")
    second = replace(first, run_id="run-2", started_at="2026-07-13T00:00:00Z")
    store.write(first)
    store.write(second)

    assert main(["--store", str(tmp_path), "compare", "run-1", "run-2"]) == 0
    assert "No semantic differences" in capsys.readouterr().out


def test_show_json_and_missing_receipt_exit_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ReceiptStore(tmp_path).write(Receipt.example(run_id="run-1"))
    assert main(["--store", str(tmp_path), "show", "run-1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == "run-1"

    assert main(["--store", str(tmp_path), "show", "missing"]) == 3
    assert "No such file" in capsys.readouterr().err


def test_executable_digest_is_captured_before_launch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "installer"
    executable.write_bytes(b"before")
    expected = __import__("hashlib").sha256(b"before").hexdigest()

    def replacing_run(*_args: object, **_kwargs: object) -> RunResult:
        executable.write_bytes(b"after")
        return Receipt.example("example").run

    monkeypatch.setattr(cli_module, "run_command", replacing_run)
    code = main(["--store", str(tmp_path / "store"), "run", "--json", "--", str(executable)])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["executable_sha256"] == expected


def test_cleanup_failure_preserves_installer_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile_installer.py"

    def failing_run(*_args: object, **_kwargs: object) -> RunResult:
        return replace(Receipt.example("example").run, exit_code=7)

    def failing_cleanup(_path: Path) -> None:
        raise OSError("cleanup blocked")

    monkeypatch.setattr(cli_module, "run_command", failing_run)
    monkeypatch.setattr(cli_module.shutil, "rmtree", failing_cleanup)

    code = main(["--store", str(tmp_path / "store"), "run", "--", sys.executable, str(fixture)])

    assert code == 10
    assert "cleanup blocked" in capsys.readouterr().err


def test_recover_lists_and_cleans_abandoned_profiles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "store"
    store = ReceiptStore(store_path)
    profile = store_path / "profiles" / "run-1-abandoned"
    profile.mkdir(parents=True)
    store.mark_active("run-1", profile)

    assert main(["--store", str(store_path), "recover"]) == 0
    assert "run-1" in capsys.readouterr().out
    assert main(["--store", str(store_path), "recover", "run-1", "--clean"]) == 0
    assert not profile.exists()
    assert store.abandoned_profiles() == {}


def test_recover_refuses_profiles_root_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "store"
    store = ReceiptStore(store_path)
    profiles_root = store_path / "profiles"
    unrelated = profiles_root / "unrelated-profile"
    unrelated.mkdir(parents=True)
    store.mark_active("run-1", profiles_root)

    assert main(["--store", str(store_path), "recover", "run-1", "--clean"]) == 3
    assert profiles_root.is_dir()
    assert unrelated.is_dir()
    assert "direct child" in capsys.readouterr().err


def test_corrupt_receipt_returns_tool_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "broken.json").write_text("[]", encoding="utf-8")

    assert main(["--store", str(tmp_path), "show", "broken"]) == 3
    assert "install-rehearsal:" in capsys.readouterr().err


def test_corrupt_numeric_receipt_returns_tool_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt = receipt_to_dict(Receipt.example("broken"))
    run = receipt["run"]
    assert isinstance(run, dict)
    run["duration_seconds"] = float("inf")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "broken.json").write_text(json.dumps(receipt), encoding="utf-8")

    assert main(["--store", str(tmp_path), "show", "broken"]) == 3
    assert "install-rehearsal:" in capsys.readouterr().err
