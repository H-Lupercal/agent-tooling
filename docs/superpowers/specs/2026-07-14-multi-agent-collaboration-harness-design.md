# Multi-Agent Collaboration Harness Design

## Goal

Add a cross-platform, local-first collaboration harness to `agent-tooling` as the
independently installable `agent-harness/` project with the `agent-harness` CLI. A user
gives the harness an overarching software goal, a Git repository, acceptance commands,
and a roster of heterogeneous AI participants. Direct model APIs, local inference
endpoints, coding-agent CLIs, and later remote A2A agents then discuss, interrupt,
implement, test, and review work against one evolving codebase.

The harness is differentiated by an open conversational floor rather than a strictly
turn-based workflow. Participants may react to partial streamed messages and begin
speaking before another participant finishes. The harness coordinates event ordering,
safe cancellation, repository isolation, evidence gates, budgets, and human escalation;
it does not appoint a model to decide which model is correct.

## Product boundary

The product is a collaboration runtime, not another model provider or a replacement for
existing agent frameworks. It provides a common participation protocol over:

- raw models accessed through provider APIs;
- OpenAI-compatible and Anthropic-compatible hosted or local endpoints;
- complete coding agents such as Codex and Claude Code;
- structured subprocess protocols such as ACP; and
- remote A2A agents in a later integration.

The repository is the shared collaboration artifact. Raw models receive a controlled
coding runtime with search, filesystem, patch, shell, Git, and test tools. Complete
coding agents may retain their native tool loops, but all canonical changes still pass
through the harness's workspace and evidence controls.

The following are outside the first release:

- browser automation of consumer ChatGPT, Claude, or similar websites;
- a hosted control plane;
- distributed participants running across multiple machines;
- voice conversation;
- automatic deployment, publishing, or other production side effects;
- a public adapter marketplace; and
- any model acting as a final arbiter.

## Existing landscape and product position

Multi-agent orchestration is established in Microsoft Agent Framework, OpenAI Agents
SDK, CrewAI, CAMEL, MetaGPT, Gas Town, RuFlo, and related projects. Provider breadth is
also established by Hermes Agent, OpenRouter, and LiteLLM. The remaining product gap is
the combination of:

1. an open, overlapping conversational floor;
2. both raw provider models and autonomous coding CLIs as addressable peers;
3. a shared but transactionally protected repository;
4. evidence-gated, model-neutral convergence; and
5. replayable attribution across messages, tools, patches, tests, and spawned agents.

The product should be described as a provider-independent live-agent collaboration
runtime or agent runtime gateway, not as a generic multi-agent framework.

## Architecture

The harness uses a central, event-sourced runtime. The runtime coordinates mechanics
without supplying a privileged model opinion.

```text
User goal + repository + roster + budgets + acceptance gates
                              |
                        Run Controller
                              |
               +--------------+--------------+
               |                             |
       Collaboration Room              Workspace Manager
               |                             |
        Append-only Event Store        Worktrees and patches
               |                             |
     +---------+---------+                   |
     |         |         |                   |
 API models  CLI agents  A2A agents          |
     |         |         |                   |
     +---------+---------+-------------------+
                              |
                    Evidence Gate Engine
                              |
                Accept / revise / ask human
```

### Run Controller

The Run Controller starts and resumes runs, admits configured and dynamic participants,
enforces capability requirements and budgets, manages participant lifecycle, and pauses
for human decisions. It may make deterministic scheduling decisions but may not decide
the substantive winner of a model disagreement.

### Collaboration Room

The Collaboration Room is a concurrent event bus. It broadcasts partial messages,
completed responses, interruption requests, participant state changes, repository
advances, patch proposals, gate results, reviewer findings, and human decisions.

### Event Store

An append-only event store is the source of truth. Every event has a run identifier,
monotonic sequence number, timestamp, actor, type, causation reference, correlation
reference, and typed payload. Large artifacts such as diffs and logs are content
addressed and referenced from events.

The local durable format is SQLite with transactional writes. Runs export to a portable
JSON Lines manifest plus content-addressed artifacts. Canonical repository integration
stops if event persistence fails; agents may not create unrecorded canonical changes.

### Agent Adapters

Adapters translate between the common participant protocol and direct APIs, compatible
endpoints, interactive CLIs, structured subprocess protocols, and later A2A. They expose
capabilities explicitly rather than silently emulating unsupported behavior.

### Coding Runtime

The Coding Runtime gives managed raw models controlled tools. Tool requests are
validated against participant permissions and recorded before execution. Tool results
are recorded and treated as untrusted input when returned to a model.

### Workspace Manager

The Workspace Manager presents one shared logical repository through isolated worktrees
and atomic patch integration. Accepted changes advance a canonical integration branch.

### Evidence Gate Engine

The Evidence Gate Engine runs deterministic checks, validates structured findings,
tracks finding fingerprints, calculates reviewer quorum, detects non-progress, and
produces neutral human-escalation packets.

### Human Console

The first interface is a cross-platform CLI with an interactive terminal view. It shows
the live room, partial speech, participant state, child lineage, worktrees, diffs, gates,
findings, dissent, and budget consumption. It also provides pause, resume, interruption,
and human-decision controls.

## Live conversation protocol

Participants exchange only published messages and actions, never hidden reasoning. A
participant may be `starting`, `listening`, `responding`, `using_tools`, `paused`,
`degraded`, `offline`, or `completed`.

A streamed response produces at least these events:

```text
message.started
message.delta
message.completed
```

Adapters group raw tokens into sentence or short timed chunks before broadcasting them.
This permits early reaction without prompting every participant for every token. Multiple
participants may speak concurrently. Monotonic event sequence numbers give all consumers
one canonical reconstruction of overlapping speech.

An idle participant may remain silent, begin a response, address another participant,
broadcast evidence, request a task or file scope, or challenge a claim. Participants do
not automatically react to their own output.

### Interruption

An interruption request identifies a target, priority, reason, and optional evidence.

- Normal interruptions are queued for the target's next listening checkpoint.
- Urgent interruptions require new evidence, a direct contradiction, a safety concern,
  or an explicit high-priority question.
- If the target adapter supports cancellation, the runtime cancels generation and emits
  `message.interrupted` while preserving the partial response.
- The target may restart with its partial response, the interruption, and relevant new
  repository state.
- An adapter without live cancellation uses soft interruption and reports that
  degradation to the room.
- Repository writes and tool processes reach an adapter-declared safe checkpoint before
  cancellation.

### Conversation stability

Total participants and simultaneous speakers are separate controls. A room may contain
many participants while allowing only a smaller number to stream at once. The user may
configure both values.

The runtime applies speaking cooldowns, event-consumer backpressure, duplicate-message
suppression, and per-participant interruption limits. Repeated interruptions without new
evidence reduce the participant's scheduling priority. The default permits two
simultaneous speakers, but this is policy rather than a framework limit.

## Shared repository and patch integration

Each work item records its objective, acceptance criteria, canonical base commit,
responsible participants, expected file scope, dependencies, task lease, and required
verification commands.

An agent works in an isolated worktree created from a canonical commit. When ready, it
submits a proposal containing:

- base commit and diff;
- authoring participant and child lineage;
- relevant message and tool-event references;
- requirement addressed;
- tests added or changed;
- commands executed and their results; and
- known limitations.

The integration pipeline is deterministic:

1. Verify that the proposal applies to its declared base.
2. Detect overlapping files and changed regions.
3. Rebase mechanically only when unambiguous.
4. Run required scoped checks in a clean environment.
5. Broadcast the proposal, diff, and evidence.
6. Collect structured findings and independent reviewer votes.
7. Apply an accepted patch atomically to the canonical branch.
8. Emit `repository.advanced` with the new commit and gate results.

Active agents receive canonical advances at safe checkpoints. Their worktrees are not
silently rebased while a command or edit is in progress.

When proposals conflict, the harness publishes both and does not select a substantive
winner. Agents may withdraw, combine, or demonstrate superiority through requirements
and tests. A conflict that outlives the deliberation budget pauses for the human.

Agents cannot force-push, rewrite canonical history, or merge directly. Rollbacks are
new revert proposals. External side effects require separate explicit authorization.
Every accepted line change remains traceable to its proposal, events, participant, and
verification evidence.

## Evidence gates and consensus

The harness distinguishes four evidence levels:

1. **Hard deterministic gates:** builds, tests, lint, type checks, security policies,
   and explicit user commands. Failures block acceptance.
2. **Requirement evidence:** a demonstrated mismatch with an acceptance criterion,
   supported by a reproduction, test, trace, or precise code path.
3. **Reviewer judgment:** maintainability, design quality, or credible risk. It blocks
   only when connected to a concrete requirement or plausible failure mode.
4. **Advisory feedback:** preferences, speculative improvements, and unrelated
   opportunities. These are recorded and cannot block completion.

Reviewers are explicitly allowed to return `no_findings`. A finding contains a stable
fingerprint, affected revision, severity, violated gate or requirement, location,
supporting evidence or reproduction, and blocking classification. A resolved finding
may be reopened only with new evidence against the current revision.

A proposal is accepted when:

```text
all hard gates pass
AND no evidence-backed blocker remains unresolved
AND the configured independent-reviewer quorum approves
AND two consecutive review rounds produce no new valid blocker
```

The patch author cannot approve its own work. The default quorum is two independent
reviewers, preferably from different provider or model families when available.
Unanimity is not required, and minority objections are preserved in the receipt.

### Loop termination and human escalation

The runtime stops autonomous deliberation when it reaches a configured review-round,
time, token, or monetary limit; sees repeated finding fingerprints without new evidence;
observes no repository, test, or gate-state change across consecutive rounds; detects
repeated restatement of positions; or cannot reconcile conflicting valid proposals.

No arbiter model is used. The human receives the current revision and diff, acceptance
criteria, gate table, approvals, dissent, unresolved evidence, competing proposals,
and consumed budgets. The human may select a proposal, revise acceptance criteria,
extend the budget, request specific evidence, or abort. The decision is an immutable
run event.

## Dynamic child participants

Any admitted participant may request a child with a role, bounded objective, selected
context, workspace policy, permissions, and budget. The Run Controller admits or rejects
the request according to user policy and remaining resources.

A child receives an independent context containing its role, objective, relevant
requirements, selected events and artifacts, and repository snapshot. It does not
inherit the parent's entire transcript. It subscribes to the room from its join event
and may retrieve older events through controlled queries.

An admitted child is a full participant. It may speak, receive interruptions, inspect
accepted state, work in an isolated worktree, submit patches, and request descendants
within policy. Its stable identity records ancestry, such as
`builder-claude/database-specialist-1`.

The preferred path is a harness-managed child that receives its own adapter process or
API session. A provider-native subagent is registered separately only when hooks or a
structured protocol expose its identity and events reliably. Otherwise it remains an
internal implementation detail attributed to its parent and cannot vote independently.

Child permissions may only narrow the parent's permissions. Spawns use explicit budget
allocations and respect user-configured limits on total dynamic children, children per
parent, spawn depth, time to live, and idle duration. Spawn storms are rejected. Child
work survives parent failure long enough for the controller to close or reassign it
safely.

Lineage affects independence: a child of a patch author does not count as an independent
reviewer for that patch. Provider and model-family correlation are also retained so one
participant cannot manufacture quorum by spawning agreeable copies.

## Participant capacity

There is no framework-defined participant cap. The user may configure any number of root
participants subject to local resources, credentials, provider limits, and the run's
explicit capacity policy. `max_participants` must be at least the configured root-roster
size and may be raised to any positive integer. Dynamic-child and simultaneous-speaker
limits are independent and user controlled. For example:

```yaml
capacity:
  max_participants: 50
  max_dynamic_children: 30
  max_children_per_parent: 5
  max_spawn_depth: 3
  max_simultaneous_speakers: 4
```

These are illustrative policy values, not framework constants. A larger explicit root
roster uses a correspondingly larger `max_participants` value. Autonomous child creation
remains bounded by user policy and overall time, token, and monetary budgets.

## Provider adapters and capability negotiation

The runtime supports two primary execution classes.

Managed model participants include native provider APIs, cloud model platforms, routing
gateways, compatible endpoints, and local inference. They use the harness Coding
Runtime. External agent participants include interactive coding CLIs, ACP processes,
remote A2A agents, and custom executable adapters. They may retain native tool loops.

Every adapter publishes a versioned capability descriptor covering at least:

```text
stream_output
receive_while_generating
cancel_generation
resume_session
structured_output
native_tool_calls
image_input
context_limit
maximum_output
workspace_mode
authentication_method
rate and cost metadata
native_child_visibility
```

The controller validates required capabilities before starting. Unsupported behavior is
never silently assumed. A CLI that cannot receive a live prompt may participate with an
explicit `interrupt: queued` capability. Events record the resolved provider, model,
adapter version, and capability snapshot so aliases or later provider changes cannot
rewrite run history.

### Provider breadth

The architecture accommodates the provider surface documented by Hermes Agent:

- API keys and native APIs;
- subscription and OAuth access where permitted;
- OpenRouter, LiteLLM, and other routing gateways;
- Azure AI Foundry, AWS Bedrock, and Google Vertex AI;
- hosted open-model providers;
- Ollama, vLLM, SGLang, llama.cpp, and LM Studio; and
- arbitrary OpenAI-compatible or Anthropic-compatible endpoints.

The first release implements generic OpenAI-compatible endpoints, native Anthropic and
Gemini adapters where protocol semantics require them, generic subprocess adapters,
first-class Codex and Claude Code profiles, and deterministic fake adapters. ACP, A2A,
additional native OAuth flows, and cloud-platform adapters follow the same contract in
later releases.

## Authentication and trust boundaries

Credentials remain in provider-native stores or environment references. Project
configuration and events contain credential references, never values. API keys, OAuth
tokens, and secrets may not enter prompts, repository files, command logs, or exported
receipts.

Each participant receives only its assigned worktree, approved tools, and required
environment references. Sending repository content to an external provider is an
explicit trust-boundary choice. Remote agents receive scoped artifacts instead of
unrestricted filesystem access. Adapter output is untrusted and validated before it
becomes a tool request or patch.

Retries, rate limits, fallback activation, and costs are participant events. Fallback
models run only when configured and are announced because changing models affects
behavior and independence. Recovery never widens permissions, changes acceptance
criteria, or spends beyond approved limits.

## Configuration and operator experience

The first release is local-first and starts from a Git repository:

```text
agent-harness init
agent-harness doctor
agent-harness run "Implement the requested feature and prove it works"
```

Initialization discovers installed coding CLIs and creates project configuration for
participants, roles, provider credential references, capability requirements,
concurrency, interruption, repository permissions, evidence commands, reviewer quorum,
and budgets.

An illustrative configuration is:

```yaml
participants:
  - id: builder-codex
    adapter: cli
    command: codex
    roles: [implementation]

  - id: reviewer-claude
    adapter: anthropic
    model: configured-claude-model
    roles: [review]

  - id: specialist-local
    adapter: openai-compatible
    endpoint: http://localhost:11434/v1
    model: configured-local-model
    roles: [tests]

capacity:
  max_participants: 20
  max_dynamic_children: 10
  max_children_per_parent: 3
  max_spawn_depth: 2
  max_simultaneous_speakers: 2

consensus:
  reviewers: 2
  quiet_rounds: 2
  max_rounds: 6
  on_deadlock: ask-human

gates:
  - command: pytest -q
  - command: ruff check .
```

The terminal interface supports detach and resume. Completion emits a portable receipt
containing the final commit, resolved participant identities, child lineage,
contributions, decisions, gate evidence, dissent, interruptions, failures, retries, and
costs.

## Failure handling

Failures are typed events, not transcript prose.

- Provider timeouts and rate limits retry only within configured limits and mark the
  participant degraded.
- CLI crashes preserve worktrees, partial messages, and tool history; restart occurs
  only when the adapter declares it safe.
- Context exhaustion creates an evidence-linked checkpoint that preserves requirements,
  unresolved findings, active task bindings, and repository references.
- Tool timeouts stop at safe process boundaries and leave evidence incomplete rather
  than failed or passed.
- Invalid patches are rejected without modifying canonical state.
- A gate that cannot run is distinct from a gate failure and never counts as passing.
- Event-store failure immediately stops canonical integration.
- Participant permissions may be revoked without deleting historical contributions.
- A missing human pauses at the next safe checkpoint only when a human decision is
  required; otherwise the run may continue within approved autonomy and budgets.

## Testing strategy

The implementation uses:

- unit tests for event ordering, deduplication, quorum, lineage, budgets, and loop
  detection;
- property tests for concurrent event streams and repository state transitions;
- adapter contract tests using recorded provider responses;
- deterministic fake agents that speak, interrupt, crash, disagree, spawn children,
  and submit conflicting patches;
- repository fixtures for consensus, invalid evidence, conflicts, and deadlock;
- chaos tests for dropped streams, process termination, partial writes, and delayed
  consumers;
- security tests for secret leakage, prompt-injected tool requests, path traversal, and
  permission escalation;
- end-to-end tests on Linux, macOS, and Windows; and
- optional live-provider tests separated from deterministic CI.

Toolbelt and Codex Conductor are used during implementation to discover and configure
development tools, govern task admission, and measure contribution. The new package
must keep its production boundaries explicit and must not create an implicit runtime
dependency between the existing Toolbelt and Conductor packages.

## Acceptance criteria

The first release is acceptable when it demonstrates:

1. At least three heterogeneous participants in deterministic fixtures while supporting
   any user-configured root roster permitted by the explicit capacity policy.
2. Overlapping streamed conversation with soft and hard interruption.
3. A participant spawning an isolated, independently contextualized child that joins
   the room under configured limits.
4. Shared logical repository state backed by isolated worktrees.
5. Attributable patch proposals and atomic canonical integration.
6. Evidence-backed review with independent quorum and lineage-aware vote exclusion.
7. Duplicate criticism and non-progress loops terminating automatically.
8. A deadlocked run pausing exclusively for human judgment.
9. Crash recovery from the event store without losing canonical state.
10. Capability negotiation that exposes degraded adapter behavior before execution.
11. A portable receipt replaying messages, interruptions, patches, gates, lineage,
    dissent, recovery, and costs.
12. Deterministic offline tests passing on Linux, macOS, and Windows.
13. No credentials or hidden reasoning recorded in project artifacts.
