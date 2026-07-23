# Lossless Agent Context Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `agent-relay`, a strict, auditable CLI that captures the latest or a selected Claude Code/Codex conversation as an immutable raw-byte capsule and starts a new provider session without model-authored summarization or silent truncation.

**Architecture:** A standard-library-only Python package separates provider discovery, append-safe raw capture, immutable capsule storage, deterministic replay, destination capability checks, and process launch. Provider adapters preserve authoritative source bytes and expose normalized indexes; launch receipts distinguish direct transport, reference-only availability, unknown capacity, and unobservable provider-side loading.

**Tech Stack:** Python 3.11+, `argparse`, frozen dataclasses, `tomllib`, `hashlib`, atomic filesystem operations, subprocesses with `shell=False`, pytest, Ruff, Pyright, Hatchling, uv, GitHub Actions.

**Approved design:** `docs/superpowers/specs/2026-07-22-lossless-agent-context-relay-design.md`

---

## File map

### Package and public surface

- `agent-relay/pyproject.toml`: distribution metadata, strict quality configuration, `agent-relay` entry point.
- `agent-relay/Makefile`: format, lint, typecheck, coverage, build, distribution, and end-to-end gates.
- `agent-relay/AGENTS.md`: package-local execution and verification contract.
- `agent-relay/README.md`: user workflow, fidelity boundary, commands, security notes.
- `agent-relay/CHANGELOG.md`: initial unreleased feature record.
- `agent-relay/LICENSE`: package copy of the root MIT license.
- `agent-relay/uv.lock`: reproducible development environment.
- `agent-relay/src/agent_relay/__init__.py`: version and supported schema constants.
- `agent-relay/src/agent_relay/__main__.py`: `python -m agent_relay` entry point.
- `agent-relay/src/agent_relay/cli.py`: argument parsing and command dispatch only.
- `agent-relay/src/agent_relay/reporting.py`: stable human and versioned JSON output.

### Domain and safety

- `agent-relay/src/agent_relay/errors.py`: stable exit codes and typed operational errors.
- `agent-relay/src/agent_relay/models.py`: immutable provider, session, event, manifest, fidelity, transport, and receipt contracts.
- `agent-relay/src/agent_relay/config.py`: platform storage roots and strict size/locking defaults.
- `agent-relay/src/agent_relay/safe_files.py`: symlink-safe paths, owner-only permissions, atomic writes, and project locks.
- `agent-relay/src/agent_relay/sensitive.py`: deterministic secret-shaped finding scanner.

### Discovery and capture

- `agent-relay/src/agent_relay/providers/base.py`: source-adapter protocol and registry contracts.
- `agent-relay/src/agent_relay/providers/codex.py`: Codex JSONL discovery, metadata, record framing, active-view classification.
- `agent-relay/src/agent_relay/providers/claude.py`: Claude JSONL discovery, sidechain graph, compaction classification.
- `agent-relay/src/agent_relay/selection.py`: repository identity, filtering, latest ordering, ambiguity handling.
- `agent-relay/src/agent_relay/capture.py`: fixed record boundaries, stable raw snapshots, normalized indexes, attachment closure.
- `agent-relay/src/agent_relay/repository.py`: read-only Git snapshot and optional diff capture.
- `agent-relay/src/agent_relay/capsules.py`: immutable publication, canonical manifest, digest verification, latest pointer.

### Replay, launch, and operations

- `agent-relay/src/agent_relay/replay.py`: deterministic primary/active/archive replay serialization.
- `agent-relay/src/agent_relay/destinations/base.py`: destination capability and capacity protocol.
- `agent-relay/src/agent_relay/destinations/codex.py`: tested Codex CLI capability matrix and argv/stdin construction.
- `agent-relay/src/agent_relay/destinations/claude.py`: tested Claude CLI capability matrix and argv/stdin construction.
- `agent-relay/src/agent_relay/launch.py`: preflight, sensitive acknowledgements, process lifecycle, replay cleanup, receipts.
- `agent-relay/src/agent_relay/skills.py`: transactional provider-skill install and uninstall.
- `agent-relay/src/agent_relay/doctor.py`: read-only capability and storage diagnostics.
- `agent-relay/src/agent_relay/cleanup.py`: preview-first capsule and stale-launch garbage collection.

### Tests and fixtures

- `agent-relay/tests/fixtures/codex/*.jsonl`: byte-stable Codex root, child, malformed, compacted, and appended sessions.
- `agent-relay/tests/fixtures/claude/*.jsonl`: byte-stable Claude root, sidechain, summary, malformed, and appended sessions.
- `agent-relay/tests/fixtures/bin/fake-codex`: deterministic destination process fixture.
- `agent-relay/tests/fixtures/bin/fake-claude`: deterministic destination process fixture.
- `agent-relay/tests/conftest.py`: shared fixture-root and fixed-clock fixtures.
- `agent-relay/tests/helpers.py`: typed factories extended by the task that introduces each domain object.
- `agent-relay/tests/test_models.py`
- `agent-relay/tests/test_config.py`
- `agent-relay/tests/test_safe_files.py`
- `agent-relay/tests/test_selection.py`
- `agent-relay/tests/test_provider_codex.py`
- `agent-relay/tests/test_provider_claude.py`
- `agent-relay/tests/test_capture.py`
- `agent-relay/tests/test_capsules.py`
- `agent-relay/tests/test_repository.py`
- `agent-relay/tests/test_sensitive.py`
- `agent-relay/tests/test_replay.py`
- `agent-relay/tests/test_destinations.py`
- `agent-relay/tests/test_launch.py`
- `agent-relay/tests/test_skills.py`
- `agent-relay/tests/test_doctor_cleanup.py`
- `agent-relay/tests/test_cli.py`
- `agent-relay/tests/test_distribution.py`
- `agent-relay/tests/e2e_smoke.sh`
- `agent-relay/scripts/finalize_sbom.py`: stamp the installed distribution version in reproducible SBOM output.

### Monorepo integration

- `README.md`: fifth project, installation, development, and license links.
- `CONTRIBUTING.md`: `agent-relay` development gate.
- `AGENTS.md`: independent-package scope and verification commands.
- `tests/test_release_contract.py`: package ownership and CI coverage.
- `.github/workflows/ci.yml`: quality, platform tests, coverage, distribution, end-to-end, and supply-chain matrices.

## Conductor execution contract

Before every delegated implementation task:

```sh
conductor status --last --pretty
```

Append a task-specific envelope to the native spawn `task_name`:

```text
<HOOK_CONTEXT><CONDUCTOR_TASK>{"schema_version":1,"task_name":"codex_adapter","task_class":"implementation","risk_triggers":[],"owned_paths":["agent-relay/src/agent_relay/providers/codex.py","agent-relay/tests/test_provider_codex.py","agent-relay/tests/fixtures/codex"],"acceptance_checks":["agent-relay/.venv/bin/python -m pytest agent-relay/tests/test_provider_codex.py -q"],"new_task":true}</CONDUCTOR_TASK></HOOK_CONTEXT>
```

Use `fork_turns="none"` plus explicit `model` and `reasoning_effort` for override
spawns. Keep Tasks 1-3, 6-7, 9-11, 13, 17, and 18 on the frontier orchestrator
because they establish contracts, integrity, security, launch behavior, or
cross-package integration. After Task 3:

- Task 4 may use `gpt-5.6-terra`, high effort, task name `terra_high_codex_adapter`.
- Task 5 may use `gpt-5.6-terra`, high effort, task name `terra_high_claude_adapter`.
- Task 8 may use `gpt-5.6-terra`, medium effort, task name `terra_medium_repo_sensitive`.
- Task 14 may use `gpt-5.6-terra`, medium effort, task name `terra_medium_doctor_cleanup`.
- Task 15 may use `gpt-5.6-terra`, medium effort, task name `terra_medium_skills`.
- Task 16 may use `gpt-5.6-terra`, medium effort, task name `terra_medium_docs_distribution`.

Every worker owns only the listed files, runs its acceptance command, and does not revert unrelated changes. The orchestrator reviews and integrates each result. At the end of every execution run:

```sh
PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last
```

## Specification coverage map

| Specification area | Implemented and verified by |
| --- | --- |
| Latest and selected session UX | Tasks 3-5, 12-13 |
| Repository scoping and moved repositories | Tasks 3, 8, 12 |
| Raw-byte authority and stable snapshots | Tasks 4-7 |
| Session graph and auxiliary subagents | Tasks 4-6, 9 |
| Archival versus active-view replay | Tasks 4-5, 9 |
| Immutable storage, digests, locks, permissions | Tasks 3, 6-7 |
| Git state and optional diff | Task 8 |
| Sensitive-data launch blocking | Tasks 8, 11, 13 |
| Destination capability and capacity rules | Tasks 10-11, 13 |
| Launch receipts and cleanup | Tasks 11, 14 |
| Versioned CLI, JSON, and exit codes | Tasks 2, 12-14 |
| Transactional skills | Task 15 |
| Distribution, documentation, and no-daemon boundary | Tasks 1, 16 |
| Cross-platform CI and monorepo governance | Task 17 |
| Fidelity/security regression audit | Task 18 |

## Test-support ownership

`tests/conftest.py` provides only the repository-wide `fixtures` path and fixed UTC
clock. `tests/helpers.py` is extended in the same commit as the task that first
uses each helper:

| Task | Helpers added |
| --- | --- |
| 3 | `summary()` |
| 7 | `staged_capsule()`, `published_capsule()` |
| 8 | `git_repo` fixture |
| 9 | `capsule` fixture with primary and auxiliary streams |
| 11 | `LaunchContext` fixture, `RecordingRunner`, `successful_runner()` |
| 12 | `missing_sessions()` and typed in-memory service fakes |
| 13 | `service_bundle()` with event recording and capacity selection |
| 14 | `snapshot_tree()`, `config_for()`, `old_capsule_with_live_receipt()` |
| 16 | `build_wheel()`, `wheel_names()` |

Each helper returns the concrete domain type introduced by the owning task and
uses only temporary paths, fixed clocks, and sanitized fixture bytes. Helpers are
test-only and never imported by `src/agent_relay`.

---

### Task 1: Establish the independent package and monorepo contract

**Files:**
- Create: `agent-relay/pyproject.toml`
- Create: `agent-relay/Makefile`
- Create: `agent-relay/AGENTS.md`
- Create: `agent-relay/README.md`
- Create: `agent-relay/CHANGELOG.md`
- Create: `agent-relay/LICENSE`
- Create: `agent-relay/src/agent_relay/__init__.py`
- Create: `agent-relay/src/agent_relay/__main__.py`
- Create: `agent-relay/src/agent_relay/cli.py`
- Create: `agent-relay/tests/test_package.py`
- Modify: `README.md`
- Modify: `tests/test_release_contract.py`

- [ ] **Step 1: Extend the root contract with the fifth package**

Change the constants and add a package-isolation assertion:

```python
PROJECTS = (
    "toolbelt",
    "codex-conductor",
    "install-rehearsal",
    "agent-harness",
    "agent-relay",
)


def test_agent_relay_is_an_independent_distribution() -> None:
    pyproject = tomllib.loads((ROOT / "agent-relay" / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == "agent-relay"
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["project"]["scripts"]["agent-relay"] == "agent_relay.cli:main"
```

- [ ] **Step 2: Run the contract test and observe the missing-package failure**

Run:

```sh
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py::test_agent_relay_is_an_independent_distribution -q
```

Expected: FAIL because `agent-relay/pyproject.toml` does not exist.

- [ ] **Step 3: Create the package metadata and entry points**

Use this complete `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25,<2"]
build-backend = "hatchling.build"

[project]
name = "agent-relay"
version = "0.1.0"
description = "Lossless, auditable context capsules for Claude Code and Codex"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = []

[project.urls]
Homepage = "https://github.com/H-Lupercal/agent-tooling/tree/main/agent-relay"
Documentation = "https://github.com/H-Lupercal/agent-tooling/tree/main/agent-relay#readme"
Repository = "https://github.com/H-Lupercal/agent-tooling"
Issues = "https://github.com/H-Lupercal/agent-tooling/issues"

[project.optional-dependencies]
dev = [
  "build>=1.2,<2",
  "cyclonedx-bom>=7,<8",
  "hatchling>=1.25,<2",
  "pip-audit>=2.7,<3",
  "pyright>=1.1.400,<2",
  "pytest>=8.3,<10",
  "pytest-cov>=6,<8",
  "ruff>=0.15,<1",
  "twine>=5,<7",
]

[project.scripts]
agent-relay = "agent_relay.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/agent_relay"]

[tool.pytest.ini_options]
addopts = "--strict-markers --strict-config"
markers = ["distribution: built wheel and sdist contract"]
testpaths = ["tests"]

[tool.coverage.run]
branch = true
source = ["agent_relay"]

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

Use these entry points:

```python
# src/agent_relay/__init__.py
"""Lossless context capsules for coding-agent handoffs."""

__version__ = "0.1.0"
CAPSULE_SCHEMA_VERSION = 1
OUTPUT_SCHEMA_VERSION = 1
```

```python
# src/agent_relay/__main__.py
from agent_relay.cli import main

raise SystemExit(main())
```

```python
# src/agent_relay/cli.py
from __future__ import annotations

import argparse


def parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="agent-relay")


def main(argv: list[str] | None = None) -> int:
    parser().parse_args(argv)
    return 0
```

- [ ] **Step 4: Add the package gate and package smoke test**

```make
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
	$(PYTHON) -m pytest --cov=agent_relay --cov-branch --cov-report=term-missing --cov-fail-under=90

check: format-check lint typecheck test

build:
	$(PYTHON) -m build --no-isolation
```

```python
# tests/test_package.py
from __future__ import annotations

import agent_relay
from agent_relay.cli import parser


def test_package_exposes_version_and_empty_cli() -> None:
    assert agent_relay.__version__ == "0.1.0"
    assert parser().prog == "agent-relay"
```

Copy the root MIT license, add the package-local TDD/verification instructions to
`AGENTS.md`, and document only the not-yet-implemented status in `README.md` and
`CHANGELOG.md`.

- [ ] **Step 5: Update the root README and lock the environment**

Add the `Agent Relay` table row, local install command, quick-start link,
development commands, and license link. Then run:

```sh
cd agent-relay
uv lock
uv sync --extra dev --locked
```

Expected: `uv.lock` and `.venv` are created with no runtime dependencies.

- [ ] **Step 6: Run the focused gates**

Run:

```sh
agent-relay/.venv/bin/python -m pytest agent-relay/tests/test_package.py -q
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: both commands PASS.

- [ ] **Step 7: Commit the package foundation**

```sh
git add agent-relay README.md tests/test_release_contract.py
git commit -m "feat: establish agent relay package"
```

---

### Task 2: Define immutable domain contracts, errors, and configuration

**Files:**
- Create: `agent-relay/src/agent_relay/errors.py`
- Create: `agent-relay/src/agent_relay/models.py`
- Create: `agent-relay/src/agent_relay/config.py`
- Create: `agent-relay/tests/conftest.py`
- Create: `agent-relay/tests/helpers.py`
- Create: `agent-relay/tests/test_models.py`
- Create: `agent-relay/tests/test_config.py`

- [ ] **Step 1: Write failing tests for stable enums and validation**

```python
from pathlib import Path

import pytest

from agent_relay.models import ActiveView, Provider, SessionSummary, TransportClass


def test_session_summary_requires_nonempty_native_id() -> None:
    with pytest.raises(ValueError, match="native session ID"):
        SessionSummary(
            provider=Provider.CODEX,
            native_id="",
            transcript=Path("/tmp/session.jsonl"),
            cwd=Path("/tmp/project"),
            last_record_at=None,
            modified_ns=1,
            model="unknown",
            effort="unknown",
            first_user_preview="",
            last_user_preview="",
            record_count=0,
            byte_count=0,
            token_count=None,
        )


def test_wire_values_are_stable() -> None:
    assert ActiveView.UNKNOWN.value == "unknown"
    assert TransportClass.REFERENCE_ONLY.value == "reference_only"
```

```python
from pathlib import Path

from agent_relay.config import Limits, RelayConfig, load_config


def test_default_limits_match_design(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml", data_root=tmp_path)
    assert config == RelayConfig(
        data_root=tmp_path,
        limits=Limits(
            max_record_bytes=67_108_864,
            max_blob_bytes=2_147_483_648,
            max_capsule_bytes=8_589_934_592,
            lock_timeout_seconds=10,
        ),
    )
```

- [ ] **Step 2: Run tests to verify missing contracts**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_models.py tests/test_config.py -q
```

Expected: collection FAIL because the modules do not exist.

- [ ] **Step 3: Implement the stable contracts**

Define these exact public enums and core dataclasses:

```python
class Provider(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"


class ActiveView(StrEnum):
    EXPLICIT = "explicit"
    RECONSTRUCTED = "reconstructed"
    UNKNOWN = "unknown"


class TransportClass(StrEnum):
    DIRECT_INPUT = "direct_input"
    REFERENCE_ONLY = "reference_only"
    UNSUPPORTED = "unsupported"


class ActiveContextState(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    TRANSPORTED_CAPACITY_KNOWN = "transported_capacity_known"
    TRANSPORTED_CAPACITY_UNKNOWN = "transported_capacity_unknown"
    REFERENCE_AVAILABLE_NOT_LOADED = "reference_available_not_loaded"
    REJECTED_BEFORE_LAUNCH = "rejected_before_launch"
    DESTINATION_FAILED = "destination_failed"


@dataclass(frozen=True)
class SessionSummary:
    provider: Provider
    native_id: str
    transcript: Path
    cwd: Path | None
    last_record_at: datetime | None
    modified_ns: int
    model: str
    effort: str
    first_user_preview: str
    last_user_preview: str
    record_count: int
    byte_count: int
    token_count: int | None

    def __post_init__(self) -> None:
        if not self.native_id:
            raise ValueError("native session ID cannot be empty")
        if self.record_count < 0 or self.byte_count < 0:
            raise ValueError("session counts cannot be negative")
```

Define the remaining frozen wire contracts with these exact fields:

```python
@dataclass(frozen=True)
class SourceFile:
    stream_id: str
    role: str
    source_path: Path
    raw_ref: str
    boundary: int
    byte_count: int
    sha256: str
    appended_after_snapshot: bool


@dataclass(frozen=True)
class IndexedEvent:
    stream_id: str
    sequence: int
    replay_scope: str
    source_type: str
    source_timestamp: datetime | None
    raw_ref: str
    raw_offset: int
    raw_length: int
    raw_sha256: str
    normalized: Mapping[str, object]


@dataclass(frozen=True)
class RepositorySnapshot:
    root: Path | None
    common_dir: Path | None
    project_key: str
    captured_at: datetime
    head: str | None
    branch: str | None
    status: bytes | None
    diff: bytes | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class FidelityReport:
    native_records: int
    exact_records: int
    structural_records: int
    unavailable_records: int
    summarized_records: int
    truncated_records: int
    captured_bytes: int
    active_view: ActiveView
    appended_after_snapshot: bool


@dataclass(frozen=True)
class CapsuleManifest:
    schema_version: int
    capsule_id: str
    created_at: datetime
    relay_version: str
    provider: Provider
    native_session_id: str
    model: str
    effort: str
    project_key: str
    source_files: tuple[SourceFile, ...]
    events: tuple[IndexedEvent, ...]
    file_inventory: Mapping[str, FileDigest]
    fidelity: FidelityReport


@dataclass(frozen=True)
class FileDigest:
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class ReplayArtifact:
    data: bytes
    sha256: str
    active_view: ActiveView
    includes_archive: bool
    includes_added_context: bool


@dataclass(frozen=True)
class LaunchReceipt:
    schema_version: int
    launch_id: str
    capsule_id: str
    capsule_sha256: str
    destination: Provider
    cli_version: str
    adapter_version: str
    transport: TransportClass
    active_view: ActiveView
    replay_bytes: int
    replay_sha256: str
    capacity: str
    allow_sensitive: bool
    allow_unknown_capacity: bool
    allow_reference_import: bool
    pid: int | None
    process_started_at: datetime | None
    started_at: datetime
    ended_at: datetime | None
    exit_status: int | None
    active_context_state: ActiveContextState
```

Keep all wire enums string-valued and reject negative byte counts, invalid
64-character lowercase SHA-256 values, non-positive event sequences, unsafe
capsule IDs, and unsupported schema versions in `__post_init__`.

Define errors and exits:

```python
class ExitCode(IntEnum):
    OK = 0
    USAGE = 2
    NOT_FOUND = 3
    CAPTURE_FAILED = 4
    INTEGRITY_FAILED = 5
    LAUNCH_BLOCKED = 6
    PROVIDER_FAILED = 7
    DESTINATION_FAILED = 8


class RelayError(Exception):
    def __init__(self, message: str, *, code: ExitCode, error_code: str) -> None:
        super().__init__(message)
        self.code = code
        self.error_code = error_code
```

- [ ] **Step 4: Implement strict configuration parsing**

Use frozen `Limits` and `RelayConfig` dataclasses. `load_config()` reads TOML when
present, rejects unknown top-level tables and unknown `limits` keys, rejects
non-positive values, and otherwise returns the design defaults. `default_data_root()`
uses `XDG_DATA_HOME`, `~/Library/Application Support`, or `LOCALAPPDATA` according
to `sys.platform`.

Create the fixed test roots:

```python
# tests/conftest.py
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def fixtures() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 7, 22, 18, 45, 22, tzinfo=UTC)
```

Start `tests/helpers.py` with imports and `make_sha256(data: bytes) -> str`; later
tasks add only the factories listed in the test-support ownership table.

- [ ] **Step 5: Run tests and typecheck**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_models.py tests/test_config.py -q
.venv/bin/python -m pyright
```

Expected: PASS.

- [ ] **Step 6: Commit the contracts**

```sh
git add agent-relay/src/agent_relay/errors.py agent-relay/src/agent_relay/models.py agent-relay/src/agent_relay/config.py agent-relay/tests/conftest.py agent-relay/tests/helpers.py agent-relay/tests/test_models.py agent-relay/tests/test_config.py
git commit -m "feat: define relay domain contracts"
```

---

### Task 3: Implement safe files, repository identity, and deterministic selection

**Files:**
- Create: `agent-relay/src/agent_relay/safe_files.py`
- Create: `agent-relay/src/agent_relay/selection.py`
- Modify: `agent-relay/tests/helpers.py`
- Create: `agent-relay/tests/test_safe_files.py`
- Create: `agent-relay/tests/test_selection.py`

- [ ] **Step 1: Write failing path, identity, and latest-selection tests**

```python
def test_latest_uses_last_native_timestamp_and_rejects_ties(tmp_path: Path) -> None:
    first = summary("aaaabbbb", tmp_path / "one.jsonl", timestamp="2026-07-22T10:00:00Z")
    second = summary("ccccdddd", tmp_path / "two.jsonl", timestamp="2026-07-22T10:00:00Z")
    with pytest.raises(RelayError, match="ambiguous latest session"):
        choose_session([first, second], latest=True, session_prefix=None)


def test_all_never_broadens_latest_selection(tmp_path: Path) -> None:
    outside = summary("aaaabbbb", tmp_path / "one.jsonl", cwd=tmp_path / "other")
    with pytest.raises(RelayError, match="explicit --session"):
        choose_for_repository([outside], repository=tmp_path / "repo", include_all=True)
```

```python
def test_atomic_write_rejects_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("owned")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(RelayError, match="symlink"):
        atomic_write_bytes(link, b"replacement", mode=0o600)
    assert target.read_text() == "owned"
```

- [ ] **Step 2: Run tests to verify missing behavior**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_safe_files.py tests/test_selection.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement safe filesystem primitives**

Implement:

```python
def atomic_write_bytes(path: Path, data: bytes, *, mode: int) -> None:
    parent = path.parent.resolve(strict=True)
    if path.is_symlink():
        raise RelayError("refusing symlink target", code=ExitCode.INTEGRITY_FAILED, error_code="symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
```

Add `ensure_private_directory()`, Windows `icacls` owner-only application and
verification, `resolved_within()`, and a per-project advisory lock with a
10-second default timeout. Use `fcntl.flock(..., LOCK_EX | LOCK_NB)` on POSIX and
`msvcrt.locking(..., LK_NBLCK, 1)` on Windows with a monotonic deadline and
50-millisecond polling. Tests mock Windows subprocess results rather than changing
host ACLs.

- [ ] **Step 4: Implement repository matching and selectors**

Implement canonical Git identity by invoking:

```python
["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"]
["git", "-C", str(path), "rev-parse", "--show-toplevel"]
```

Hash `common_dir.resolve()` plus `worktree.resolve()` with SHA-256. Implement:
`matches_repository()`, `filter_sessions()`, `choose_session()`,
`parse_since()`, `unique_prefix()`, and 120-character masked previews. Require
eight-character session prefixes and fail tied latest timestamps.

- [ ] **Step 5: Run focused tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_safe_files.py tests/test_selection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the shared foundation**

```sh
git add agent-relay/src/agent_relay/safe_files.py agent-relay/src/agent_relay/selection.py agent-relay/tests/helpers.py agent-relay/tests/test_safe_files.py agent-relay/tests/test_selection.py
git commit -m "feat: add safe storage and session selection"
```

---

### Task 4: Add the Codex source adapter

**Conductor:** `implementation`, Terra/high, owned paths limited to this task.

**Files:**
- Create: `agent-relay/src/agent_relay/providers/__init__.py`
- Create: `agent-relay/src/agent_relay/providers/base.py`
- Create: `agent-relay/src/agent_relay/providers/codex.py`
- Create: `agent-relay/tests/test_provider_codex.py`
- Create: `agent-relay/tests/fixtures/codex/root.jsonl`
- Create: `agent-relay/tests/fixtures/codex/child.jsonl`
- Create: `agent-relay/tests/fixtures/codex/compacted.jsonl`
- Create: `agent-relay/tests/fixtures/codex/malformed.jsonl`

- [ ] **Step 1: Create byte-stable fixtures and failing discovery tests**

The root fixture begins:

```jsonl
{"type":"session_meta","payload":{"id":"codex-root-0001","parent_thread_id":null,"cwd":"/tmp/project","cli_version":"0.145.0","model":"gpt-5.6-sol","reasoning_effort":"high"},"timestamp":"2026-07-22T10:00:00Z"}
{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Preserve this exactly."}]},"timestamp":"2026-07-22T10:00:01Z"}
{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Working."}]},"timestamp":"2026-07-22T10:00:02Z"}
```

Test exact metadata and byte offsets:

```python
def test_codex_adapter_discovers_metadata_and_raw_ranges(fixtures: Path) -> None:
    adapter = CodexSourceAdapter(fixtures / "codex")
    session = adapter.sessions()[0]
    assert session.native_id == "codex-root-0001"
    assert session.model == "gpt-5.6-sol"
    assert session.effort == "high"
    records = list(adapter.records(session))
    raw = session.transcript.read_bytes()
    assert raw[records[1].offset : records[1].offset + records[1].length].endswith(b"\n")
```

- [ ] **Step 2: Run the Codex test and observe the import failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_provider_codex.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Define the source-adapter protocol**

```python
class SourceAdapter(Protocol):
    provider: Provider

    def sessions(self) -> tuple[SessionSummary, ...]: ...
    def records(self, session: SessionSummary) -> Iterator[NativeRecord]: ...
    def session_graph(self, session: SessionSummary) -> SessionGraph: ...
    def active_view(self, session: SessionSummary) -> ActiveViewResult: ...
```

Define frozen `NativeRecord`, `SessionGraph`, and `ActiveViewResult` in
`providers/base.py` exactly as follows:

```python
@dataclass(frozen=True)
class NativeRecord:
    source_path: Path
    offset: int
    length: int
    timestamp: datetime | None
    native_type: str
    normalized: Mapping[str, object]


@dataclass(frozen=True)
class SessionStream:
    native_id: str
    transcript: Path
    replay_scope: str
    parent_native_id: str | None


@dataclass(frozen=True)
class SessionGraph:
    primary: SessionStream
    auxiliary: tuple[SessionStream, ...]
    metadata_files: tuple[Path, ...]
    attachments: tuple[Path, ...]


@dataclass(frozen=True)
class ActiveViewResult:
    classification: ActiveView
    record_refs: tuple[tuple[str, int], ...]
    reason: str
```

`record_refs` contains `(stream_id, one-based sequence)` pairs and must reference
only primary-stream events.

- [ ] **Step 4: Implement Codex discovery and framing**

Walk `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` or the injected test root.
Read only complete newline-terminated records. Parse `session_meta`,
`response_item`, `token_count`, compaction records, and subagent references.
Unknown JSON object types retain `native_type="unknown"`. Invalid JSON with a
complete newline yields an opaque record; invalid file framing raises
`CAPTURE_FAILED`.

- [ ] **Step 5: Implement Codex active-view classification**

Return `RECONSTRUCTED` only when a documented compaction record supplies a summary
and an unambiguous retained-event boundary. Otherwise return `UNKNOWN`; never infer
an active subset from token counts.

- [ ] **Step 6: Run the adapter tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_provider_codex.py -q
```

Expected: PASS, including unknown-record, missing-model, child-reference, and
compaction cases.

- [ ] **Step 7: Commit the Codex adapter**

```sh
git add agent-relay/src/agent_relay/providers agent-relay/tests/test_provider_codex.py agent-relay/tests/fixtures/codex
git commit -m "feat: capture codex session records"
```

---

### Task 5: Add the Claude source adapter

**Conductor:** `implementation`, Terra/high, owned paths limited to this task.

**Files:**
- Create: `agent-relay/src/agent_relay/providers/claude.py`
- Create: `agent-relay/tests/test_provider_claude.py`
- Create: `agent-relay/tests/fixtures/claude/root.jsonl`
- Create: `agent-relay/tests/fixtures/claude/sidechain.jsonl`
- Create: `agent-relay/tests/fixtures/claude/summary.jsonl`
- Create: `agent-relay/tests/fixtures/claude/malformed.jsonl`
- Modify: `agent-relay/src/agent_relay/providers/__init__.py`

- [ ] **Step 1: Write Claude fixtures and failing tests**

Use a sanitized native shape:

```jsonl
{"parentUuid":null,"isSidechain":false,"cwd":"/tmp/project","sessionId":"claude-root-0001","version":"1.0.0","type":"user","message":{"role":"user","content":"Preserve this exactly."},"uuid":"u-1","timestamp":"2026-07-22T10:00:00Z"}
{"parentUuid":"u-1","isSidechain":false,"cwd":"/tmp/project","sessionId":"claude-root-0001","version":"1.0.0","type":"assistant","message":{"role":"assistant","model":"claude-opus","content":[{"type":"text","text":"Working."}]},"uuid":"a-1","timestamp":"2026-07-22T10:00:01Z"}
```

```python
def test_claude_adapter_keeps_sidechain_auxiliary(fixtures: Path) -> None:
    adapter = ClaudeSourceAdapter(fixtures / "claude")
    session = next(item for item in adapter.sessions() if item.native_id == "claude-root-0001")
    graph = adapter.session_graph(session)
    assert graph.primary.native_id == "claude-root-0001"
    assert tuple(child.replay_scope for child in graph.auxiliary) == ("auxiliary",)
```

- [ ] **Step 2: Run the test and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_provider_claude.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement Claude discovery and metadata**

Walk `~/.claude/projects/<encoded-cwd>/*.jsonl` or the injected root. Extract
`sessionId`, `cwd`, timestamps, model from assistant messages, and effort only when
the native record contains it. Missing values become `"unknown"`.

- [ ] **Step 4: Implement sidechain and summary handling**

Frame complete newline records exactly. Use `isSidechain`, `parentUuid`, session
IDs, and explicit transcript references to build auxiliary streams. Treat a native
summary record as `RECONSTRUCTED` only when it identifies the retained leaf/boundary;
otherwise classify the active view as `UNKNOWN`.

- [ ] **Step 5: Run the Claude adapter tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_provider_claude.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the Claude adapter**

```sh
git add agent-relay/src/agent_relay/providers agent-relay/tests/test_provider_claude.py agent-relay/tests/fixtures/claude
git commit -m "feat: capture claude session records"
```

---

### Task 6: Build append-safe raw capture and session closure

**Files:**
- Create: `agent-relay/src/agent_relay/capture.py`
- Create: `agent-relay/tests/test_capture.py`

- [ ] **Step 1: Write failing stable-prefix and closure tests**

```python
def test_capture_ignores_records_appended_after_boundary(tmp_path: Path) -> None:
    source = tmp_path / "session.jsonl"
    source.write_bytes(b'{"type":"one"}\n')
    boundary = establish_boundary(source, max_record_bytes=1024)
    source.write_bytes(source.read_bytes() + b'{"type":"two"}\n')
    snapshot = copy_stable_prefix(boundary, tmp_path / "raw.jsonl")
    assert (tmp_path / "raw.jsonl").read_bytes() == b'{"type":"one"}\n'
    assert snapshot.appended_after_snapshot is True


def test_capture_rejects_mutation_before_boundary(tmp_path: Path) -> None:
    source = tmp_path / "session.jsonl"
    source.write_bytes(b'{"type":"one"}\n')
    boundary = establish_boundary(source, max_record_bytes=1024)
    source.write_bytes(b'{"type":"mutated"}\n')
    with pytest.raises(RelayError, match="changed before snapshot boundary"):
        copy_stable_prefix(boundary, tmp_path / "raw.jsonl")
```

- [ ] **Step 2: Run the capture test and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_capture.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement fixed boundaries and raw copies**

`establish_boundary()` opens the file without following symlinks, records device,
inode/file ID, size, mtime, and the final complete newline offset. It rejects a
record larger than `max_record_bytes`. `copy_stable_prefix()` reads exactly that
prefix, hashes while streaming, fsyncs the destination, then verifies identity,
size, and the digest of the source prefix.

- [ ] **Step 4: Implement capture closure and normalized indexes**

`CaptureEngine.capture(session, adapter, options)` copies the primary stream,
explicit auxiliary streams, referenced provider metadata, and explicit binary
conversation inputs. It writes `events.jsonl` with `raw_ref`, byte range, SHA-256,
stream ID, local sequence, replay scope, timestamp, native type, and normalized
index. It never crawls adjacent files. Referenced attachments must be regular,
non-symlink files explicitly named by a captured native input record; missing or
unsafe attachments are reported unavailable and never followed.

- [ ] **Step 5: Add retry and size-limit cases**

Test one retry after in-boundary mutation, hard failure after the second unstable
attempt, incomplete trailing-record reporting, maximum blob failure, and maximum
capsule failure. Assert every failure leaves no published capsule.

- [ ] **Step 6: Run the focused tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_capture.py tests/test_provider_codex.py tests/test_provider_claude.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit capture**

```sh
git add agent-relay/src/agent_relay/capture.py agent-relay/tests/test_capture.py
git commit -m "feat: capture stable raw session prefixes"
```

---

### Task 7: Publish and verify immutable capsules

**Files:**
- Create: `agent-relay/src/agent_relay/capsules.py`
- Modify: `agent-relay/tests/helpers.py`
- Create: `agent-relay/tests/test_capsules.py`

- [ ] **Step 1: Write failing canonical-manifest tests**

```python
def test_publish_creates_canonical_manifest_and_latest(tmp_path: Path) -> None:
    store = CapsuleStore(tmp_path)
    capsule = store.publish(project_key="project", staged=staged_capsule(tmp_path))
    manifest_bytes = (capsule.path / "manifest.json").read_bytes()
    assert manifest_bytes == canonical_json_bytes(json.loads(manifest_bytes))
    latest = json.loads((tmp_path / "projects/project/latest.json").read_text())
    assert latest["capsule_id"] == capsule.capsule_id
    assert latest["capsule_sha256"] == capsule.digest


def test_verify_detects_raw_byte_change(tmp_path: Path) -> None:
    capsule = published_capsule(tmp_path)
    (capsule.path / "raw/root.jsonl").write_bytes(b"changed\n")
    with pytest.raises(RelayError, match="digest mismatch"):
        CapsuleStore(tmp_path).verify(capsule.capsule_id, project_key="project")
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_capsules.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement canonical JSON and capsule IDs**

```python
@dataclass(frozen=True)
class VerifiedCapsule:
    capsule_id: str
    path: Path
    digest: str
    manifest: CapsuleManifest


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def new_capsule_id(now: datetime, random_bytes: bytes) -> str:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"capsule-{stamp}-{random_bytes.hex()[:12]}"
```

Use `secrets.token_bytes(6)` in production and injected bytes in tests.

- [ ] **Step 4: Implement publication and verification**

Inventory every file except `manifest.json` in lexical order with byte length and
SHA-256. Write the canonical manifest, hash it for the capsule digest, acquire the
project lock, atomically rename the staged directory, then atomically update
`latest.json`. Verification rejects unknown schema versions, symlinks, missing
files, extra files, length mismatches, and digest mismatches.

- [ ] **Step 5: Test concurrency and immutability**

Use two threads blocked on a barrier to publish separate staged capsules. Assert
both survive, `latest` names the last completed publication, timeout publishes
nothing, and launch operations never change capsule mtimes or contents.

- [ ] **Step 6: Run focused tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_capsules.py tests/test_safe_files.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit capsule storage**

```sh
git add agent-relay/src/agent_relay/capsules.py agent-relay/tests/helpers.py agent-relay/tests/test_capsules.py
git commit -m "feat: publish immutable context capsules"
```

---

### Task 8: Capture Git state and block sensitive launches

**Conductor:** `implementation`, Terra/medium, owned paths limited to this task.

**Files:**
- Create: `agent-relay/src/agent_relay/repository.py`
- Create: `agent-relay/src/agent_relay/sensitive.py`
- Modify: `agent-relay/tests/conftest.py`
- Create: `agent-relay/tests/test_repository.py`
- Create: `agent-relay/tests/test_sensitive.py`

- [ ] **Step 1: Write failing repository and scanner tests**

```python
def test_snapshot_marks_capture_time_and_optional_diff(git_repo: Path) -> None:
    (git_repo / "tracked.txt").write_text("changed\n")
    snapshot = snapshot_repository(git_repo, include_diff=False)
    assert snapshot.diff is None
    assert "tracked.txt" in snapshot.status


def test_scanner_reports_location_without_secret_value() -> None:
    secret = "Authorization: Bearer abcdef123456"
    findings = scan_bytes(secret.encode(), source="events.jsonl")
    assert findings[0].category == "bearer_token"
    assert findings[0].source == "events.jsonl"
    assert "abcdef123456" not in repr(findings)
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_repository.py tests/test_sensitive.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement read-only Git snapshots**

Run Git with explicit argv, captured output, `check=True`, and `shell=False`:

```python
def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        shell=False,
    ).stdout
```

Capture root, common dir, HEAD, branch, porcelain-v2 `-z` status, timestamps, and
optional `git diff --binary HEAD`. Mark live state unavailable rather than guessing
when a selected historical repository no longer exists.

- [ ] **Step 4: Implement deterministic scanning**

Define:

```python
@dataclass(frozen=True)
class SensitiveFinding:
    category: str
    source: str
    byte_offset: int
    record_sequence: int | None
```

Scan raw bytes, replay bytes, attachments, and included diffs for private-key
headers, bearer credentials, credential URLs, and assignment names containing
`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`, or `AUTH`. Return category,
source, byte offset, and record sequence only. If scan limits are exceeded, raise
`LAUNCH_BLOCKED` with `sensitive_scan_incomplete`.

- [ ] **Step 5: Run focused tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_repository.py tests/test_sensitive.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit repository and scanning**

```sh
git add agent-relay/src/agent_relay/repository.py agent-relay/src/agent_relay/sensitive.py agent-relay/tests/conftest.py agent-relay/tests/test_repository.py agent-relay/tests/test_sensitive.py
git commit -m "feat: snapshot repositories and detect secrets"
```

---

### Task 9: Generate deterministic active-view and archival replay

**Files:**
- Create: `agent-relay/src/agent_relay/replay.py`
- Modify: `agent-relay/tests/conftest.py`
- Create: `agent-relay/tests/test_replay.py`

- [ ] **Step 1: Write failing replay-scope tests**

```python
def test_strict_replay_excludes_auxiliary_streams(capsule: VerifiedCapsule) -> None:
    replay = build_replay(capsule, ReplayOptions())
    assert b"PRIMARY EVENT" in replay.data
    assert b"CHILD PRIVATE EVENT" not in replay.data
    assert replay.active_view is ActiveView.UNKNOWN


def test_include_related_is_labeled_added_context(capsule: VerifiedCapsule) -> None:
    replay = build_replay(capsule, ReplayOptions(include_related=True))
    assert b"BEGIN ADDED AUXILIARY CONTEXT" in replay.data
    assert replay.includes_added_context is True
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_replay.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement deterministic replay framing**

Define:

```python
@dataclass(frozen=True)
class ReplayOptions:
    include_archive: bool = False
    include_related: bool = False
```

Use fixed UTF-8 delimiters containing capsule ID, source provider/model/effort,
stream, sequence, native role/type, raw digest, and source timestamp. JSON payloads
are rendered from raw bytes, not normalized mappings. Binary records render a
digest and capsule-relative blob reference. Historical system/developer content is
tagged `HISTORICAL_SOURCE_INSTRUCTION`.

- [ ] **Step 4: Implement active-view rules**

For `EXPLICIT` and `RECONSTRUCTED`, replay the adapter-supplied active record
references. Add the full primary archive only with `include_archive=True`. For
`UNKNOWN`, replay the full primary archive and set
`source_active_view=unknown`. Auxiliary streams require `include_related=True` and
an `ADDED AUXILIARY CONTEXT` delimiter.

- [ ] **Step 5: Hash and test replay determinism**

Build the same replay twice and assert byte equality and SHA-256 equality. Assert
option changes alter the hash and are reflected in metadata.

- [ ] **Step 6: Commit replay**

```sh
git add agent-relay/src/agent_relay/replay.py agent-relay/tests/conftest.py agent-relay/tests/test_replay.py
git commit -m "feat: build deterministic context replay"
```

---

### Task 10: Classify destination CLI transport and capacity

**Files:**
- Create: `agent-relay/src/agent_relay/destinations/__init__.py`
- Create: `agent-relay/src/agent_relay/destinations/base.py`
- Create: `agent-relay/src/agent_relay/destinations/codex.py`
- Create: `agent-relay/src/agent_relay/destinations/claude.py`
- Create: `agent-relay/tests/test_destinations.py`

- [ ] **Step 1: Write failing capability tests**

```python
def test_unknown_cli_version_is_unsupported() -> None:
    capability = CodexDestination().classify("999.0.0", initial_input_bytes=100)
    assert capability.transport is TransportClass.UNSUPPORTED


def test_reference_transport_requires_explicit_acknowledgement() -> None:
    capability = ClaudeDestination().classify("2.1.218", initial_input_bytes=8_001)
    assert capability.transport is TransportClass.REFERENCE_ONLY
    assert capability.requires_reference_ack is True
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_destinations.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Define the destination protocol**

```python
class DestinationAdapter(Protocol):
    provider: Provider

    def detect_version(self, executable: Path) -> str: ...
    def classify(self, version: str, *, initial_input_bytes: int) -> DestinationCapability: ...
    def command(
        self,
        executable: Path,
        *,
        repository: Path,
        launch_name: str,
        initial_prompt: str,
    ) -> tuple[str, ...]: ...
    def exact_token_count(self, replay: bytes, capability: DestinationCapability) -> int | None: ...
```

Define:

```python
@dataclass(frozen=True)
class DestinationCapability:
    transport: TransportClass
    tested_version_range: str
    input_channel: str | None
    safe_argv_bytes: int
    context_limit_tokens: int | None
    exact_token_counter: bool
    requires_reference_ack: bool
```

- [ ] **Step 4: Implement versioned Codex and Claude matrices**

Probe versions with `[executable, "--version"]`. The first capability matrix
supports exactly:

```python
SUPPORTED = {
    Provider.CODEX: {"0.145.0": 8_000},
    Provider.CLAUDE: {"2.1.218": 8_000},
}
```

Both versions document a positional initial prompt. Classify a complete UTF-8
bootstrap plus replay of at most 8,000 bytes as `DIRECT_INPUT` with
`input_channel="argv_prompt"`. Larger input is `REFERENCE_ONLY`; neither current
adapter claims interactive stdin support. Codex constructs
`(executable, "-C", repository, prompt)`. Claude constructs
`(executable, "--name", launch_name, prompt)`. Never guess compatibility for an
unknown version.

Version one does not translate source model or effort into destination CLI flags.
The new session uses the destination provider's configured defaults. Tests assert
that generated argv contains no relay-inferred `--model` or `--effort`; the source
model and effort remain visible in the capsule and bootstrap.

- [ ] **Step 5: Implement capacity states**

The first two capability entries set `exact_token_counter=False`, so capacity is
`unknown` even when the replay fits the 8 KB transport. Return a labeled heuristic
estimate for display and require `--allow-unknown-capacity`. Add known-capacity
tests with a fake adapter that supplies both an exact counter and a context limit;
known overflow returns `LAUNCH_BLOCKED` before process creation.

- [ ] **Step 6: Run destination tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_destinations.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit destination adapters**

```sh
git add agent-relay/src/agent_relay/destinations agent-relay/tests/test_destinations.py
git commit -m "feat: classify provider launch capabilities"
```

---

### Task 11: Implement launch preflight, lifecycle, and receipts

**Files:**
- Create: `agent-relay/src/agent_relay/launch.py`
- Modify: `agent-relay/tests/conftest.py`
- Modify: `agent-relay/tests/helpers.py`
- Create: `agent-relay/tests/test_launch.py`
- Create: `agent-relay/tests/fixtures/bin/fake-codex`
- Create: `agent-relay/tests/fixtures/bin/fake-claude`

- [ ] **Step 1: Write failing preflight and receipt tests**

```python
def test_sensitive_launch_is_blocked_before_process_creation(context: LaunchContext) -> None:
    runner = RecordingRunner()
    with pytest.raises(RelayError, match="--allow-sensitive"):
        launch(context.with_sensitive_finding(), runner=runner)
    assert runner.calls == []


def test_direct_launch_receipt_does_not_claim_model_loading(context: LaunchContext) -> None:
    receipt = launch(context.with_known_capacity(), runner=successful_runner())
    assert receipt.active_context_state is ActiveContextState.TRANSPORTED_CAPACITY_KNOWN
    assert receipt.transport is TransportClass.DIRECT_INPUT
    assert receipt.replay_sha256 == sha256(context.replay.data).hexdigest()
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_launch.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement ordered preflight**

Define the launch input and runner boundary:

```python
@dataclass(frozen=True)
class LaunchOptions:
    allow_sensitive: bool = False
    allow_unknown_capacity: bool = False
    allow_reference_import: bool = False
    keep_launch_files: bool = False


@dataclass(frozen=True)
class LaunchContext:
    capsule: VerifiedCapsule
    replay: ReplayArtifact
    repository: Path
    executable: Path
    destination: DestinationAdapter
    options: LaunchOptions
    findings: tuple[SensitiveFinding, ...]


class ProcessRunner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
    ) -> ProcessResult: ...


@dataclass(frozen=True)
class ProcessResult:
    pid: int
    process_started_at: datetime
    ended_at: datetime
    exit_status: int
```

Verify the capsule, build replay, scan every transferred byte, classify CLI
version/transport, enforce `--allow-sensitive`, enforce
`--allow-reference-import`, and enforce known/unknown capacity in that order. No
destination process starts before all gates pass.

- [ ] **Step 4: Implement shell-free process launch**

Use `subprocess.Popen(argv, shell=False, cwd=repository)` for the documented
positional-prompt direct transport. Reference mode creates
`launches/<id>/replay.bin` with owner-only permissions and passes only the
deterministic bootstrap path as the positional prompt. Record PID and process
start time before waiting.

- [ ] **Step 5: Implement immutable launch receipts**

Write `receipt.json` atomically outside the capsule with capsule and replay digests,
provider/CLI/adapter versions, transport, capacity, acknowledgements, PID/start
time, timestamps, exit status, and the exact active-context state. Delete
`replay.bin` after exit unless requested otherwise; never write replay text or
secret values into the receipt.

- [ ] **Step 6: Test failure and interruption cleanup**

Cover missing CLI, nonzero destination exit, keyboard interruption, reference
acknowledgement, unknown-capacity acknowledgement, replay cleanup, PID start-time
recording, and unchanged capsule bytes.

- [ ] **Step 7: Run focused tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_launch.py tests/test_destinations.py tests/test_sensitive.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit launch behavior**

```sh
git add agent-relay/src/agent_relay/launch.py agent-relay/tests/conftest.py agent-relay/tests/helpers.py agent-relay/tests/test_launch.py agent-relay/tests/fixtures/bin
git commit -m "feat: launch providers with fidelity receipts"
```

---

### Task 12: Add sessions, capture, capsules, and verify CLI commands

**Files:**
- Modify: `agent-relay/src/agent_relay/cli.py`
- Create: `agent-relay/src/agent_relay/reporting.py`
- Modify: `agent-relay/tests/helpers.py`
- Create: `agent-relay/tests/test_cli.py`

- [ ] **Step 1: Write failing parser and JSON-output tests**

```python
def test_capture_defaults_to_latest_current_repository() -> None:
    arguments = parser().parse_args(["capture", "codex"])
    assert arguments.command == "capture"
    assert arguments.provider == "codex"
    assert arguments.latest is True


def test_json_error_is_stable(capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["sessions", "codex", "--json"], services=missing_sessions())
    payload = json.loads(capsys.readouterr().out)
    assert result == 3
    assert payload == {
        "schema_version": 1,
        "command": "sessions",
        "status": "error",
        "error_code": "session_not_found",
        "data": {},
    }
```

- [ ] **Step 2: Run the CLI tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_cli.py -q
```

Expected: FAIL because subcommands are missing.

- [ ] **Step 3: Build the parser exactly from the option contract**

Add `sessions`, `capture`, `capsules`, and `verify`. Make `--latest`, `--session`,
and `--pick` mutually exclusive; omission means latest. Reject `--all` capture
without explicit `--session`. Require a TTY for `--pick`. Add `--json` to every
subcommand.

- [ ] **Step 4: Implement reporting**

Human session rows contain masked 120-character first/last previews. JSON always
uses:

```python
{
    "schema_version": 1,
    "command": command,
    "status": status,
    "error_code": error_code,
    "data": data,
}
```

Diagnostics go to stderr; JSON stdout contains no prose. Map every `RelayError`
exit code directly.

- [ ] **Step 5: Wire read and capture services**

Dispatch through this injected boundary so tests use temporary provider roots and
clocks:

```python
@dataclass(frozen=True)
class Services:
    config: RelayConfig
    sources: Mapping[Provider, SourceAdapter]
    destinations: Mapping[Provider, DestinationAdapter]
    capsule_store: CapsuleStore
    capture_engine: CaptureEngine
    process_runner: ProcessRunner
    now: Callable[[], datetime]
```

Change the entry point signature to:

```python
def main(
    argv: list[str] | None = None,
    *,
    services: Services | None = None,
) -> int:
    active_services = services if services is not None else build_services()
    return dispatch(parser().parse_args(argv), active_services)
```

`capture` prints the selected session before capture, publishes only after
verification, and reports exact/structural/unavailable/summary/truncation counts.

- [ ] **Step 6: Run CLI tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the capture CLI**

```sh
git add agent-relay/src/agent_relay/cli.py agent-relay/src/agent_relay/reporting.py agent-relay/tests/helpers.py agent-relay/tests/test_cli.py
git commit -m "feat: expose session capture commands"
```

---

### Task 13: Add switch and start orchestration

**Files:**
- Modify: `agent-relay/src/agent_relay/cli.py`
- Modify: `agent-relay/tests/helpers.py`
- Modify: `agent-relay/tests/test_cli.py`

- [ ] **Step 1: Write failing switch/start command tests**

```python
def test_switch_publishes_capsule_before_launch() -> None:
    events: list[str] = []
    services = service_bundle(events=events)
    result = main(["switch", "--from", "codex", "--to", "claude"], services=services)
    assert result == 0
    assert events[:3] == ["capture", "verify", "launch"]


def test_unknown_capacity_requires_ack() -> None:
    services = service_bundle(capacity="unknown")
    assert main(["start", "claude", "--capsule", "latest"], services=services) == 6
    assert main(
        ["start", "claude", "--capsule", "latest", "--allow-unknown-capacity"],
        services=services,
    ) == 0
```

- [ ] **Step 2: Run focused tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_cli.py -k "switch or start or capacity" -q
```

Expected: FAIL because commands are absent.

- [ ] **Step 3: Add full switch and start options**

`switch` owns source selectors, `--include-diff`, replay-expanding flags, all three
acknowledgements, launch-file retention, and JSON. `start` owns capsule selection,
replay flags, acknowledgements, retention, and JSON. Permit same-provider switching
while always creating a new destination session.

- [ ] **Step 4: Wire ordered orchestration**

`switch`: select → capture → verify → print capsule ID → preflight → launch.
`start`: resolve capsule → verify → preflight → launch. A blocked or failed launch
never deletes the capsule.

- [ ] **Step 5: Run CLI and launch tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_cli.py tests/test_launch.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit orchestration**

```sh
git add agent-relay/src/agent_relay/cli.py agent-relay/tests/helpers.py agent-relay/tests/test_cli.py
git commit -m "feat: switch and resume provider sessions"
```

---

### Task 14: Add doctor and preview-first cleanup

**Conductor:** `implementation`, Terra/medium, owned paths limited to this task.

**Files:**
- Create: `agent-relay/src/agent_relay/doctor.py`
- Create: `agent-relay/src/agent_relay/cleanup.py`
- Modify: `agent-relay/tests/helpers.py`
- Create: `agent-relay/tests/test_doctor_cleanup.py`
- Modify: `agent-relay/src/agent_relay/cli.py`

- [ ] **Step 1: Write failing diagnostics and cleanup tests**

```python
def test_doctor_is_read_only(tmp_path: Path) -> None:
    before = snapshot_tree(tmp_path)
    report = run_doctor(config_for(tmp_path))
    assert report.storage_status == "missing"
    assert snapshot_tree(tmp_path) == before


def test_gc_refuses_live_launch(tmp_path: Path) -> None:
    candidate = old_capsule_with_live_receipt(tmp_path)
    plan = plan_cleanup(tmp_path, older_than=timedelta(days=30), all_projects=True)
    assert candidate not in plan.deletable
    assert candidate in plan.blocked_live
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_doctor_cleanup.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Implement read-only doctor**

Report storage/ACL status, source roots, format probes, installed destination
versions, supported ranges, transport class, capacity knowledge, and skill
ownership. Do not create storage, capsules, locks, or provider processes.

- [ ] **Step 4: Implement cleanup plans and guarded apply**

Parse `m/h/d/w` durations. Scope to current repository unless `--all`. Preview by
default. Before `--apply`, revalidate every target beneath the data root and refuse
live launches by matching both PID and process start time. Delete only the exact
planned capsule and stale launch paths.

- [ ] **Step 5: Wire doctor and gc commands**

Return versioned JSON and stable exit codes. `gc --apply` prints removed capsule
IDs and whether replay files are recoverable (`false` after deletion).

- [ ] **Step 6: Run focused tests and commit**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_doctor_cleanup.py tests/test_cli.py -q
```

Expected: PASS.

```sh
git add agent-relay/src/agent_relay/doctor.py agent-relay/src/agent_relay/cleanup.py agent-relay/src/agent_relay/cli.py agent-relay/tests/helpers.py agent-relay/tests/test_doctor_cleanup.py
git commit -m "feat: diagnose and clean relay storage"
```

---

### Task 15: Add transactional Codex and Claude skills

**Conductor:** `implementation`, Terra/medium, owned paths limited to this task.

**Files:**
- Create: `agent-relay/src/agent_relay/skills.py`
- Create: `agent-relay/src/agent_relay/assets/codex/SKILL.md`
- Create: `agent-relay/src/agent_relay/assets/claude/SKILL.md`
- Create: `agent-relay/tests/test_skills.py`
- Modify: `agent-relay/pyproject.toml`
- Modify: `agent-relay/src/agent_relay/cli.py`

- [ ] **Step 1: Write failing ownership tests**

```python
def test_install_refuses_unowned_skill(tmp_path: Path) -> None:
    target = tmp_path / "context-relay" / "SKILL.md"
    target.parent.mkdir()
    target.write_text("user content")
    with pytest.raises(RelayError, match="unowned"):
        install_skill(Provider.CODEX, target.parent)
    assert target.read_text() == "user content"


def test_uninstall_keeps_modified_managed_skill(tmp_path: Path) -> None:
    installed = install_skill(Provider.CLAUDE, tmp_path)
    installed.write_text(installed.read_text() + "\nlocal change\n")
    result = uninstall_skill(Provider.CLAUDE, tmp_path)
    assert result == "modified_retained"
    assert installed.exists()
```

- [ ] **Step 2: Run tests and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_skills.py -q
```

Expected: collection FAIL.

- [ ] **Step 3: Write the provider skill assets**

Both skills instruct the provider to:

1. use the current native session ID when exposed;
2. otherwise list recent current-repository sessions and confirm concurrency;
3. run `agent-relay capture <provider> --session <id>`;
4. print the exact `agent-relay start <destination> --capsule <id>` command;
5. avoid nested launch unless the user explicitly requests it;
6. repeat the fidelity receipt without claiming KV-cache transfer.

Include an ownership header with asset version and SHA-256.

- [ ] **Step 4: Implement transactional install and uninstall**

Package assets with Hatchling. Install through a sibling temporary file and atomic
rename. Refuse unowned targets. Uninstall only when ownership marker and digest
match an installed asset; retain modified files.

- [ ] **Step 5: Wire commands and run tests**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_skills.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit skills**

```sh
git add agent-relay/src/agent_relay/skills.py agent-relay/src/agent_relay/assets agent-relay/src/agent_relay/cli.py agent-relay/pyproject.toml agent-relay/tests/test_skills.py
git commit -m "feat: install provider handoff skills"
```

---

### Task 16: Add distribution, end-to-end, and user documentation

**Conductor:** `docs` plus `tests`, Terra/medium, owned paths limited to this task.

**Files:**
- Create: `agent-relay/tests/test_distribution.py`
- Create: `agent-relay/tests/e2e_smoke.sh`
- Create: `agent-relay/scripts/finalize_sbom.py`
- Modify: `agent-relay/tests/helpers.py`
- Modify: `agent-relay/README.md`
- Modify: `agent-relay/CHANGELOG.md`
- Modify: `agent-relay/Makefile`
- Modify: `agent-relay/AGENTS.md`

- [ ] **Step 1: Write a failing wheel contract**

```python
@pytest.mark.distribution
def test_built_wheel_contains_cli_and_skill_assets(tmp_path: Path) -> None:
    wheel = build_wheel(tmp_path)
    names = wheel_names(wheel)
    assert "agent_relay/cli.py" in names
    assert "agent_relay/assets/codex/SKILL.md" in names
    assert "agent_relay/assets/claude/SKILL.md" in names
```

- [ ] **Step 2: Run the distribution test and observe failure**

Run:

```sh
cd agent-relay
.venv/bin/python -m pytest tests/test_distribution.py -m distribution -q
```

Expected: FAIL until build helpers and package-data configuration are complete.

- [ ] **Step 3: Add the end-to-end fake-provider script**

The shell script creates a temporary repository and provider roots, writes one
Codex and one Claude fixture, captures latest and selected sessions, verifies
capsules, runs fake direct and reference launches, checks blocked sensitive and
unknown-capacity cases, and verifies `gc` preview makes no changes.

Run commands through `"$PYTHON" -m agent_relay`; never require provider credentials.

- [ ] **Step 4: Complete package documentation**

Document:

- exact versus unavailable state;
- archival versus active-view replay;
- latest and selected-session examples;
- all CLI commands and exit codes;
- strict capacity and sensitive-data acknowledgements;
- capsule storage and cleanup;
- skill behavior;
- no KV-cache or hidden-state claim;
- troubleshooting for unsupported CLI versions and moved repositories.

- [ ] **Step 5: Add full package gates**

Extend the Makefile with:

```make
.PHONY: audit distribution e2e sbom

audit:
	$(PYTHON) -m pip_audit

distribution:
	$(PYTHON) -m pytest -m distribution -q
	$(PYTHON) -m build --no-isolation
	$(PYTHON) -m twine check dist/*.whl dist/*.tar.gz

e2e:
	PYTHON=$(PYTHON) bash tests/e2e_smoke.sh

sbom:
	uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file build/runtime-requirements.txt --quiet
	uv venv --clear --python 3.13 build/sbom-venv
	uv pip install --link-mode=copy --python build/sbom-venv -r build/runtime-requirements.txt dist/*.whl
	uv run cyclonedx-py environment build/sbom-venv --pyproject pyproject.toml --mc-type library --output-reproducible --of JSON --output-file sbom.cdx.json
	uv run --offline --no-project --python build/sbom-venv python scripts/finalize_sbom.py --input sbom.cdx.json --distribution agent-relay
```

Copy the tested SBOM finalizer pattern from the existing packages and change only
the accepted distribution name to `agent-relay`.

- [ ] **Step 6: Run package verification**

Run:

```sh
cd agent-relay
uv lock --check
make check PYTHON=.venv/bin/python
make distribution PYTHON=.venv/bin/python
make e2e PYTHON=.venv/bin/python
make audit PYTHON=.venv/bin/python
make sbom PYTHON=.venv/bin/python
```

Expected: all commands PASS and coverage is at least 90%.

- [ ] **Step 7: Commit documentation and release tests**

```sh
git add agent-relay
git commit -m "docs: complete agent relay package"
```

---

### Task 17: Integrate Agent Relay into monorepo CI and governance

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`
- Modify: `AGENTS.md`
- Modify: `tests/test_release_contract.py`

- [ ] **Step 1: Extend root tests before CI**

Add assertions that `agent-relay` appears in quality, test, coverage, distribution,
end-to-end, and supply-chain CI matrices; that the coverage source is
`agent_relay`; that its distribution name is `agent-relay`; and that its lockfile
is tracked.

- [ ] **Step 2: Run the root contract and observe CI-matrix failure**

Run:

```sh
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: FAIL with missing `agent-relay` CI matrix entries.

- [ ] **Step 3: Update CI matrices**

Add `agent-relay` to quality, three-platform test, coverage, distribution,
end-to-end, and supply-chain jobs. Keep action SHAs pinned, checkout credentials
disabled, project-specific uv cache keys, unique artifact names, 90% coverage, and
the existing build/SBOM isolation.

- [ ] **Step 4: Update governance documentation**

Change the root README from four to five tools and include install/develop/license
links. Add the new independent package and exact verification commands to root
`AGENTS.md` and `CONTRIBUTING.md`. Do not add a publishing workflow; the initial
scope is a tested local distribution, not a PyPI release.

- [ ] **Step 5: Run root and workflow contracts**

Run:

```sh
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit monorepo integration**

```sh
git add .github/workflows/ci.yml README.md CONTRIBUTING.md AGENTS.md tests/test_release_contract.py
git commit -m "ci: verify agent relay package"
```

---

### Task 18: Run final verification and frontier review

**Files:**
- Modify only files required by concrete failures discovered in this task.

- [ ] **Step 1: Verify the working tree and lockfile**

Run:

```sh
git status --short
cd agent-relay
uv lock --check
```

Expected: no unexplained files and lockfile check PASS.

- [ ] **Step 2: Run the complete Agent Relay gate**

Run:

```sh
cd agent-relay
make check PYTHON=.venv/bin/python
make distribution PYTHON=.venv/bin/python
make e2e PYTHON=.venv/bin/python
make audit PYTHON=.venv/bin/python
make sbom PYTHON=.venv/bin/python
```

Expected: formatting, lint, strict Pyright, tests, 90% branch coverage, build,
distribution tests, end-to-end smoke test, dependency audit, and reproducible SBOM
generation all PASS.

- [ ] **Step 3: Run the monorepo contract**

Run:

```sh
cd ..
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: PASS.

- [ ] **Step 4: Audit the implemented fidelity claims**

Run:

```sh
rg -n "exact transfer|KV cache transferred|fully loaded|seamless resume" agent-relay
rg -n "TODO|TBD|FIXME|pass$|NotImplemented" agent-relay/src agent-relay/tests
```

Expected: no unqualified transfer claims and no incomplete implementation markers.
Any documentation occurrence must explicitly deny the claim.

- [ ] **Step 5: Review security-sensitive boundaries at the frontier tier**

Inspect the actual diff for:

- symlink and path traversal rejection;
- raw-byte hashes independent from normalized JSON;
- atomic publication and immutable capsules;
- Windows/POSIX owner-only storage;
- shell-disabled provider launch;
- secret values absent from output and receipts;
- capacity/reference acknowledgements before launch;
- no provider-side loading claim;
- `gc` live-process and exact-target validation.

Fix only concrete findings, rerun the affected focused tests, and make one
descriptive commit per fix.

- [ ] **Step 6: Run the final Conductor report**

Run:

```sh
cd ..
PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last
```

Expected: a routing ledger with every delegated task recorded with model and
reasoning effort. Include the table in the user handoff.

- [ ] **Step 7: Close verification without an ambiguous catch-all commit**

If Step 5 finds a defect, mark this task incomplete, return to the task that owns
the affected file, add a focused regression test there, and use that task's exact
test and commit sequence. If Step 5 finds no defect, create no commit.
