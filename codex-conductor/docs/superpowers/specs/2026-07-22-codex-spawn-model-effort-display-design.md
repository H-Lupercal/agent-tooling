# Codex Spawn Model and Effort Display

**Date:** 2026-07-22
**Status:** Approved design, pending implementation plan

## Purpose

Make lower-model Codex delegation visible to the user at spawn time. When
Conductor approves a routed spawn that is eligible for savings, Codex CLI and
the Codex VS Code extension should show the selected worker model, reasoning
effort, and task.

The display is informational only. It must not change whether work is allowed,
which model or effort is selected, how reservations are accounted for, or how
Codex names the child agent.

## Current behavior

Codex requires the calling model to provide `task_name` to `spawn_agent`, but
the runtime separately assigns an agent nickname. The CLI spawn event and the
VS Code "Created ..." activity row use runtime agent metadata, so a task-naming
convention cannot reliably expose model and effort in both clients.

The Codex `PreToolUse` hook response supports a top-level `systemMessage`. Codex
surfaces that message in its UI or event stream, giving Conductor one supported
cross-client display mechanism without patching the CLI or extension.

## User-visible behavior

Immediately before an eligible child is spawned, show one line in both Codex
CLI and VS Code:

```text
Spawning gpt-5.6-terra · high · tests_ledger
```

The format is fixed:

```text
Spawning <model> · <reasoning-effort> · <task>
```

The notice appears only when all of these conditions hold:

- the provider is Codex;
- the operation is a new agent spawn;
- Conductor approved the operation;
- the active run is in routing mode; and
- the approved decision is savings-eligible, which is Conductor's existing
  indication that the routed worker is genuinely cheaper than the caller.

No notice appears for denied operations, same-model workers, non-spawn agent
operations, admission or observe mode, or ungoverned tools.

## Data flow

The existing policy and atomic reservation transaction remain authoritative.
After `decide()` returns an approved, savings-eligible spawn decision, the hook
uses the decision's reservation identifier to read the committed reservation.

The display fields come from existing authoritative state and normalized input:

- model: committed reservation model;
- reasoning effort: committed reservation reasoning effort; and
- task: the validated Conductor task envelope, which is the same task name used
  to create the reservation.

The hook formats those values and asks the Codex provider to add the notice to
the already-generated allow response. The provider emits the notice as the
documented top-level `systemMessage`; the permission decision remains `allow`.

The provider boundary should expose a small response-decoration method with a
default no-op implementation. The Codex provider overrides it to add the
supported field. This keeps Codex response syntax out of the shared hook and
leaves a clean seam for separate Claude work without changing Claude behavior
in this implementation.

## Failure handling

Display enrichment is best-effort and must never become an admission gate. If
the reservation cannot be reread, required display metadata is absent, or the
notice cannot be formatted, Conductor emits the original allow response without
the notice and records a bounded diagnostic. It does not deny or retry the
spawn.

Existing fail-closed behavior before a policy decision is unchanged. Denial
responses and their reasons are unchanged.

## Scope boundaries

This change does not:

- alter routing, policy evaluation, ceilings, task classes, or model selection;
- modify reservation or accounting schemas;
- rename agents or tasks;
- patch the Codex CLI or VS Code extension;
- add a second post-spawn lifecycle message; or
- implement the Claude provider's display behavior.

The Claude implementation is a separate provider-specific change. It must
verify Claude's current CLI, extension, hook response, and effective-effort
metadata rather than copying Codex response fields.

## Testing

Automated tests will establish that:

1. an approved savings-eligible Codex spawn adds exactly the expected
   `systemMessage` while retaining `permissionDecision: allow`;
2. the notice uses the committed reservation's model, effort, and task;
3. same-model, denied, non-spawn, admission-mode, and observe-mode operations do
   not add a notice;
4. a display-enrichment failure preserves the original allow response;
5. existing Codex denial output remains byte-for-byte compatible; and
6. Claude provider output remains unchanged.

Implementation verification will run the Conductor project gates required by
the repository contract:

```sh
make check PYTHON=.venv/bin/python
make dist-test PYTHON=.venv/bin/python
make e2e PYTHON=.venv/bin/python
```

The run will finish with the required Conductor report command from the
monorepo root.
