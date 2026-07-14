# Agent Harness

Agent Harness is a local-first, provider-independent collaboration runtime for coding
agents. It gives a user-configured group of agents one durable conversation, permits
overlapping responses and evidence-backed interruption, and records an exact event history
that can be shown, exported, or resumed after a crash.

The foundation release uses deterministic fake participants so the orchestration and
recovery model can be exercised without credentials or network access. It does **not yet
execute live model providers or coding CLIs**. Those adapters will implement the same
participant protocol in a later slice.

## Quick start

Agent Harness requires Python 3.11 or newer. From this directory:

```sh
python -m pip install -e .
mkdir harness-demo
cd harness-demo
agent-harness init
agent-harness doctor
agent-harness --store .harness-state run "compare two implementation strategies" --fake
```

The run prints a `run_id`. Use it in the remaining commands:

```sh
agent-harness --store .harness-state show RUN_ID
agent-harness --store .harness-state export RUN_ID receipt.jsonl
agent-harness --store .harness-state resume RUN_ID --fake
```

`resume` is only valid for an incomplete run. It restores the persisted roster, child
lineage, selected child context, participant state, and consumed token budget; it does not
add newly configured participants. Persisted root settings must still match the project
configuration. Completed, failed, aborted, incomplete-metadata, and configuration-drift
histories are refused with exit code 3.

These commands and paths work on Linux, macOS, and Windows; shell syntax for creating or
changing directories may vary. Python and SQLite provide the runtime portability.

## Configuration

`agent-harness init` creates `agent-harness.toml` in the current directory and refuses to
overwrite an existing file. The strict parser rejects unknown settings, duplicate participant
IDs, invalid capacities, and a root roster larger than `max_participants`. Credentials may
only be referenced by environment-variable name; credential values never belong in the file.

The participant count is not capped at three. `max_participants` is an explicit project
capacity, and admitted children are additionally governed by total child count, per-parent
count, spawn depth, simultaneous speakers, and token budget.

## Trust boundaries

- The SQLite event store is the source of truth. Events are persisted before subscribers see
  them, and portable receipts contain the same canonical events in sequence order.
- Message events contain text an agent deliberately publishes to the room. Hidden chain of
  thought or provider-internal reasoning is neither requested nor stored.
- Interruptions describe a reason and require evidence at urgent priority. The event log
  records both the request and how it was applied. A hard interruption prevents any remaining
  chunks from being published as a completed response.
- A dynamic child has its own identity, role, selected context, and budget. Because it shares
  lineage with its parent, it does not count as an independent reviewer in the later consensus
  layer. An admitted child actively responds; adapter construction or execution failures are
  retained as `participant.degraded` events without erasing lineage.
- The foundation fake adapter is for deterministic tests and demonstrations, not simulated
  proof that a live provider completed work.

See [architecture](docs/architecture.md) for data flow and component boundaries and
[tool activity](docs/tool-activity.md) for the implementation-tool evidence ledger.

## Development

```sh
uv sync --extra dev --locked
uv lock --check
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```

The package has no runtime dependencies outside the Python standard library.
