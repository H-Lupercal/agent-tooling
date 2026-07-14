from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent_harness.cli import main
from agent_harness.models import Event
from agent_harness.store import EventStore


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    *arguments: str,
) -> tuple[int, str, str]:
    monkeypatch.chdir(tmp_path)
    result = main(list(arguments))
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def _append(
    store: EventStore,
    run_id: str,
    kind: str,
    actor: str,
    payload: dict[str, object] | None = None,
) -> None:
    store.append(
        replace(
            Event.example(run_id),
            kind=kind,
            actor=actor,
            payload=payload or {},
        )
    )


def test_direct_cli_covers_init_doctor_run_show_and_export(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    code, _, _ = _invoke(monkeypatch, capsys, tmp_path, "init")
    assert code == 0
    code, stdout, _ = _invoke(monkeypatch, capsys, tmp_path, "doctor")
    assert code == 0
    assert "configuration valid" in stdout

    store = tmp_path / "state"
    code, stdout, _ = _invoke(
        monkeypatch,
        capsys,
        tmp_path,
        "--store",
        str(store),
        "run",
        "direct coverage",
        "--fake",
    )
    assert code == 0
    run_id = stdout.splitlines()[0].split("=", 1)[1]
    events = EventStore(store / "events.db").replay(run_id)
    started = [event.sequence for event in events if event.kind == "message.started"]
    completed = [event.sequence for event in events if event.kind == "message.completed"]
    assert len(started) == 2
    assert max(started) < min(completed)

    code, shown, _ = _invoke(monkeypatch, capsys, tmp_path, "--store", str(store), "show", run_id)
    assert code == 0
    assert '"kind":"run.completed"' in shown

    receipt = tmp_path / "receipt.jsonl"
    code, _, _ = _invoke(
        monkeypatch,
        capsys,
        tmp_path,
        "--store",
        str(store),
        "export",
        run_id,
        str(receipt),
    )
    assert code == 0
    assert receipt.is_file()


def test_direct_cli_covers_stable_operational_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert _invoke(monkeypatch, capsys, tmp_path, "init")[0] == 0
    code, _, stderr = _invoke(monkeypatch, capsys, tmp_path, "init")
    assert code == 3
    assert stderr.startswith("agent-harness: ")

    code, _, stderr = _invoke(monkeypatch, capsys, tmp_path, "run", "live please")
    assert code == 3
    assert "--fake" in stderr

    code, _, stderr = _invoke(monkeypatch, capsys, tmp_path, "show", "missing")
    assert code == 3
    assert "run not found" in stderr


def test_direct_cli_covers_incomplete_and_terminal_resume(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert _invoke(monkeypatch, capsys, tmp_path, "init")[0] == 0
    store_dir = tmp_path / "state"
    store = EventStore(store_dir / "events.db")
    run_id = "run-direct-resume"
    _append(store, run_id, "run.started", "user", {"goal": "recover"})
    _append(
        store,
        run_id,
        "participant.joined",
        "runtime",
        {
            "participant_id": "builder",
            "adapter": "fake",
            "model": "offline-builder",
            "roles": ["builder"],
            "context_limit": 8000,
            "parent_id": None,
        },
    )
    _append(store, run_id, "message.completed", "builder")
    _append(
        store,
        run_id,
        "participant.joined",
        "runtime",
        {
            "participant_id": "reviewer",
            "adapter": "fake",
            "model": "offline-reviewer",
            "roles": ["reviewer"],
            "context_limit": 8000,
            "parent_id": None,
        },
    )

    code, stdout, _ = _invoke(
        monkeypatch,
        capsys,
        tmp_path,
        "--store",
        str(store_dir),
        "resume",
        run_id,
        "--fake",
    )
    assert code == 0
    assert "run.resumed" in stdout

    code, _, stderr = _invoke(
        monkeypatch,
        capsys,
        tmp_path,
        "--store",
        str(store_dir),
        "resume",
        run_id,
        "--fake",
    )
    assert code == 3
    assert "already completed" in stderr
