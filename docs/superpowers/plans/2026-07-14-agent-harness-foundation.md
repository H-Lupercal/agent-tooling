# Agent Harness Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently installable `agent-harness` package that can persist and replay a deterministic, concurrent conversation among a user-configured roster of fake heterogeneous participants, including interruption and dynamically admitted child participants.

**Architecture:** This is the first of four vertical-slice plans derived from the approved design. It establishes immutable event models, a transactional SQLite event store, an asynchronous collaboration room, adapter contracts, a deterministic fake adapter, capacity-governed child spawning, a resumable controller, a CLI, and receipts. Repository worktrees/evidence gates, live provider adapters, and the full interactive console remain separate follow-on plans so this slice is independently testable and useful.

**Tech Stack:** Python 3.11+, standard library runtime (`asyncio`, `argparse`, `dataclasses`, `sqlite3`, `tomllib`), Hatchling, uv, pytest, pytest-cov, Ruff, Pyright.

---

## Planned file structure

```text
agent-harness/
  AGENTS.md                         package execution rules
  LICENSE                           MIT license copy
  Makefile                          local quality and build commands
  README.md                         foundation CLI and trust boundaries
  pyproject.toml                    package metadata and tool configuration
  uv.lock                           locked development environment
  docs/
    architecture.md                 foundation component/data-flow reference
    tool-activity.md                human-readable Toolbelt/Conductor ledger
    tool-activity.jsonl             machine-readable activity ledger
  src/agent_harness/
    __init__.py                     package version
    __main__.py                     python -m entry point
    adapters/
      __init__.py                   adapter exports
      base.py                       participant adapter protocol and emissions
      fake.py                       deterministic scripted adapter
    cli.py                          init/doctor/run/show/export commands
    config.py                       strict TOML project configuration
    controller.py                   run lifecycle, capacity, interrupts, children
    models.py                       immutable versioned event/run schemas
    receipts.py                     portable JSONL receipt export
    room.py                         async publish/subscribe and backpressure
    store.py                        transactional SQLite event persistence
    py.typed                        typed-package marker
  tests/
    test_cli.py
    test_config.py
    test_controller.py
    test_models.py
    test_receipts.py
    test_room.py
    test_store.py
tests/test_release_contract.py      add the new package to monorepo checks
README.md                           list the new package and development commands
```

## Scope decomposition after this plan

| Plan | Working result |
|---|---|
| Foundation (this document) | Durable concurrent conversation with fake participants, interrupts, children, replay, and receipts |
| Repository and consensus | Isolated worktrees, patch proposals, deterministic gates, findings, quorum, convergence, and human escalation |
| Live adapters | OpenAI-compatible, Anthropic, Gemini, Codex CLI, Claude Code CLI, capability probes, and secret boundaries |
| Operator experience and hardening | Interactive terminal UI, chaos/recovery suite, distribution verification, and cross-platform release gates |

### Task 1: Scaffold the independent package and quality contract

**Files:**
- Create: `agent-harness/pyproject.toml`
- Create: `agent-harness/Makefile`
- Create: `agent-harness/AGENTS.md`
- Create: `agent-harness/LICENSE`
- Create: `agent-harness/README.md`
- Create: `agent-harness/src/agent_harness/__init__.py`
- Create: `agent-harness/src/agent_harness/__main__.py`
- Create: `agent-harness/src/agent_harness/py.typed`
- Create: `agent-harness/tests/test_package.py`

- [ ] **Step 1: Create the package metadata and empty import surface**

```toml
# agent-harness/pyproject.toml
[build-system]
requires = ["hatchling>=1.25,<2"]
build-backend = "hatchling.build"

[project]
name = "agent-harness"
version = "0.1.0"
description = "Provider-independent live collaboration runtime for coding agents"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = []

[project.optional-dependencies]
dev = [
  "build>=1.2,<2",
  "hatchling>=1.25,<2",
  "pyright>=1.1.400,<2",
  "pytest>=8.3,<10",
  "pytest-cov>=6,<8",
  "ruff>=0.15,<1",
]

[project.scripts]
agent-harness = "agent_harness.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/agent_harness"]

[tool.pytest.ini_options]
addopts = "--strict-markers --strict-config"
testpaths = ["tests"]

[tool.coverage.run]
branch = true
source = ["agent_harness"]

[tool.coverage.report]
fail_under = 90
show_missing = true
exclude_also = ["if __name__ == .__main__.:"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "strict"
include = ["src", "tests"]
venvPath = "."
venv = ".venv"
```

```python
# agent-harness/src/agent_harness/__init__.py
"""Live collaboration runtime for heterogeneous coding agents."""

__version__ = "0.1.0"
```

```python
# agent-harness/src/agent_harness/__main__.py
from agent_harness.cli import main

raise SystemExit(main())
```

```markdown
<!-- agent-harness/README.md -->
# Agent Harness

Agent Harness is a local-first, provider-independent collaboration runtime for coding
agents. The foundation release runs deterministic fake participants while live provider
and coding-CLI adapters are developed behind the same protocol.
```

Copy the repository MIT license to `agent-harness/LICENSE`. Create `py.typed` as an empty
marker file. Create the package directories before running uv.

- [ ] **Step 2: Write the package smoke test**

```python
# agent-harness/tests/test_package.py
from agent_harness import __version__


def test_package_version_is_initial_release() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 3: Lock and install the development environment**

Run: `cd agent-harness && uv lock && uv sync --extra dev --locked`

Expected: `uv.lock` exists and the editable package plus development dependencies install successfully.

- [ ] **Step 4: Run the smoke test**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_package.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Add package-local execution rules and quality targets**

```make
# agent-harness/Makefile
.PHONY: build check format format-check lint test typecheck

PYTHON ?= python3

format:
	$(PYTHON) -m ruff format src tests

format-check:
	$(PYTHON) -m ruff format --check src tests

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m pyright

test:
	$(PYTHON) -m pytest --cov=agent_harness --cov-branch --cov-report=term-missing --cov-fail-under=90

check: format-check lint typecheck test

build:
	$(PYTHON) -m build --no-isolation
```

`AGENTS.md` must state that runtime code is standard-library only in this foundation, tests require a demonstrated failing state before implementation, provider secrets must never enter fixtures, and the final package gates are `uv lock --check`, `make check`, and `make build`.

- [ ] **Step 6: Commit the scaffold**

```bash
git add agent-harness
git commit -m "chore: scaffold agent harness package"
```

### Task 2: Define immutable event and participant models

**Files:**
- Create: `agent-harness/src/agent_harness/models.py`
- Create: `agent-harness/tests/test_models.py`

- [ ] **Step 1: Write failing validation and serialization tests**

```python
from datetime import UTC, datetime

import pytest

from agent_harness.models import Event, Participant, event_from_json, event_to_json


def test_event_round_trip_is_canonical() -> None:
    event = Event(
        schema_version=1,
        run_id="run-1",
        sequence=1,
        occurred_at=datetime(2026, 7, 14, tzinfo=UTC),
        actor="user",
        kind="run.started",
        causation_id=None,
        correlation_id="goal-1",
        payload={"goal": "repair parser"},
    )
    assert event_from_json(event_to_json(event)) == event


def test_event_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="run ID"):
        Event.example(run_id="../escape")


def test_participant_requires_positive_context_limit() -> None:
    with pytest.raises(ValueError, match="context limit"):
        Participant("reviewer", "fake", "fake-v1", (), 0, None)
```

- [ ] **Step 2: Run the model tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_models.py -q`

Expected: FAIL with `ModuleNotFoundError: agent_harness.models`.

- [ ] **Step 3: Implement strict frozen dataclasses and canonical JSON**

```python
# agent-harness/src/agent_harness/models.py
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value) or ".." in value.split("/"):
        raise ValueError(f"{label} must be a safe identifier")
    return value


@dataclass(frozen=True)
class Participant:
    participant_id: str
    adapter: str
    model: str
    roles: tuple[str, ...]
    context_limit: int
    parent_id: str | None

    def __post_init__(self) -> None:
        _identifier(self.participant_id, "participant ID")
        if self.context_limit <= 0:
            raise ValueError("context limit must be positive")


@dataclass(frozen=True)
class Event:
    schema_version: int
    run_id: str
    sequence: int
    occurred_at: datetime
    actor: str
    kind: str
    causation_id: str | None
    correlation_id: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported event schema version")
        _identifier(self.run_id, "run ID")
        _identifier(self.actor, "actor")
        _identifier(self.kind, "event kind")
        _identifier(self.correlation_id, "correlation ID")
        if self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")

    @classmethod
    def example(cls, run_id: str) -> Event:
        return cls(1, run_id, 1, datetime.now(UTC), "user", "run.started", None, "goal", {})


def event_to_json(event: Event) -> str:
    value = asdict(event)
    value["occurred_at"] = event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def event_from_json(raw: str) -> Event:
    value = json.loads(raw)
    value["occurred_at"] = datetime.fromisoformat(value["occurred_at"].replace("Z", "+00:00"))
    return Event(**value)
```

- [ ] **Step 4: Run and pass the model tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_models.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the event contract**

```bash
git add agent-harness/src/agent_harness/models.py agent-harness/tests/test_models.py
git commit -m "feat: define harness event contract"
```

### Task 3: Persist events transactionally in SQLite

**Files:**
- Create: `agent-harness/src/agent_harness/store.py`
- Create: `agent-harness/tests/test_store.py`

- [ ] **Step 1: Write failing append, replay, and concurrency tests**

```python
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_harness.models import Event
from agent_harness.store import EventStore


def test_append_assigns_monotonic_sequences(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    first = store.append(Event.example("run-1"))
    second = store.append(Event.example("run-1"))
    assert (first.sequence, second.sequence) == (1, 2)
    assert store.replay("run-1") == [first, second]


def test_concurrent_appends_do_not_duplicate_sequences(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    with ThreadPoolExecutor(max_workers=4) as pool:
        events = list(pool.map(lambda _: store.append(Event.example("run-1")), range(20)))
    assert sorted(event.sequence for event in events) == list(range(1, 21))
```

- [ ] **Step 2: Run the store tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_store.py -q`

Expected: FAIL with `ModuleNotFoundError: agent_harness.store`.

- [ ] **Step 3: Implement transactional append and replay**

Implement `EventStore` with one SQLite connection per operation, WAL mode, `BEGIN IMMEDIATE`, a unique `(run_id, sequence)` constraint, canonical JSON payload storage, and a 5-second busy timeout. `append()` must ignore the caller's sequence, allocate `MAX(sequence)+1` inside the transaction, commit before returning, and roll back on every exception. `replay()` must order strictly by sequence and reconstruct events through `event_from_json()`.

```python
class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def append(self, event: Event) -> Event:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()[0]
            persisted = replace(event, sequence=sequence)
            connection.execute(
                "INSERT INTO events(run_id, sequence, event_json) VALUES (?, ?, ?)",
                (persisted.run_id, persisted.sequence, event_to_json(persisted)),
            )
            connection.commit()
            return persisted
```

- [ ] **Step 4: Run and pass the store tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_store.py -q`

Expected: `2 passed` with sequences 1 through 20 allocated exactly once.

- [ ] **Step 5: Commit the event store**

```bash
git add agent-harness/src/agent_harness/store.py agent-harness/tests/test_store.py
git commit -m "feat: persist harness events transactionally"
```

### Task 4: Build the asynchronous collaboration room

**Files:**
- Create: `agent-harness/src/agent_harness/room.py`
- Create: `agent-harness/tests/test_room.py`

- [ ] **Step 1: Write failing fan-out and backpressure tests**

```python
import asyncio
from pathlib import Path

from agent_harness.models import Event
from agent_harness.room import CollaborationRoom
from agent_harness.store import EventStore


def test_publish_persists_before_fan_out(tmp_path: Path) -> None:
    async def scenario() -> None:
        room = CollaborationRoom(EventStore(tmp_path / "events.db"), queue_size=2)
        first = room.subscribe("agent-a")
        second = room.subscribe("agent-b")
        persisted = await room.publish(Event.example("run-1"))
        assert (await first.get()).sequence == persisted.sequence
        assert (await second.get()).sequence == persisted.sequence

    asyncio.run(scenario())


def test_slow_consumer_applies_backpressure(tmp_path: Path) -> None:
    async def scenario() -> None:
        room = CollaborationRoom(EventStore(tmp_path / "events.db"), queue_size=1)
        queue = room.subscribe("slow")
        await room.publish(Event.example("run-1"))
        blocked = asyncio.create_task(room.publish(Event.example("run-1")))
        await asyncio.sleep(0)
        assert not blocked.done()
        await queue.get()
        await blocked

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the room tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_room.py -q`

Expected: FAIL with `ModuleNotFoundError: agent_harness.room`.

- [ ] **Step 3: Implement persist-before-publish semantics**

```python
class CollaborationRoom:
    def __init__(self, store: EventStore, queue_size: int = 100) -> None:
        if queue_size < 1:
            raise ValueError("queue size must be positive")
        self.store = store
        self.queue_size = queue_size
        self._subscribers: dict[str, asyncio.Queue[Event]] = {}

    def subscribe(self, participant_id: str) -> asyncio.Queue[Event]:
        if participant_id in self._subscribers:
            raise ValueError(f"duplicate subscriber: {participant_id}")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers[participant_id] = queue
        return queue

    async def publish(self, event: Event) -> Event:
        persisted = await asyncio.to_thread(self.store.append, event)
        for participant_id in sorted(self._subscribers):
            await self._subscribers[participant_id].put(persisted)
        return persisted
```

- [ ] **Step 4: Run and pass room tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_room.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the room**

```bash
git add agent-harness/src/agent_harness/room.py agent-harness/tests/test_room.py
git commit -m "feat: add durable collaboration room"
```

### Task 5: Define the adapter protocol and deterministic fake participant

**Files:**
- Create: `agent-harness/src/agent_harness/adapters/__init__.py`
- Create: `agent-harness/src/agent_harness/adapters/base.py`
- Create: `agent-harness/src/agent_harness/adapters/fake.py`
- Create: `agent-harness/tests/test_fake_adapter.py`

- [ ] **Step 1: Write a failing streamed-output test**

```python
import asyncio

from agent_harness.adapters.fake import FakeAdapter
from agent_harness.models import Participant


def test_fake_adapter_streams_scripted_chunks() -> None:
    async def scenario() -> None:
        participant = Participant("builder", "fake", "fake-v1", ("implementation",), 4096, None)
        adapter = FakeAdapter(participant, scripts=(("hello ", "room"),))
        emissions = [item async for item in adapter.respond("goal")]
        assert [item.kind for item in emissions] == ["message.started", "message.delta", "message.delta", "message.completed"]
        assert [item.content for item in emissions[1:3]] == ["hello ", "room"]

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the test to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_fake_adapter.py -q`

Expected: FAIL because the adapter modules do not exist.

- [ ] **Step 3: Implement the protocol and fake adapter**

```python
# adapters/base.py
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from agent_harness.models import Participant


@dataclass(frozen=True)
class Emission:
    kind: str
    content: str


class ParticipantAdapter(Protocol):
    participant: Participant

    async def respond(self, prompt: str) -> AsyncIterator[Emission]: ...

    async def interrupt(self, reason: str) -> bool: ...
```

`FakeAdapter.respond()` must consume one scripted tuple per call, emit start/delta/complete in order, optionally wait on an injected `asyncio.Event` between deltas, and emit `message.interrupted` instead of completed when `interrupt()` sets its cancellation flag. Exhausted scripts raise a stable `RuntimeError("fake adapter script exhausted")`.

- [ ] **Step 4: Run and pass adapter tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_fake_adapter.py -q`

Expected: streamed-output and interruption cases pass.

- [ ] **Step 5: Commit the adapter contract**

```bash
git add agent-harness/src/agent_harness/adapters agent-harness/tests/test_fake_adapter.py
git commit -m "feat: define participant adapter protocol"
```

### Task 6: Orchestrate concurrent speakers and evidence-backed interruption

**Files:**
- Create: `agent-harness/src/agent_harness/controller.py`
- Create: `agent-harness/tests/test_controller.py`

- [ ] **Step 1: Write failing concurrent-speaker and interruption tests**

```python
def test_controller_allows_configured_concurrent_speakers(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = controller_with_two_blocked_fake_adapters(tmp_path, max_speakers=2)
        run = asyncio.create_task(controller.run("compare implementations"))
        await controller.wait_until_responding(2)
        assert controller.responding_count == 2
        controller.release_all()
        await run

    asyncio.run(scenario())


def test_urgent_interrupt_requires_reason_and_evidence(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = controller_with_blocked_fake_adapter(tmp_path)
        with pytest.raises(ValueError, match="evidence"):
            await controller.interrupt("builder", priority="urgent", reason="disagree", evidence=None)

    asyncio.run(scenario())
```

- [ ] **Step 2: Run controller tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_controller.py -q`

Expected: FAIL with `ModuleNotFoundError: agent_harness.controller`.

- [ ] **Step 3: Implement capacity-controlled concurrent response tasks**

`RunController` owns the run ID, adapters, room, an `asyncio.Semaphore(max_simultaneous_speakers)`, participant states, and active response tasks. For each adapter, it publishes `participant.joined`, starts a response under the semaphore, translates each `Emission` into a persisted `Event`, and publishes `run.completed` after all roots finish.

`interrupt()` must publish `interrupt.requested` before calling the adapter. Urgent interruption requires non-empty evidence, and the resulting event records whether the adapter returned hard cancellation or queued soft interruption.

```python
async def interrupt(
    self,
    participant_id: str,
    *,
    priority: str,
    reason: str,
    evidence: str | None,
) -> bool:
    if priority == "urgent" and not evidence:
        raise ValueError("urgent interruption requires evidence")
    await self._publish("interrupt.requested", "user", {"target": participant_id, "priority": priority, "reason": reason, "evidence": evidence})
    hard = await self.adapters[participant_id].interrupt(reason)
    await self._publish("interrupt.applied", "runtime", {"target": participant_id, "mode": "hard" if hard else "queued"})
    return hard
```

- [ ] **Step 4: Run and pass controller tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_controller.py -q`

Expected: concurrent-speaker, event-ordering, hard-interrupt, and evidence-validation cases pass.

- [ ] **Step 5: Commit orchestration**

```bash
git add agent-harness/src/agent_harness/controller.py agent-harness/tests/test_controller.py
git commit -m "feat: orchestrate concurrent agent conversation"
```

### Task 7: Admit isolated child participants with lineage and budgets

**Files:**
- Modify: `agent-harness/src/agent_harness/models.py`
- Modify: `agent-harness/src/agent_harness/controller.py`
- Modify: `agent-harness/tests/test_controller.py`

- [ ] **Step 1: Write failing child-admission tests**

```python
def test_child_joins_with_independent_context_and_lineage(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = controller_with_parent(tmp_path, max_participants=3, max_depth=2)
        child = await controller.spawn_child(
            parent_id="builder",
            role="test-specialist",
            objective="write boundary tests",
            context=("requirement: reject empty input",),
            token_budget=1000,
        )
        assert child.parent_id == "builder"
        assert child.participant_id == "builder/test-specialist-1"
        assert controller.context_for(child.participant_id) == ("requirement: reject empty input",)

    asyncio.run(scenario())


def test_child_cannot_exceed_capacity(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = controller_with_parent(tmp_path, max_participants=1, max_depth=1)
        with pytest.raises(RuntimeError, match="participant capacity"):
            await controller.spawn_child("builder", "reviewer", "review", (), 100)

    asyncio.run(scenario())
```

- [ ] **Step 2: Run child tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_controller.py -k child -q`

Expected: FAIL because `spawn_child` and child contexts are absent.

- [ ] **Step 3: Implement child identity, context isolation, and admission**

Add frozen `CapacityPolicy(max_participants, max_dynamic_children, max_children_per_parent, max_spawn_depth, max_simultaneous_speakers)` and `ChildRequest(role, objective, context, token_budget)` models with positive-value validation. `spawn_child()` must allocate a deterministic child ordinal, reject every exceeded limit before constructing the adapter, publish requested/admitted or requested/rejected events, store only the explicitly selected context, and start the child through an injected `child_adapter_factory`.

Child token budget must be charged against a controller-owned remaining budget. A child adapter failure publishes `participant.degraded` without removing its lineage or previously persisted events.

```python
@dataclass(frozen=True)
class CapacityPolicy:
    max_participants: int
    max_dynamic_children: int
    max_children_per_parent: int
    max_spawn_depth: int
    max_simultaneous_speakers: int


@dataclass(frozen=True)
class ChildRequest:
    role: str
    objective: str
    context: tuple[str, ...]
    token_budget: int
```

- [ ] **Step 4: Run and pass child tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_controller.py -k child -q`

Expected: lineage, isolated-context, depth, per-parent, total-child, participant-capacity, and budget cases pass.

- [ ] **Step 5: Commit dynamic participation**

```bash
git add agent-harness/src/agent_harness/models.py agent-harness/src/agent_harness/controller.py agent-harness/tests/test_controller.py
git commit -m "feat: admit governed child participants"
```

### Task 8: Parse strict project configuration and expose the CLI

**Files:**
- Create: `agent-harness/src/agent_harness/config.py`
- Create: `agent-harness/src/agent_harness/cli.py`
- Create: `agent-harness/tests/test_config.py`
- Create: `agent-harness/tests/test_cli.py`

- [ ] **Step 1: Write failing config and CLI tests**

```python
def test_config_rejects_capacity_below_root_roster(tmp_path: Path) -> None:
    config = tmp_path / "agent-harness.toml"
    config.write_text('[capacity]\nmax_participants=1\n[[participants]]\nid="a"\n[[participants]]\nid="b"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="root roster"):
        load_config(config)


def test_init_writes_safe_default_config(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "init")
    assert result.returncode == 0
    assert (tmp_path / "agent-harness.toml").is_file()
    assert "credential" not in (tmp_path / "agent-harness.toml").read_text(encoding="utf-8").lower()


def test_run_with_fake_roster_emits_completed_run(tmp_path: Path) -> None:
    run_cli(tmp_path, "init")
    result = run_cli(tmp_path, "run", "prove concurrency", "--fake")
    assert result.returncode == 0
    assert "run.completed" in result.stdout
```

- [ ] **Step 2: Run config and CLI tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_config.py tests/test_cli.py -q`

Expected: FAIL because configuration and CLI modules do not exist.

- [ ] **Step 3: Implement strict TOML parsing**

`load_config()` must use `tomllib`, reject missing or unknown top-level keys, reject duplicate participant IDs, require positive capacity values, ensure `max_participants >= len(participants)`, and represent credential settings only as environment-variable names. Use frozen dataclasses rather than passing raw mappings into the controller.

```python
@dataclass(frozen=True)
class HarnessConfig:
    participants: tuple[Participant, ...]
    capacity: CapacityPolicy
    total_token_budget: int
    queue_size: int


def load_config(path: Path) -> HarnessConfig:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    _reject_unknown_keys(raw, {"participants", "capacity", "budgets", "room"}, "root")
    participants = _parse_participants(raw.get("participants"))
    capacity = _parse_capacity(raw.get("capacity"))
    if capacity.max_participants < len(participants):
        raise ValueError("participant capacity is below the configured root roster")
    return HarnessConfig(
        participants=participants,
        capacity=capacity,
        total_token_budget=_positive_integer(raw["budgets"]["tokens"], "token budget"),
        queue_size=_positive_integer(raw["room"]["queue_size"], "queue size"),
    )
```

- [ ] **Step 4: Implement init, doctor, run, and show commands**

```python
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
    return parser
```

`init` must refuse to overwrite an existing config. `doctor` returns nonzero for invalid configuration. `run` rejects a non-fake roster until a live adapter plan implements it. `show` prints canonical event JSON in sequence order. All errors use the stable `agent-harness: <message>` prefix and exit code 3.

- [ ] **Step 5: Run and pass config and CLI tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_config.py tests/test_cli.py -q`

Expected: config validation, refusal-to-overwrite, doctor, fake run, show, and stable-error tests pass.

- [ ] **Step 6: Commit configuration and CLI**

```bash
git add agent-harness/src/agent_harness/config.py agent-harness/src/agent_harness/cli.py agent-harness/tests/test_config.py agent-harness/tests/test_cli.py
git commit -m "feat: expose agent harness foundation CLI"
```

### Task 9: Export portable receipts and resume interrupted runs

**Files:**
- Create: `agent-harness/src/agent_harness/receipts.py`
- Create: `agent-harness/tests/test_receipts.py`
- Modify: `agent-harness/src/agent_harness/cli.py`
- Modify: `agent-harness/tests/test_cli.py`

- [ ] **Step 1: Write failing receipt and resume tests**

```python
def test_receipt_export_is_replayable(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    output = tmp_path / "receipt.jsonl"
    export_receipt(store, "run-1", output)
    lines = output.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2, 3]


def test_resume_rejects_completed_run(tmp_path: Path) -> None:
    result = run_completed_fixture_then_resume(tmp_path)
    assert result.returncode == 3
    assert "already completed" in result.stderr
```

- [ ] **Step 2: Run receipt tests to verify failure**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_receipts.py tests/test_cli.py -k 'receipt or resume' -q`

Expected: FAIL because receipt export and resume do not exist.

- [ ] **Step 3: Implement canonical JSONL export and run-state reconstruction**

`export_receipt()` writes to an exclusive temporary file, flushes and fsyncs, atomically replaces the destination, and includes every canonical event exactly once in sequence order. `reconstruct_run()` derives participant states and terminal run state solely from replayed events. A run is resumable only when it has `run.started` without `run.completed`, `run.failed`, or `run.aborted`.

```python
@dataclass(frozen=True)
class ReconstructedRun:
    run_id: str
    terminal: bool
    participant_states: dict[str, str]
    last_sequence: int


def export_receipt(store: EventStore, run_id: str, output: Path) -> None:
    events = store.replay(run_id)
    if not events:
        raise ValueError(f"unknown run ID: {run_id}")
    _atomic_write(output, "".join(event_to_json(event) for event in events))


def reconstruct_run(events: list[Event]) -> ReconstructedRun:
    if not events or events[0].kind != "run.started":
        raise ValueError("run history does not begin with run.started")
    terminal_kinds = {"run.completed", "run.failed", "run.aborted"}
    states = _reduce_participant_states(events)
    return ReconstructedRun(events[0].run_id, events[-1].kind in terminal_kinds, states, events[-1].sequence)
```

- [ ] **Step 4: Add `export RUN_ID OUTPUT` and `resume RUN_ID` commands**

`resume` uses reconstructed state, republishes `run.resumed`, and launches only participants that were not terminal. The foundation fake adapter resumes from scripted state stored in configuration; live provider session restoration belongs to the live-adapter plan.

- [ ] **Step 5: Run and pass receipt and resume tests**

Run: `cd agent-harness && .venv/bin/python -m pytest tests/test_receipts.py tests/test_cli.py -q`

Expected: atomic export, exact replay, incomplete-run resume, and terminal-run refusal cases pass.

- [ ] **Step 6: Commit receipts and recovery**

```bash
git add agent-harness/src/agent_harness/receipts.py agent-harness/src/agent_harness/cli.py agent-harness/tests/test_receipts.py agent-harness/tests/test_cli.py
git commit -m "feat: export and resume harness runs"
```

### Task 10: Document, track tool activity, and integrate monorepo contracts

**Files:**
- Modify: `agent-harness/README.md`
- Create: `agent-harness/docs/architecture.md`
- Create: `agent-harness/docs/tool-activity.md`
- Create: `agent-harness/docs/tool-activity.jsonl`
- Modify: `README.md`
- Modify: `tests/test_release_contract.py`

- [ ] **Step 1: Write the failing monorepo contract update**

Update `PROJECTS` to `("toolbelt", "codex-conductor", "install-rehearsal", "agent-harness")`, then add assertions that each project appears in the root README and owns a `pyproject.toml`, README, license, and Makefile. Keep release-workflow assertions limited to the two currently published packages with a separate `PUBLISHED_PROJECTS` tuple.

- [ ] **Step 2: Run the root contract to verify failure**

Run: `codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q`

Expected: FAIL because agent-harness documentation and required package files are not all present in the asserted root contract.

- [ ] **Step 3: Write package and architecture documentation**

README examples must cover `init`, `doctor`, deterministic `run --fake`, `show`, `export`, and `resume`; state that the foundation does not yet execute live providers; distinguish published messages from hidden reasoning; and document that child participants do not count as independent reviewers in the later consensus layer.

The architecture document must show the Run Controller, Collaboration Room, Event Store, fake adapter, child admission, and receipt flow with the SQLite database as the source of truth.

- [ ] **Step 4: Record Toolbelt and Conductor activity without code attribution**

Seed the ledgers with the commands actually executed during planning:

```json
{"actor":"toolbelt","operation":"scan","evidence_command":"toolbelt scan --path . --json","affected_paths":[],"outputs":{"files_scanned":221,"wrote_files":false}}
{"actor":"toolbelt","operation":"discover","evidence_command":"toolbelt discover --path . --json","affected_paths":[],"outputs":{"observed_tools":["ruff","pyright"],"managed_tools":[]}}
{"actor":"toolbelt","operation":"doctor","evidence_command":"toolbelt doctor --path . --json","affected_paths":[],"outputs":{"ready":true,"warning":"no v2 declaration exists"}}
{"actor":"conductor","operation":"status","evidence_command":"conductor status --last --pretty","affected_paths":[],"outputs":{"mode":"admission","pricing_verified":false,"run_id":"019f5538-c3c6-7021-b0dd-87e383790d8f"}}
```

The Markdown ledger must say: “No code authorship attributed to Toolbelt or Conductor.” Append subsequent commands and outcomes as implementation proceeds.

- [ ] **Step 5: Run package and monorepo verification**

Run:

```bash
cd agent-harness
uv lock --check
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
cd ..
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: Ruff formatting/lint pass, Pyright reports zero errors, all package tests pass with at least 90% branch coverage, wheel and sdist build, and the root release contract passes.

- [ ] **Step 6: Run Toolbelt readiness evidence for the new package**

Run:

```bash
toolbelt scan --path agent-harness --json
toolbelt discover --path agent-harness --json
toolbelt doctor --path agent-harness --json
```

Expected: Toolbelt scans the package and reports its detected tools. Do not mutate Toolbelt declarations unless a separate reviewed plan explicitly authorizes adoption.

- [ ] **Step 7: Record the final Conductor report**

Run: `PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last`

Expected: a real run report or the controlled state explaining that no governed tasks were admitted. Copy the exact result into the final handoff and activity ledger; do not invent savings.

- [ ] **Step 8: Commit documentation and monorepo integration**

```bash
git add agent-harness README.md tests/test_release_contract.py
git commit -m "docs: integrate agent harness foundation"
```

## Foundation completion gate

The foundation plan is complete only when:

1. `agent-harness run --fake` demonstrates overlapping persisted message streams.
2. An evidence-backed hard interruption preserves a partial message.
3. A parent spawns a separately identified child with selected context and bounded budget.
4. SQLite replay reconstructs the same canonical event order after process restart.
5. A portable JSONL receipt contains every event exactly once.
6. Root and package quality gates pass with fresh evidence.
7. Toolbelt and Conductor activity is recorded without false code attribution.
