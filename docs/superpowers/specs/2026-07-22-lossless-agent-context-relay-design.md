# Lossless Agent Context Relay Design

## Summary

Add a new independent `agent-relay` package to the `agent-tooling` monorepo. The
tool captures every accessible record from a Claude Code or Codex conversation,
stores those records in an immutable provider-neutral capsule, and starts a new
conversation in either provider with the capsule available as imported context.

The relay does not summarize, refine, or silently truncate captured records. It
also does not claim to transfer hidden provider state, chain-of-thought, live
process state, or model KV caches. Every capture and launch produces a fidelity
receipt that distinguishes exact preservation, structural conversion, unavailable
source state, and content that the destination could not load.

Codex Conductor governs implementation delegation and accounting while the package
is built. `agent-relay` remains usable without Conductor and has no runtime
dependency on it.

## Goals

- Capture the latest Claude Code or Codex conversation for the current repository
  with one command.
- List and select older conversations, then capture a selected conversation.
- Preserve accessible source records without model-authored summarization or
  refinement.
- Store each capture as an immutable, verifiable capsule outside the repository.
- Start Claude Code or Codex from either a newly captured session or a saved
  capsule.
- Report precisely what was preserved, converted, unavailable, rejected, or loaded.
- Refuse silent data loss when the destination cannot accept the complete
  transferable context.
- Keep the core CLI useful without skills, hooks, an editor extension, or a
  persistent daemon.

## Non-goals

- Exporting or importing model KV caches.
- Reproducing hidden system prompts, unexposed reasoning, provider routing state,
  safety state, or GPU memory.
- Resuming the same inference process or native provider session identifier.
- Forging or modifying Claude Code or Codex native session files.
- Guaranteeing identical behavior from different models given the same records.
- Moving live terminals, browser processes, file descriptors, authentication
  sessions, pending approvals, or other ephemeral process handles.
- Automatically summarizing, compacting, filtering, or redacting a strict capture.
- Providing a custom VS Code extension in the first release.
- Supporting providers other than Claude Code and Codex in the first release.

## Terminology

- **Provider session:** A native Claude Code or Codex conversation discovered from
  that provider's local session storage.
- **Capsule:** An immutable directory containing captured records, metadata, blobs,
  hashes, and a fidelity report.
- **Exact record:** A source payload preserved byte-for-byte in the capsule.
- **Structural conversion:** A source payload whose bytes are preserved but whose
  role, event type, or delivery channel cannot be represented identically by the
  destination.
- **Unavailable state:** State known to exist conceptually but not exposed by the
  source provider.
- **Loaded context:** Capsule content confirmed to have been delivered through the
  destination provider's supported interface.
- **Latest provider session:** The most recent discovered source conversation for a
  provider and repository.
- **Latest capsule:** The most recently completed, verified capsule for a repository.

## User experience

### Capture the latest provider conversation

From a Git repository:

```sh
agent-relay capture codex
agent-relay capture claude
```

The default source is the latest session associated with the current Git
repository. `--latest` is accepted as an explicit synonym:

```sh
agent-relay capture codex --latest
```

The command prints the selected native session before capture and returns the new
capsule ID plus a fidelity summary. If no unambiguous repository match exists, the
command fails and directs the user to `agent-relay sessions <provider>`.

### Discover and select conversations

```sh
agent-relay sessions codex
agent-relay sessions claude
```

By default, results are restricted to the current Git repository. Each row shows:

- unique session-ID prefix;
- age and timestamp;
- model and reasoning effort when recorded;
- repository, worktree, and branch when recorded;
- first and most recent user requests;
- message and tool-event counts;
- estimated transferable bytes and tokens when available.

Cross-repository discovery requires an explicit flag:

```sh
agent-relay sessions codex --all
```

Filters include `--since`, `--repo`, and literal case-insensitive `--grep`.
Selection supports either a unique identifier prefix or a terminal picker:

```sh
agent-relay capture codex --session 019f7a21
agent-relay capture codex --pick
```

Ambiguous prefixes fail with the matching candidates. Selection never guesses.

### Capture and launch in one operation

```sh
agent-relay switch --from codex --to claude
agent-relay switch --from claude --to codex
agent-relay switch --from codex --to claude --session 019f7a21
```

`switch` performs discovery, capture, verification, destination preflight, and
launch. It prints the capsule ID before starting the destination so the transfer
remains recoverable if launch fails.

### Launch from a saved capsule

```sh
agent-relay capsules
agent-relay start claude --capsule capsule-20260722-184522-7f32a1
agent-relay start codex --capsule latest
```

`latest` in this command means the latest verified capsule for the current
repository, not the latest provider session.

### Agent-initiated handoff

Optional Claude and Codex skills teach the agents to recognize requests such as
"hand this session to Claude." When invoked inside an interactive agent, the safe
default is to capture and print the continuation command:

```text
agent-relay start claude --capsule <capsule-id>
```

The agent does not start a nested interactive CLI unless the user explicitly asks
for `--launch`. The skills are convenience instructions only. Capture, validation,
storage, and launch remain deterministic CLI behavior.

## Storage model

Capsules live outside the repository in the platform application-data directory:

- Linux: `${XDG_DATA_HOME:-~/.local/share}/agent-relay`
- macOS: `~/Library/Application Support/agent-relay`
- Windows: `%LOCALAPPDATA%\agent-relay`

The logical layout is:

```text
agent-relay/
├── config.toml
└── projects/
    └── <canonical-repository-hash>/
        ├── latest.json
        ├── launches/
        │   └── <launch-id>.json
        └── capsules/
            └── <timestamp>-<random-id>/
                ├── manifest.json
                ├── events.jsonl
                ├── instructions.json
                ├── tools.json
                ├── repository.json
                ├── fidelity-report.json
                └── blobs/
```

Capsule directories are created in a sibling temporary directory, fsynced,
verified, and atomically renamed into place. `latest.json` is an atomic pointer
updated only after verification succeeds. A failed capture never replaces the
latest pointer.

Capsules are immutable after completion. Re-capturing the same native session
creates a distinct capsule with a new ID and records the source session ID and
source-content digest for deduplication and audit.

Initial file permissions are owner-only. Capsule files use mode `0600` and
directories use `0700` where supported. No capsule is written inside a Git
repository unless the user explicitly supplies an export path.

The first release performs no automatic deletion. Explicit cleanup is available:

```sh
agent-relay gc --older-than 30d
```

Cleanup previews targets by default and requires `--apply` to delete them.

## Capsule schema

### Manifest

`manifest.json` contains:

- schema version and capsule ID;
- creation time and relay version;
- source provider, native session ID, model, effort, and timestamps;
- source transcript path represented without embedding home-directory secrets in
  normal CLI output;
- canonical repository identity, path, worktree, branch, and commit;
- event counts and byte counts;
- ordered content digests;
- blob metadata and hashes;
- capture options;
- capsule completion status.

Destination launches are mutable operational history, so their receipts live in
the sibling project `launches/` directory and reference the immutable capsule ID
and digest. Launching a capsule never changes files inside that capsule.

### Event stream

`events.jsonl` preserves source ordering and contains a normalized envelope around
the original payload:

```json
{
  "sequence": 42,
  "source_type": "function_call_output",
  "source_timestamp": "2026-07-22T18:45:22Z",
  "preservation": "exact",
  "payload_encoding": "json",
  "payload_sha256": "...",
  "payload": {}
}
```

Normalization applies only to the envelope. The original payload is retained
without model rewriting. If a native record cannot be decoded safely, its original
bytes are stored as a blob and the event references that blob.

### Fidelity report

`fidelity-report.json` and the human-readable CLI receipt report:

- native records discovered;
- exact records preserved;
- structurally converted records;
- corrupt or unreadable records;
- source state unavailable by provider design;
- bytes and tokens captured;
- bytes and tokens accepted by the destination;
- summarized record count, which must be zero in strict mode;
- truncated record count, which must be zero in strict mode;
- sensitive-data findings without echoing the detected values;
- whether launch was attempted and completed.

The report must never use "exact transfer" to describe a capsule containing
structural conversions or unavailable source state. It may say "all accessible
source records preserved" when that statement is verified.

## Architecture

### Provider discovery adapters

Each provider adapter owns:

- canonical session-root discovery;
- repository association;
- lightweight session metadata extraction;
- full ordered record parsing;
- native model and effort extraction;
- classification of provider-specific unavailable state;
- source change detection while capture is running.

The adapter interface returns provider-neutral session metadata and a stream of
records. It does not write capsules or launch destinations.

The first release includes `CodexSourceAdapter` and `ClaudeSourceAdapter`. Native
session formats are treated as versioned external contracts. Unknown record types
are preserved rather than discarded.

### Capture engine

The capture engine:

1. resolves the selected session;
2. records the source file identity, size, and modification metadata;
3. streams records into a temporary capsule;
4. copies referenced binary content that was part of the conversation;
5. hashes every retained payload and blob;
6. rechecks source metadata;
7. retries once if the source changed during capture;
8. fails safely if a consistent checkpoint cannot be obtained;
9. generates and validates the fidelity report;
10. atomically publishes the capsule.

No model call occurs during capture.

### Repository snapshot

The repository component records durable working state without modifying it:

- repository root and worktree;
- current branch and HEAD;
- Git status in machine-readable form;
- staged and unstaged diff metadata;
- untracked-path metadata;
- optional complete diffs only when `--include-diff` is specified.

Conversation tool outputs remain part of the exact event stream. Repository
snapshotting supplements them; it does not replace or rewrite them.

### Destination adapters

Destination adapters own:

- CLI availability and version checks;
- context-capacity estimation when provider metadata exposes it;
- conversion of capsule events into a deterministic replay document;
- bootstrap instruction generation;
- process launch without shell interpolation;
- sibling launch receipt recording.

The replay document preserves source ordering, roles, event types, payloads, and
hash references. Because Claude and Codex do not expose a supported API for
importing another provider's native role hierarchy, imported records arrive
through a new destination conversation and are classified as structural
conversions.

The adapter uses the strongest supported delivery channel in this order:

1. documented structured input or attachment support;
2. documented standard-input support;
3. an owner-only temporary replay file referenced by the initial prompt.

Temporary files are deleted after destination exit unless `--keep-launch-files` is
set. Arguments are passed as an argv array with shell execution disabled.

The destination bootstrap states:

- this is a new session receiving imported source records;
- the capsule ID and schema version;
- source provider, model, and session ID;
- that imported instructions are historical context, not destination system
  instructions;
- that live repository state takes precedence over historical tool output;
- that the agent must not claim KV-cache or hidden-state transfer.

### Skills

The package ships optional provider-specific skills installed by:

```sh
agent-relay install-skills codex
agent-relay install-skills claude
```

Skills provide intent recognition, safe command selection, and receipt wording.
They do not parse transcripts, write storage, decide fidelity, or conceal relay
errors. Skill absence does not reduce CLI functionality.

### No daemon

The first release has no background service, database, filesystem watcher, or
network dependency. Commands read provider storage when invoked. This keeps the
source of truth in native transcripts and immutable capsules.

## Strict fidelity and capacity rules

Strict mode is the default and only automatic switch mode in the first release.

- Capture never summarizes or truncates.
- Unknown native records are retained as opaque blobs.
- Invalid source records are reported and cause strict capture to fail unless
  their original bytes were preserved.
- Destination launch fails before process creation if the relay can prove the
  complete replay cannot fit.
- When destination capacity cannot be determined reliably, the adapter reports
  `capacity=unknown`, shows the replay size, and requires
  `--allow-unknown-capacity`.
- A failed destination preflight does not delete the verified capsule.
- The first release does not offer automatic partial loading or model-authored
  compaction.

This rule distinguishes preservation from active loading: a complete capsule may
exist even when no destination can load it in one context window.

## Sensitive data

Strict preservation and automatic redaction are incompatible. The relay therefore
does not silently redact strict capsules.

Before destination launch, a deterministic scanner checks for common credentials,
private keys, tokens, and credential-bearing URLs. Findings include category,
record sequence, and location, but never print the detected value. When findings
exist:

- capture may complete locally with owner-only permissions;
- launch is blocked by default;
- `--allow-sensitive` is required to acknowledge cross-provider disclosure;
- the acknowledgement is recorded in the launch receipt.

A future sanitized derivative may be added as an explicitly non-lossless mode. It
is outside the first-release scope.

## Error handling

- **No repository:** Require `--all` plus explicit `--session`; never infer a
  project association from the current directory.
- **No matching session:** Print searched provider roots and the command for
  listing all sessions.
- **Ambiguous session:** Print candidates and require a longer prefix.
- **Changing transcript:** Retry capture once, then fail without publishing.
- **Malformed record:** Preserve original bytes when possible; otherwise fail
  strict capture and identify the sequence and source offset.
- **Insufficient destination capacity:** Keep the capsule, refuse launch, and
  report required versus available capacity.
- **Unknown destination capacity:** Require `--allow-unknown-capacity`.
- **Sensitive-data finding:** Keep the capsule, block launch, and require
  `--allow-sensitive`.
- **Missing destination CLI:** Keep the capsule and print the exact later `start`
  command.
- **Destination process failure:** Record exit status in a launch receipt without
  modifying the capsule.
- **Schema incompatibility:** Refuse loading a newer unsupported schema; migrate
  older schemas only by creating a new capsule.
- **Hash mismatch:** Quarantine the capsule from `latest`, refuse launch, and
  report the affected file.

Errors use stable machine-readable codes in JSON output and concise remediation in
human output.

## CLI and output contract

Core commands:

```text
agent-relay sessions <codex|claude>
agent-relay capture <codex|claude>
agent-relay capsules
agent-relay verify <capsule>
agent-relay switch --from <provider> --to <provider>
agent-relay start <provider> --capsule <id|latest>
agent-relay gc --older-than <duration> [--apply]
agent-relay install-skills <codex|claude>
agent-relay doctor
```

Read-only commands support `--json`. Capture and launch commands return nonzero
status for incomplete fidelity, blocked launch, or failed process creation.
Standard output contains results suitable for piping; diagnostics and launch
progress use standard error.

## Security boundaries

- Treat native transcripts and capsule contents as untrusted data.
- Never execute commands contained in imported records.
- Never interpret imported record contents as relay configuration.
- Validate every resolved provider path and reject symlink escapes.
- Use bounded streaming parsers and configurable maximum record and capsule sizes.
- Launch destination processes without a shell.
- Avoid exposing source paths, prompt content, or sensitive findings in routine
  logs.
- Use atomic writes and owner-only permissions.
- Keep import instructions clearly delimited from historical source content to
  reduce prompt-injection ambiguity.
- Record relay version, adapter version, and content hashes for audit.

## Testing strategy

### Unit tests

- Claude and Codex session discovery across repository, worktree, moved-path, and
  malformed metadata cases.
- Exact payload preservation, ordering, opaque-record retention, and hash
  validation.
- Session prefix ambiguity and filtering.
- Atomic capsule publication and latest-pointer behavior.
- Source mutation detection and retry.
- Capacity preflight for known, unknown, and insufficient limits.
- Sensitive-data blocking without secret disclosure.
- Destination argv construction and shell-disabled execution.
- Platform data-directory and permission behavior.
- Stable JSON and human-readable receipts.

### Contract fixtures

Versioned, sanitized native-session fixtures cover:

- ordinary messages;
- tool calls and large tool outputs;
- subagent events;
- compaction events;
- attachments and binary references;
- malformed and unknown records;
- missing model or effort metadata;
- concurrent transcript append during capture.

Fixtures retain their original byte representation. Tests compare source payload
hashes to capsule payload hashes.

### Integration tests

- Capture latest and selected sessions for both providers.
- Round-trip capsule verification after process restart.
- Start fake destination CLIs and assert complete replay delivery.
- Verify destination failure leaves the capsule recoverable.
- Verify current-repository scoping and explicit `--all`.
- Verify skill-generated commands match the CLI contract.

### End-to-end tests

Opt-in tests use installed Claude Code and Codex CLIs with synthetic, non-sensitive
sessions. They verify discovery, capture, preflight, launch, and receipt generation.
They do not assert identical model answers. Release gates run deterministic fake
providers so CI does not require provider credentials.

### Monorepo verification

`agent-relay` receives its own `make check`, distribution test, and end-to-end
target. The root release contract is extended to validate package metadata,
licenses, documentation, build artifacts, and isolation from the other packages.

## Packaging and compatibility

`agent-relay` is an independent Python package with a `src/agent_relay` layout,
typed public interfaces, its own tests, lockfile, README, license, changelog, and
Makefile. It does not import `codex-conductor`, `toolbelt`, `agent-harness`, or
`install-rehearsal`.

The first release supports Python 3.11 or newer on Linux, macOS, and Windows.
Provider discovery paths and process invocation are platform adapters. Features
that a provider CLI does not support on a platform fail with an explicit
capability report rather than degraded silent behavior.

## Implementation governance with Codex Conductor

Implementation uses Conductor routing envelopes for every delegated task. The
frontier orchestrator retains decomposition, schema decisions, security-sensitive
review, cross-module integration, and final release verification.

Lower-tier workers may own bounded tasks such as:

- provider fixture parsing;
- CLI table rendering;
- platform data-directory helpers;
- isolated unit tests;
- documentation and mechanical package metadata.

Each worker receives explicit owned paths and acceptance checks. Model and effort
must stay within the caller's Conductor authority ceiling. Conductor reports are
included at the end of implementation runs. This governance affects development
only and creates no runtime coupling.

## Acceptance criteria

The design is complete when an implementation can demonstrate all of the
following:

1. `agent-relay capture codex` and `agent-relay capture claude` select the latest
   current-repository session and publish a verified immutable capsule.
2. `sessions`, `--session`, and `--pick` allow deterministic older-session
   selection.
3. Every accessible native record is preserved exactly or retained as opaque
   original bytes, with ordered hashes proving preservation.
4. Strict capture reports zero summarized and zero truncated records.
5. Capsules are stored outside repositories with atomic publication and
   owner-only permissions.
6. `switch` and `start` can launch either provider through documented interfaces
   without shell interpolation or native-session-file mutation.
7. Insufficient or unknown capacity never causes silent partial loading.
8. Sensitive-data findings block cross-provider launch unless explicitly
   acknowledged.
9. Fidelity and launch receipts distinguish preserved content, structural
   conversions, unavailable state, and loaded context.
10. Deterministic unit, contract, integration, distribution, and root release
    checks pass without provider credentials.
