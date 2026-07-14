from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from agent_harness.models import Event
from agent_harness.store import EventStore


def run_cli(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    source = Path(__file__).parents[1] / "src"
    environment["PYTHONPATH"] = str(source)
    return subprocess.run(
        [sys.executable, "-m", "agent_harness", *arguments],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_init_writes_safe_default_config(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "init")

    assert result.returncode == 0
    config = tmp_path / "agent-harness.toml"
    assert config.is_file()
    assert "credential" not in config.read_text(encoding="utf-8").lower()


def test_init_refuses_to_overwrite_config_with_stable_error(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(tmp_path, "init")

    assert result.returncode == 3
    assert result.stderr.startswith("agent-harness: ")
    assert "already exists" in result.stderr


def test_doctor_validates_default_config(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(tmp_path, "doctor")

    assert result.returncode == 0
    assert "configuration valid" in result.stdout


def test_run_with_fake_roster_emits_completed_run(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(
        tmp_path,
        "--store",
        str(tmp_path / "store"),
        "run",
        "prove concurrency",
        "--fake",
    )

    assert result.returncode == 0
    assert "run.completed" in result.stdout
    run_id = result.stdout.splitlines()[0].split("=", 1)[1]

    shown = run_cli(tmp_path, "--store", str(tmp_path / "store"), "show", run_id)
    assert shown.returncode == 0
    assert '"kind":"run.started"' in shown.stdout
    assert shown.stdout.index('"sequence":1') < shown.stdout.index('"sequence":2')


def test_run_without_fake_flag_is_rejected(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(tmp_path, "run", "use live providers")

    assert result.returncode == 3
    assert result.stderr.startswith("agent-harness: ")
    assert "--fake" in result.stderr


def _append_run_event(
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


def test_export_command_writes_canonical_receipt(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0
    store_dir = tmp_path / "store"
    run = run_cli(
        tmp_path,
        "--store",
        str(store_dir),
        "run",
        "export this",
        "--fake",
    )
    run_id = run.stdout.splitlines()[0].split("=", 1)[1]
    output = tmp_path / "receipt.jsonl"

    result = run_cli(
        tmp_path,
        "--store",
        str(store_dir),
        "export",
        run_id,
        str(output),
    )

    assert result.returncode == 0
    assert output.read_text(encoding="utf-8").count("\n") > 1


def test_resume_rejects_completed_run(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0
    store_dir = tmp_path / "store"
    run = run_cli(
        tmp_path,
        "--store",
        str(store_dir),
        "run",
        "finish this",
        "--fake",
    )
    run_id = run.stdout.splitlines()[0].split("=", 1)[1]

    result = run_cli(tmp_path, "--store", str(store_dir), "resume", run_id, "--fake")

    assert result.returncode == 3
    assert "already completed" in result.stderr


def test_resume_launches_only_nonterminal_fake_participants(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0
    store_dir = tmp_path / "store"
    store = EventStore(store_dir / "events.db")
    run_id = "run-incomplete"
    _append_run_event(store, run_id, "run.started", "user", {"goal": "recover"})
    _append_run_event(
        store,
        run_id,
        "participant.joined",
        "runtime",
        {"participant_id": "builder"},
    )
    _append_run_event(store, run_id, "message.completed", "builder")
    _append_run_event(
        store,
        run_id,
        "participant.joined",
        "runtime",
        {"participant_id": "reviewer"},
    )

    result = run_cli(tmp_path, "--store", str(store_dir), "resume", run_id, "--fake")

    assert result.returncode == 0
    assert "run.resumed" in result.stdout
    resumed_events = store.replay(run_id)[4:]
    assert any(
        event.kind == "message.completed" and event.actor == "reviewer" for event in resumed_events
    )
    assert not any(
        event.kind == "message.completed" and event.actor == "builder" for event in resumed_events
    )
