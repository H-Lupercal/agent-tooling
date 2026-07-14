"""Command-line entry point for offline foundation runs."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from agent_harness.adapters.fake import FakeAdapter
from agent_harness.config import HarnessConfig, load_config
from agent_harness.controller import RunController
from agent_harness.models import event_to_json
from agent_harness.receipts import export_receipt, reconstruct_run
from agent_harness.room import CollaborationRoom
from agent_harness.store import EventStore

_CONFIG_NAME = "agent-harness.toml"
_DEFAULT_CONFIG = """[capacity]
max_participants = 6
max_dynamic_children = 4
max_children_per_parent = 2
max_spawn_depth = 2
max_simultaneous_speakers = 2

[budgets]
tokens = 12000

[room]
queue_size = 100

[[participants]]
id = "builder"
adapter = "fake"
model = "offline-builder"
roles = ["builder"]
context_limit = 8000

[[participants]]
id = "reviewer"
adapter = "fake"
model = "offline-reviewer"
roles = ["reviewer"]
context_limit = 8000
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-harness")
    parser.add_argument("--store", type=Path, default=Path.home() / ".agent-harness")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="write a safe project configuration")
    commands.add_parser("doctor", help="validate project configuration and capabilities")
    run = commands.add_parser("run", help="start a collaboration run")
    run.add_argument("goal")
    run.add_argument("--fake", action="store_true", help="use deterministic offline participants")
    show = commands.add_parser("show", help="show persisted events")
    show.add_argument("run_id")
    export = commands.add_parser("export", help="export a portable JSONL receipt")
    export.add_argument("run_id")
    export.add_argument("output", type=Path)
    resume = commands.add_parser("resume", help="resume a nonterminal collaboration run")
    resume.add_argument("run_id")
    resume.add_argument(
        "--fake",
        action="store_true",
        help="use deterministic offline participants",
    )
    return parser


def _config_path() -> Path:
    return Path.cwd() / _CONFIG_NAME


def _init() -> None:
    path = _config_path()
    if path.exists():
        raise ValueError(f"{path.name} already exists")
    path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    print(f"wrote {path}")


def _doctor() -> None:
    config = load_config(_config_path())
    print(f"configuration valid: {len(config.participants)} participants")


def _fake_adapters(config: HarnessConfig) -> dict[str, FakeAdapter]:
    adapters: dict[str, FakeAdapter] = {}
    for participant in config.participants:
        if participant.adapter != "fake":
            raise ValueError("--fake requires every configured adapter to be fake")
        role = participant.roles[0]
        adapters[participant.participant_id] = FakeAdapter(
            participant,
            scripts=((f"{role} response from {participant.participant_id}",),),
        )
    return adapters


async def _run(store_path: Path, goal: str, fake: bool) -> None:
    if not fake:
        raise ValueError("live providers are not implemented; pass --fake")
    config = load_config(_config_path())
    run_id = f"run-{uuid.uuid4().hex}"
    store = EventStore(store_path / "events.db")
    controller = RunController(
        run_id=run_id,
        adapters=_fake_adapters(config),
        room=CollaborationRoom(store, queue_size=config.queue_size),
        max_simultaneous_speakers=config.capacity.max_simultaneous_speakers,
        capacity=config.capacity,
        total_token_budget=config.total_token_budget,
    )
    await controller.run(goal)
    print(f"run_id={run_id}")
    for event in store.replay(run_id):
        print(event.kind)


async def _resume(store_path: Path, run_id: str, fake: bool) -> None:
    if not fake:
        raise ValueError("live providers are not implemented; pass --fake")
    store = EventStore(store_path / "events.db")
    events = store.replay(run_id)
    reconstructed = reconstruct_run(events)
    if reconstructed.terminal:
        terminal_kind = next(
            event.kind for event in reversed(events) if event.kind.startswith("run.")
        )
        terminal_label = terminal_kind.removeprefix("run.")
        raise ValueError(f"run is already {terminal_label}")
    goal_value = events[0].payload.get("goal")
    if not isinstance(goal_value, str) or not goal_value:
        raise ValueError("run.started event does not contain a goal")
    config = load_config(_config_path())
    adapters = {
        participant_id: adapter
        for participant_id, adapter in _fake_adapters(config).items()
        if reconstructed.participant_states.get(participant_id) != "terminal"
    }
    controller = RunController(
        run_id=run_id,
        adapters=adapters,
        room=CollaborationRoom(store, queue_size=config.queue_size),
        max_simultaneous_speakers=config.capacity.max_simultaneous_speakers,
        capacity=config.capacity,
        total_token_budget=config.total_token_budget,
    )
    await controller.resume(goal_value)
    print(f"run_id={run_id}")
    for event in store.replay(run_id):
        if event.sequence > reconstructed.last_sequence:
            print(event.kind)


def _show(store_path: Path, run_id: str) -> None:
    store = EventStore(store_path / "events.db")
    events = store.replay(run_id)
    if not events:
        raise ValueError(f"run not found: {run_id}")
    for event in events:
        sys.stdout.write(event_to_json(event))


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "init":
            _init()
        elif arguments.command == "doctor":
            _doctor()
        elif arguments.command == "run":
            asyncio.run(_run(arguments.store, arguments.goal, arguments.fake))
        elif arguments.command == "show":
            _show(arguments.store, arguments.run_id)
        elif arguments.command == "export":
            export_receipt(
                EventStore(arguments.store / "events.db"),
                arguments.run_id,
                arguments.output,
            )
            print(f"exported {arguments.run_id} to {arguments.output}")
        elif arguments.command == "resume":
            asyncio.run(_resume(arguments.store, arguments.run_id, arguments.fake))
        else:
            raise AssertionError(f"unhandled command: {arguments.command}")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"agent-harness: {exc}", file=sys.stderr)
        return 3
    return 0
