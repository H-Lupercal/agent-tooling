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
source state, direct transport, reference-only availability, and rejected launch.

Codex Conductor governs implementation delegation and accounting while the package
is built. `agent-relay` remains usable without Conductor and has no runtime
dependency on it.

## Resolved design decisions

- The distribution and command are named `agent-relay`; the Python import package
  is `agent_relay`.
- Version one supports Claude Code and Codex on Python 3.11 or newer across Linux,
  macOS, and Windows.
- The relay is an on-demand CLI with immutable filesystem capsules. It has no
  daemon, database, custom editor extension, or relay-originated network call.
- Raw native record bytes are authoritative. Parsed or reserialized JSON is never
  evidence of exact preservation.
- Latest-session discovery is repository-scoped. Cross-repository capture always
  requires explicit selection.
- Capsules contain the complete accessible archival stream. Destination replay
  uses the provider-exposed active view when deterministic, otherwise a clearly
  labeled archival fallback.
- Referenced subagent transcripts are auxiliary data and are not injected into a
  strict parent replay.
- Strict capture never summarizes, redacts, filters, or truncates. Size limits fail
  closed.
- Strict automatic switching requires a tested direct-input channel. File-reference
  import and unknown capacity each require a separate explicit acknowledgement.
- Sensitive data is preserved locally under owner-only permissions. Cross-provider
  launch is blocked until explicitly acknowledged.
- Capsules are never overwritten and are never deleted automatically. Cleanup is
  preview-only unless `gc --apply` is provided.
- Skills are optional convenience layers. The CLI owns every correctness and
  security decision.
- Conductor governs development delegation only; it is not a runtime dependency.

## Goals

- Capture the latest Claude Code or Codex conversation for the current repository
  with one command.
- List and select older conversations, then capture a selected conversation.
- Preserve accessible source records without model-authored summarization or
  refinement.
- Store each capture as an immutable, verifiable capsule outside the repository.
- Start Claude Code or Codex from either a newly captured session or a saved
  capsule.
- Report precisely what was preserved, converted, unavailable, transported,
  reference-only, or rejected.
- Refuse silent data loss when the destination cannot accept the complete
  transferable context.
- Keep the core CLI useful without skills, hooks, an editor extension, or a
  persistent daemon.

## Non-goals

- Exporting or importing model KV caches.
- Reproducing hidden system prompts, unexposed reasoning, provider routing state,
  safety state, or GPU memory.
- Claiming that an append-only native transcript equals the model's current active
  prompt when the provider does not expose prompt assembly or compaction state.
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
- **Exact record:** The original byte range for a complete native source record,
  preserved without reserialization in the capsule's `raw/` directory and verified
  by digest.
- **Structural conversion:** A source payload whose bytes are preserved but whose
  role, event type, or delivery channel cannot be represented identically by the
  destination.
- **Unavailable state:** State known to exist conceptually but not exposed by the
  source provider.
- **Transported input:** Replay bytes handed to a documented destination CLI input
  channel without local truncation. This proves process-level delivery only; it
  does not prove how the hosted model processed or retained those bytes.
- **Reference import:** A destination launch whose initial message contains a
  capsule or replay-file path. The records are available to the destination agent
  but are not claimed to be in active model context until the agent reads them.
- **Archival stream:** The complete, ordered, accessible native record history for
  the selected session.
- **Provider-exposed active view:** The subset or transformed view that native
  records explicitly identify as active after compaction. This exists only when
  the provider format exposes enough information to derive it deterministically.
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
- exact transferable bytes, plus a native token count when recorded; otherwise
  token count is displayed as `unknown`.

User-message previews are limited to 120 display characters, normalize control
characters, and mask detected credential values. JSON listing output contains the
same preview, not full message bodies. Full content is available only inside an
owner-readable captured capsule.

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
`--latest`, `--session`, and `--pick` are mutually exclusive. `--pick` requires an
interactive terminal and fails with a usage error otherwise. Capturing a session
outside the current repository requires both `--all` and an explicit `--session`;
`--all` never broadens automatic latest selection.

`--since` accepts an RFC 3339 UTC timestamp or an integer duration suffixed with
`m`, `h`, `d`, or `w`. `--repo` accepts a path and compares its canonical Git
identity. `--grep` searches user-message text only. `--session` accepts a full
native ID or a unique prefix of at least eight characters.

Repository association uses the canonicalized recorded session `cwd` and the
current repository's worktree and common Git directory. A session matches when its
recorded `cwd` equals the worktree root or is a descendant of it. Symlink aliases
are resolved before comparison. There is no fuzzy path or repository-name match.
A moved repository therefore requires `--all` and explicit selection.

"Latest" means the session with the greatest timestamp on its last complete native
record. Filesystem modification time is used only when a native record timestamp is
absent. If the best timestamp is tied or malformed, automatic selection fails and
requires `--session` or `--pick`.

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

When the current provider exposes its native session ID to the skill environment,
the skill passes that exact ID with `--session`. When it does not, the skill lists
current-repository sessions and requires confirmation if more than one session has
received a complete record within the last five minutes. It must not assume that
the newest concurrent session is itself.

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
        │   └── <launch-id>/
        │       ├── receipt.json
        │       └── replay.bin
        └── capsules/
            └── <timestamp>-<random-id>/
                ├── manifest.json
                ├── events.jsonl
                ├── instructions.json
                ├── tools.json
                ├── repository.json
                ├── fidelity-report.json
                ├── raw/
                └── blobs/
```

Capsule directories are created in a sibling temporary directory, fsynced,
verified, and atomically renamed into place. `latest.json` is an atomic pointer
updated only after verification succeeds. A failed capture never replaces the
latest pointer.

Publication and `latest.json` updates use a per-project advisory lock. Concurrent
captures are permitted to build temporary capsules in parallel, but publication is
serialized.
Every completed capsule remains addressable; `latest` points to the capsule whose
publication completed last. Lock acquisition times out after 10 seconds by
default; timeout failure does not publish a partial capsule.

Capsules are immutable after completion. Launch replay material and receipts are
stored under the sibling `launches/` directory because they are operational
derivatives, not captured source state. Re-capturing the same native session
creates a distinct capsule with a new ID and records the source session ID and
source-content digest for deduplication and audit.

Initial file permissions are owner-only. Capsule files use mode `0600` and
directories use `0700` on POSIX. Windows storage applies an owner-only discretionary
ACL and verifies the resulting ACL before publication. If owner-only protection
cannot be established, capture fails. No capsule is written inside a Git repository
unless the user explicitly supplies an export path.

The first release performs no automatic deletion. Explicit cleanup is available:

```sh
agent-relay gc --older-than 30d
```

Cleanup previews targets by default and requires `--apply` to delete them.
It refuses capsules referenced by a live launch receipt. Liveness checks validate
both process ID and recorded process start time to avoid PID-reuse mistakes.
Interrupted stale launch material is eligible only after the destination process
is confirmed absent.

`config.toml` uses these first-release defaults:

```toml
[limits]
max_record_bytes = 67108864
max_blob_bytes = 2147483648
max_capsule_bytes = 8589934592
lock_timeout_seconds = 10
```

Configuration overrides built-in defaults. Standard platform data-directory
variables choose only the storage root; the first release defines no
relay-specific environment-variable or command-line limit overrides. Crossing a
size limit fails capture or launch; it never clips content.

Capsule IDs use
`capsule-<UTC YYYYMMDDTHHMMSSZ>-<12 lowercase cryptographic-random hex chars>`.
All stored timestamps use RFC 3339 UTC with microsecond precision.

## Capsule schema

### Manifest

`manifest.json` contains:

- schema version and capsule ID;
- creation time and relay version;
- source provider, native session ID, model, effort, and timestamps;
- source transcript path represented without embedding home-directory secrets in
  normal CLI output;
- every captured source file's identity, snapshot boundary, size, digest, and role
  in the session graph;
- canonical repository identity, path, worktree, branch, and commit;
- event counts and byte counts;
- ordered content digests;
- blob metadata and hashes;
- capture options;
- capsule completion status.

Destination launches are mutable operational history, so their receipts live in
the sibling project `launches/` directory and reference the immutable capsule ID
and digest. Launching a capsule never changes files inside that capsule.

The manifest contains a lexicographically sorted inventory of every other capsule
file with its byte length and SHA-256 digest. The capsule digest is the SHA-256 of
the manifest's canonical UTF-8 JSON bytes, using sorted keys and no insignificant
whitespace. `latest.json` and launch receipts record that capsule digest.
Verification detects corruption and substitution relative to those recorded
digests; it is an integrity check, not proof against an attacker who can rewrite
the capsule and every local pointer.

### Event stream

`events.jsonl` preserves source ordering and contains a normalized index over the
authoritative original bytes:

```json
{
  "stream_id": "primary",
  "sequence": 42,
  "replay_scope": "primary",
  "source_type": "function_call_output",
  "source_timestamp": "2026-07-22T18:45:22Z",
  "preservation": "exact",
  "raw_ref": "raw/root-session.jsonl",
  "raw_offset": 4812,
  "raw_length": 917,
  "raw_sha256": "...",
  "normalized": {}
}
```

`sequence` is contiguous within `stream_id`; the manifest stores the parent-child
session graph rather than inventing a false total order across concurrent streams.
The `normalized` field is a non-authoritative search and replay index. Exactness is
proved from `raw_ref`, byte boundaries, and `raw_sha256`; JSON parsing and
reserialization are never treated as exact preservation. If a native record cannot
be decoded, its complete original byte range is still retained and indexed as an
opaque event. An incomplete trailing record is outside the capture boundary and is
reported, not stored as a complete event.

The capsule always contains the complete archival primary stream. The manifest
classifies active-view knowledge as:

- `explicit`: native records provide a complete deterministic active view;
- `reconstructed`: documented native compaction events permit deterministic
  reconstruction, but the provider does not expose its final serialized prompt;
- `unknown`: native records do not identify the active subset.

The default replay uses the provider-exposed active view for `explicit` or
`reconstructed` sessions. The complete archival stream is added as separately
delimited reference data only when `--include-archive` is specified. For `unknown`
sessions, the default replay is the complete archival primary stream and the
launch receipt states `source_active_view=unknown`. This is an unedited historical
replay, not a claim that the source model had all records simultaneously active.

### Fidelity report

`fidelity-report.json` and the human-readable CLI receipt report:

- native records discovered;
- exact records preserved;
- structurally converted records;
- corrupt or unreadable records;
- source state unavailable by provider design;
- active-view classification and replay source;
- bytes and tokens captured;
- replay bytes generated for a launch;
- destination transport class and bytes handed to the destination process;
- whether active model loading is unobservable, known incomplete, or rejected;
- summarized record count, which must be zero in strict mode;
- truncated record count, which must be zero in strict mode;
- sensitive-data findings without echoing the detected values;
- whether launch was attempted and completed.

The report must never use "exact transfer" to describe a capsule containing
structural conversions or unavailable source state. It may say "all accessible
source records preserved" when that statement is verified. Process-level transport
must not be described as proof that a hosted model loaded, attended to, or retained
the complete replay.

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

Each adapter builds an explicit session graph. The selected session is the
**primary stream**. Its replay contains only records represented in that native
stream. The capture closure additionally contains:

- the selected primary session transcript;
- child or subagent transcripts explicitly referenced by a captured native record;
- provider metadata files explicitly referenced by the selected session;
- binary attachments explicitly referenced as conversation inputs.

The adapter does not crawl neighboring session files, arbitrary project files, or
provider memory files merely because they share a directory. Project memory is
included only when the native transcript records that specific content or file as
loaded; otherwise its existence is reported as unverified auxiliary state.
Missing referenced content is reported as unavailable, while the native reference
record itself remains exactly preserved.

Related child transcripts are retained as separately identified auxiliary streams
for audit and later explicit selection. They are not flattened into the primary
replay because the parent model may have seen only a child result rather than the
child's internal conversation. A destination replay includes the primary stream
only. `--include-related` makes auxiliary streams available as separately
delimited reference material, is classified as added context, and is never enabled
by strict automatic switching.

### Capture engine

The capture engine:

1. resolves the selected session;
2. opens every session-graph source file and records its file identity;
3. fixes a snapshot boundary at the final complete native record visible at open
   time;
4. streams only bytes at or before those boundaries into a temporary capsule;
5. stores authoritative raw byte copies before building normalized indexes;
6. streams complete records into the event index;
7. copies explicitly referenced binary content that was part of the conversation;
8. hashes every retained raw file, record range, and blob;
9. verifies that each source file was not replaced, truncated, or modified before
   its snapshot boundary;
10. retries once if a stable prefix could not be obtained;
11. generates and validates the fidelity report;
12. atomically publishes the capsule.

No model call occurs during capture.

Native transcripts are expected to be append-oriented. Records appended after the
fixed snapshot boundary are intentionally excluded and counted in the receipt as
`appended_after_snapshot`; they do not invalidate the capture. Replacement,
truncation, or mutation of bytes inside the boundary does invalidate the attempt.
This allows a running Claude or Codex session to hand itself off without waiting
for the source process to exit.

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

The repository snapshot describes state at capsule-capture time, not historical
state at the time of every source event. Its timestamp and commit are explicit.
For a cross-repository `--all` capture, snapshotting occurs only when the selected
session's recorded repository still exists and can be resolved. Otherwise the
capsule retains recorded source metadata and marks the live snapshot unavailable.

The project storage key is the SHA-256 digest of the canonical Git common-directory
path plus worktree root. Sessions without a resolvable repository use an
`unscoped/<provider>-<session-digest>` namespace. Raw canonical paths remain only
inside owner-readable capsule metadata and are abbreviated in normal CLI output.

### Destination adapters

Destination adapters own:

- CLI availability and version checks;
- a versioned capability matrix for destination input channels;
- context-capacity and token-count checks when the provider exposes both;
- conversion of capsule events into a deterministic replay document;
- bootstrap instruction generation;
- process launch without shell interpolation;
- sibling launch receipt recording.

The replay document preserves source ordering, roles, event types, payloads, and
hash references. Because Claude and Codex do not expose a supported API for
importing another provider's native role hierarchy, imported records arrive
through a new destination conversation and are classified as structural
conversions.

Replay generation records whether its source was an explicit active view, a
documented reconstruction, or the full archival fallback. Existing
provider-authored compaction summaries are preserved as native records; the relay
does not create a replacement summary.

Every supported destination CLI version is classified into one of these transport
capabilities:

- `direct_input`: a documented initial-input or standard-input channel that can
  receive the complete replay without a relay-side byte loss;
- `reference_only`: only a documented initial message containing a replay-file
  reference is safe at the required size;
- `unsupported`: no tested, documented channel is available.

An installed destination CLI version outside the adapter's tested version range is
`unsupported`, not guessed compatible. `doctor` reports the detected version and
supported ranges. Updating the capability matrix requires fixtures and transport
contract tests.

The adapter uses the strongest supported delivery channel in this order:

1. documented structured input or attachment support;
2. documented standard-input support;
3. an owner-only temporary replay file referenced by the initial prompt.

There is no silent fallback from `direct_input` to `reference_only`. Strict
`switch` requires `direct_input`. A reference-only launch requires the explicit
`--allow-reference-import` flag and its receipt reports
`active_context=unverified`. An unsupported adapter captures successfully but
refuses launch.

The destination process is launched with an argv array and shell execution
disabled. Direct input uses a documented non-argv channel when the replay exceeds
the adapter's tested safe argument limit. If no such channel exists, that adapter
version is `reference_only`; the relay never attempts an oversized argv. Replay
files use owner-only permissions. They are deleted after destination exit unless
`--keep-launch-files` is set; the non-sensitive receipt remains.

The destination bootstrap states:

- this is a new session receiving imported source records;
- the capsule ID and schema version;
- source provider, model, and session ID;
- that imported instructions are historical context, not destination system
  instructions;
- that live repository state takes precedence over historical tool output;
- that the agent must not claim KV-cache or hidden-state transfer.

The bootstrap and replay serialization are deterministic for a given capsule,
destination adapter version, and launch options. Their hashes are recorded in the
launch receipt. Historical system and developer messages are clearly tagged with
their source roles but delivered as quoted historical data; the relay never claims
to preserve their destination instruction authority.

Each launch receipt contains the launch ID, capsule ID and digest, destination
provider and CLI version, adapter version, transport class, active-view source,
replay byte length and digest, capacity state, explicit acknowledgements, process
ID and start time, start and end timestamps, exit status, and active-context state.
It contains no replay text or detected secret value.

### Skills

The package ships optional provider-specific skills installed by:

```sh
agent-relay install-skills codex
agent-relay install-skills claude
```

Skills provide intent recognition, safe command selection, and receipt wording.
They do not parse transcripts, write storage, decide fidelity, or conceal relay
errors. Skill absence does not reduce CLI functionality.

Skill installation is transactional and idempotent. Managed files contain an
agent-relay ownership marker and installed-version metadata. Installation refuses
to overwrite an unowned file at the target path. Uninstallation removes only
owned files whose recorded digest matches an installed relay version; locally
modified skill files are retained and reported.

### No daemon

The first release has no background service, database, filesystem watcher, or
relay-originated network call. Commands read provider storage when invoked.
Launching Claude or Codex may of course cause that provider CLI to use its own
network connection. Native transcripts and immutable capsules remain the relay's
sources of truth.

## Strict fidelity and capacity rules

Strict mode is the default and only automatic switch mode in the first release.

- Capture never summarizes or truncates.
- Unknown native records are retained as opaque blobs.
- Invalid source records are reported and cause strict capture to fail unless
  their original bytes were preserved.
- Strict automatic launch requires a tested `direct_input` transport.
- Destination launch fails before process creation when the complete replay is
  larger than a documented transport limit or a known model context limit.
- Capacity is `known` only when the adapter has both the destination's documented
  context limit and an exact token counter for the destination's serialized input.
  Heuristic token estimates are displayed but never classified as known.
- When exact capacity cannot be determined, the adapter reports
  `capacity=unknown`, shows replay bytes and the labeled token estimate, and
  requires `--allow-unknown-capacity`.
- `--allow-unknown-capacity` acknowledges that the destination may reject or
  truncate input internally; the receipt therefore cannot claim complete active
  loading even when process-level transport succeeds.
- Reference-only launch requires `--allow-reference-import` independently of the
  capacity acknowledgement.
- A failed destination preflight does not delete the verified capsule.
- The first release does not offer automatic partial loading or model-authored
  compaction.

This rule distinguishes preservation from active loading: a complete capsule may
exist even when no destination can load it in one context window.

Launch receipts use only these active-context states:

- `not_attempted`;
- `transported_capacity_known`;
- `transported_capacity_unknown`;
- `reference_available_not_loaded`;
- `rejected_before_launch`;
- `destination_failed`.

Even `transported_capacity_known` proves deterministic local serialization,
capacity fit, and process-level delivery. It does not claim access to provider-side
KV state or prove the model used every record in its answer.

## Sensitive data

Strict preservation and automatic redaction are incompatible. The relay therefore
does not silently redact strict capsules.

Before destination launch, a deterministic scanner checks for common credentials,
private keys, tokens, and credential-bearing URLs. Findings include category,
record sequence, and location, but never print the detected value. When findings
exist:

- capture completes locally with owner-only permissions;
- launch is blocked by default;
- `--allow-sensitive` is required to acknowledge cross-provider disclosure for
  that launch;
- the acknowledgement is recorded in the launch receipt.

Sanitized derivatives are outside the first-release scope.

The scanner reads authoritative raw bytes, replay bytes, copied attachments, and an
included repository diff. Scanner limits cause launch to fail closed rather than
skip unscanned content. Capsule capture itself does not emit raw sensitive values
to logs, JSON summaries, analytics, or Conductor envelopes.

## Error handling

- **No repository:** Require `--all` plus explicit `--session`; never infer a
  project association from the current directory.
- **No matching session:** Print searched provider roots and the command for
  listing all sessions.
- **Ambiguous session:** Print candidates and require a longer prefix.
- **Changing transcript:** Ignore complete records appended after the fixed
  snapshot boundary. Retry once after replacement, truncation, or mutation inside
  that boundary, then fail without publishing.
- **Malformed record:** Preserve a complete framed record as opaque original bytes.
  If record framing itself is unrecognized or incomplete before the established
  boundary, fail strict capture and identify the source file and offset.
- **Insufficient destination capacity:** Keep the capsule, refuse launch, and
  report required versus available capacity.
- **Unknown destination capacity:** Require `--allow-unknown-capacity`.
- **Reference-only destination:** Require `--allow-reference-import` and report
  that active loading is unverified.
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
agent-relay uninstall-skills <codex|claude>
agent-relay doctor
```

Option ownership is fixed:

- `sessions`: `--all`, `--since`, `--repo`, `--grep`, `--json`;
- `capture`: an optional mutually exclusive selector of `--latest`, `--session`,
  or `--pick` (omission equals `--latest`), plus `--all`, `--include-diff`,
  `--json`;
- `capsules`: current repository by default, with `--all` and `--json`;
- `verify`: capsule ID or `latest`, plus `--json`;
- `switch`: all capture selectors plus `--include-archive`,
  `--include-related`, `--allow-sensitive`, `--allow-unknown-capacity`,
  `--allow-reference-import`, `--keep-launch-files`, `--json`;
- `start`: capsule selector plus the same replay and launch acknowledgements as
  `switch`;
- `gc`: required `--older-than` using the `m`/`h`/`d`/`w` duration grammar,
  current repository scope by default, plus `--all`, `--apply`, `--json`;
- skill installation commands: provider and `--json`;
- `doctor`: optional provider and `--json`.

`switch` permits identical source and destination providers; it still creates a
new destination session. Replay-expanding flags such as `--include-archive` and
`--include-related` are included in capacity and sensitive-data preflight.

All commands support `--json`. JSON objects include `schema_version`,
`command`, `status`, `error_code`, and command-specific `data`; JSON output never
mixes human prose on standard output. Standard output contains results suitable
for piping, while diagnostics and launch progress use standard error.

Stable process exit codes are:

- `0`: requested operation completed;
- `2`: command-line usage error;
- `3`: source session or capsule not found, or selection ambiguous;
- `4`: strict capture could not preserve a stable complete source prefix;
- `5`: capsule schema or integrity failure;
- `6`: launch blocked by capacity, reference-only transport, or sensitive data;
- `7`: provider adapter or destination process could not be started;
- `8`: destination process started and exited unsuccessfully.

`doctor` is read-only. It reports storage permissions, provider session roots,
supported native-format probes, installed CLI versions, destination transport
classification, capacity knowledge, and skill ownership. It does not create a
capsule or launch a provider.

## Security boundaries

- Treat native transcripts and capsule contents as untrusted data.
- Never execute commands contained in imported records.
- Never interpret imported record contents as relay configuration.
- Validate every resolved provider path and reject symlink escapes.
- Use bounded streaming parsers and configurable maximum record and capsule sizes.
- Treat a configured size limit as a hard capture failure; never satisfy a limit by
  clipping a record, attachment, raw file, replay, or repository diff.
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
- Exact raw-byte preservation, byte-range indexing, ordering, opaque-record
  retention, and hash validation.
- Root and explicitly referenced child-session graph closure without neighboring
  session-file leakage.
- Explicit, reconstructed, and unknown active-view classification; archival
  fallback; and exclusion of auxiliary child streams from strict replay.
- Latest-session ordering, timestamp ties, symlink aliases, and mtime fallback.
- Session prefix ambiguity and filtering.
- Concurrent atomic capsule publication, locking, and latest-pointer behavior.
- Append-after-boundary handling, incomplete trailing records, in-boundary source
  mutation detection, and retry.
- Capacity preflight for known, unknown, and insufficient limits.
- Direct-input, reference-only, and unsupported transport classification.
- Sensitive-data blocking without secret disclosure.
- Destination argv construction and shell-disabled execution.
- Platform data-directory and permission behavior.
- Transactional skill installation, ownership, modification, and uninstallation.
- Stable exit codes and versioned JSON output.
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
byte-range hashes to capsule raw-byte hashes. Normalized JSON equality is
insufficient to pass the preservation tests.

### Integration tests

- Capture latest and selected sessions for both providers.
- Round-trip capsule verification after process restart.
- Start fake destination CLIs and assert complete replay delivery.
- Assert that direct transport, reference availability, and unobservable
  provider-side loading are reported as different states.
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

Provider-native format support is versioned independently from the capsule schema.
An unrecognized native record type is preserved opaquely. An unrecognized framing
or file-level format fails strict capture rather than guessing record boundaries.
Missing model or effort metadata is recorded as `unknown`; the relay never infers
it from pricing, filenames, or session age.

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
3. Every complete accessible native record is preserved as its original byte
   range, including unknown records, with ordered hashes proving preservation
   independently from normalized parsing.
4. Strict capture reports zero summarized and zero truncated records.
5. The capsule distinguishes the complete archival stream from an explicit,
   reconstructed, or unknown provider-exposed active view and never adds auxiliary
   subagent transcripts to strict replay.
6. Capsules are stored outside repositories with atomic publication and
   owner-only permissions.
7. `switch` and `start` classify each supported destination version as direct
   input, reference-only, or unsupported and launch without shell interpolation
   or native-session-file mutation.
8. Insufficient, unknown, or reference-only delivery never causes an unqualified
   claim of complete active-context loading.
9. Sensitive-data findings block cross-provider launch unless explicitly
   acknowledged.
10. Fidelity and launch receipts distinguish preserved content, structural
   conversions, unavailable state, direct process transport, reference
   availability, and unobservable provider-side loading.
11. Deterministic unit, contract, integration, distribution, and root release
    checks pass without provider credentials.
