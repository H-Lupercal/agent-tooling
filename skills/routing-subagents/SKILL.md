---
name: routing-subagents
description: Use when a Codex task has independent workstreams, needs independent review, or contains high-risk decisions that may justify subagents.
---

# Routing Subagents

Before applying this skill or spawning subagents under its routing guidance, ask the user whether to use routing-subagents for the current task. If routing-subagents has already been selected or approved for the current task, or the user has directly requested subagents or parallel agent work, proceed without asking again. A direct delegation request authorizes using this routing guidance within the requested scope. Merely discovering or reading this skill does not count as selection. A request to edit this skill is not a request to run its delegation workflow. This confirmation gate is a local preference; current Codex supports delegation requested by the user or applicable AGENTS.md/skill instructions.

Delegate only when it improves time or confidence. Choose the supported model and reasoning effort with the lowest expected total task cost that is likely to succeed without retrying. Include coordination, duplicated context, and retries in that cost; subagents can increase total token usage. Treat ChatGPT-login usage qualitatively; do not invent fixed effort multipliers or convert API prices into subscription allowance.

## Decide whether to delegate

- Supported model or effort choices explicitly made by the user override automatic routing; ask before substituting an unavailable choice.
- `spawn_agent` metadata determines availability and supported efforts; the main model picker and API model catalog do not establish subagent availability.
- Delegate bounded independent work or independent judgment. Keep tightly coupled implementation, integration, and final synthesis with the primary; read-only mapping or review may still be delegated.
- Batch high-volume work into balanced shards rather than spawning per item.

## Choose the model

Consider only models advertised by the current runtime. These task assignments are local routing recommendations:

| Model | Use |
|---|---|
| `gpt-6-luna` | Focused edits, extraction, triage, read-heavy mapping, and repeatable high-volume work |
| `gpt-6.1-sol` | Default for implementation, debugging, research, and review; complex coding and agentic workflows where time and cost matter |
| `gpt-6-sol` | Previous-generation fallback when GPT-6.1 Sol is unavailable, or when explicitly requested |
| `gpt-6-astra` | Hardest multi-step work, cross-cutting reasoning, and high-consequence judgment across code, tools, or research |
| `gpt-5.6-sol` | Older alternatives when explicitly requested, needed for an established workflow, or the preferred GPT-6 route is unavailable |

For security-critical root cause, data-loss risk, or irreversible decisions, prefer Astra at `xhigh` for decisive analysis or independent validation, and `max` for one final quality-critical validator when additional depth is warranted. `gpt-6.1-sol` is the preferred fallback when Astra is unavailable unless the user explicitly requested Astra; otherwise use an available supported route. Other models may gather bounded evidence.

Use the full versioned model ID when dispatching: GPT-6.1 Sol, GPT-6 Sol, and GPT-5.6 Sol have different defaults and roles. Do not infer a GPT-6 Terra model or retain an unavailable older Luna route.

## Choose reasoning effort

The runtime advertised these Codex subagent options when this skill was updated; recheck the live tool metadata before dispatch:

| Model | Supported efforts | Live tool default |
|---|---|---|
| `gpt-6.1-sol` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `low` |
| `gpt-6-astra` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `medium` |
| `gpt-6-sol` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `medium` |
| `gpt-6-luna` | `low`, `medium`, `high`, `xhigh`, `max` | `low` |
| `gpt-5.6-sol` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `low` |

API, product recommendations, and live tool defaults differ. GPT-6.1 Sol's API supports `low`, `medium` (default), `high`, `xhigh`, and `max`; it does not support `none` or `minimal`. This runtime instead defaults GPT-6.1 Sol to `low` and also advertises `ultra`. Only pass settings accepted by the tool being called. Do not pass `ultra` as an API reasoning effort. GPT-6 Luna does not support Ultra. Current product guidance starts Luna at `high` and Astra at `low`; these are recommendations, not the tool defaults above.

| Effort | Local routing recommendation |
|---|---|
| `low` | Deterministic, tightly scoped work |
| `medium` | Routine coding, analysis, and review; starting point for Astra when stronger capability is needed |
| `high` | Difficult but well-scoped multi-step work |
| `xhigh` | Ambiguous or high-risk investigation |
| `max` | Hardest single-agent reasoning or final quality-critical judgment when depth outweighs latency and usage |
| `ultra` | Maximum reasoning with delegation for work that benefits from parallel agents |

Use `ultra` for a spawned orchestrator only when nested delegation provides a concrete benefit and the live runtime has capacity for that orchestrator and its planned concurrent workers. Prefer a flat plan when the primary can coordinate the work directly. Count the primary, existing agents, and descendants according to the runtime rules before spawning. With four total slots, the primary can coordinate three workers directly; adding an orchestrator leaves capacity for only two concurrent workers. Schedule additional independent work in batches or reuse agents. Do not require a fixed number of workstreams for Ultra; select it only when supported and useful. Never suggest retuning the current primary. Preserve an explicit `max` choice as `max`; do not automatically upgrade it to `ultra`.

## Dispatch and escalate

- Name each subagent’s `task_name` after its model and reasoning effort (for example, `sol61_medium` or `astra_xhigh`), adding a short task suffix when needed for uniqueness.
- Give each subagent a bounded goal, scope, constraints, expected output, and verification responsibility.
- Default implementation and review needing judgment to `gpt-6.1-sol` at `medium`; use `high` or `xhigh` for complex logic or conflicting evidence. Use `gpt-6-luna` at `low` for deterministic support work, or `medium`/`high` for scoped work needing more checking. Use Astra at `low` for clear work needing strong judgment, `medium` for broader multi-step work, and `high` for complex debugging, sustained multi-step analysis, or careful review of assumptions and edge cases. Reserve `xhigh` for especially demanding or ambiguous investigations and `max` for the hardest quality-critical judgments when depth outweighs latency and usage. These are local starting points, not runtime defaults or quality guarantees.
- Pass both `model` and `reasoning_effort` when selecting a route. In the current `collaboration.spawn_agent` schema, overrides require `fork_turns: "none"`. Only `"all"` and `"none"` are supported; do not pass integer strings. Full-history forks (`"all"` or omitted) inherit the parent's model and effort and reject overrides. Supply a self-contained brief for `"none"`.
- Give parallel editors disjoint file ownership or isolated worktrees when needed. State that the workspace is shared, preserve others' changes, and return concise findings with file references, changes, validation results, and unresolved risks. The primary integrates and verifies the combined result.
- Use the current tool controls: `send_message` steers an existing agent without starting a turn; `followup_task` starts or resumes work; `interrupt_agent` stops its current turn. Collect required results before final synthesis and reuse existing agents when useful.
- Diagnose an incomplete or failed result before escalating. Supply missing evidence or clarify the brief first; resolve tool failures and permission constraints through the applicable workflow. If a dependency remains unavailable, report the specific blocker and continue independent work. A stronger model does not grant access or repair unavailable tools. Increase effort when the remaining problem is insufficient depth; increase model tier when it is insufficient capability. Do not repeat completed work merely to try a stronger route, or assume an effort label provides equal capability across models.
- Otherwise decide autonomously. Ask only when a requested route is unavailable or the quality-versus-allowance choice could change correctness, safety, or scope.

## Sources and freshness

Checked 2026-10-08 against the official pages below and the live `collaboration.spawn_agent` schema. Live tool support governs dispatch. Routing thresholds, task names, confirmation, and orchestration choices are local preferences.

- [Codex subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents): delegation triggers and the recommended current Sol model.
- [Models and reasoning controls](https://learn.chatgpt.com/docs/models): product effort recommendations, Max, Ultra, and availability differences.
- [GPT-6.1 Sol API model](https://developers.openai.com/api/docs/models/gpt-6.1-sol): API reasoning levels and API default, distinct from this runtime.
- [Model selection](https://developers.openai.com/api/docs/guides/model-selection): capability, cost, latency, and task-specific effort tradeoffs.

Recheck the live schema before dispatch. Refresh official guidance when changing model policy; do not infer tool availability from an API catalog or product model picker.
