---
name: routing-subagents
description: Use when a Codex task has independent workstreams, needs independent review, or contains high-risk decisions that may justify subagents.
---

# Routing Subagents

Delegate only when it improves time or confidence. Choose the supported model and reasoning effort with the lowest expected total task cost that is likely to succeed without retrying. Per-token price alone is insufficient: Astra can use fewer output tokens on difficult work. Treat ChatGPT-login usage qualitatively; do not invent fixed effort multipliers or convert API prices into subscription allowance.

## Decide whether to delegate

- Supported model or effort choices explicitly made by the user override automatic routing; ask before substituting an unavailable choice.
- `spawn_agent` metadata determines availability and supported efforts; the main model picker and API model catalog do not establish subagent availability.
- Delegate bounded independent work or independent judgment. Keep tightly coupled implementation, integration, and final synthesis with the primary; read-only mapping or review may still be delegated.
- Batch high-volume work into balanced shards rather than spawning per item.

## Choose the model

Consider only models advertised by the current runtime. These task assignments are local routing recommendations:

| Model | Use |
|---|---|
| `gpt-5.6-luna` | Deterministic, mechanical, read-heavy, or high-volume work |
| `gpt-5.6-terra` | Routine implementation, debugging, analysis, or review |
| `gpt-5.6-sol` | Complex, open-ended work needing deeper analysis or polished output when Astra's additional capability is unnecessary |
| `gpt-6-astra` | Hardest multi-step work, cross-cutting reasoning, and high-consequence judgment across code, tools, or research |
| `gpt-5.3-codex-spark` | Narrow latency-sensitive coding, only when advertised |

For security-critical root cause, data-loss risk, or irreversible decisions, prefer Astra at `xhigh` for decisive analysis or independent validation, and `max` for one final quality-critical validator when additional depth is warranted. Sol is the fallback when Astra is unavailable unless the user explicitly requested Astra. Other models may gather bounded evidence.

## Choose reasoning effort

The runtime advertised these Codex subagent options when this skill was updated; recheck the live tool metadata before dispatch:

| Model | Supported efforts | Default |
|---|---|---|
| `gpt-6-astra` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `medium` |
| `gpt-5.6-sol` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `low` |
| `gpt-5.6-terra` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | `medium` |
| `gpt-5.6-luna` | `low`, `medium`, `high`, `xhigh`, `max` | `low` |

Astra's API `reasoning.effort` supports `low`, `medium`, `high`, `xhigh`, and `max`; it does not support `none` or `minimal`. Codex's `ultra` adds orchestration with subagents and is available here through the runtime. Do not pass `ultra` as an API reasoning effort or assume every client exposes it.

| Effort | Local routing recommendation |
|---|---|
| `low` | Deterministic, tightly scoped work |
| `medium` | Routine coding, analysis, and review; starting point for Astra when stronger capability is needed |
| `high` | Difficult but well-scoped multi-step work |
| `xhigh` | Ambiguous or high-risk investigation |
| `max` | Hardest single-agent reasoning or final quality-critical judgment when depth outweighs latency and usage |
| `ultra` | Maximum reasoning with delegation for work that benefits from parallel agents |

Preserve this skill's local convention: assign `ultra` only to a spawned orchestrator with at least three useful independent workstreams and sufficient available agent capacity. The three-workstream threshold is a routing preference, not an OpenAI requirement. Never suggest retuning the current primary. Preserve an explicit `max` choice as `max`; do not automatically upgrade it to `ultra`.

## Dispatch and escalate

- Name each subagent’s `task_name` after its model and reasoning effort (for example, `terra_medium` or `astra_xhigh`), adding a short task suffix when needed for uniqueness.
- Give each subagent a bounded goal, scope, constraints, expected output, and verification responsibility.
- Default ordinary implementation and review to Terra at `medium`; prefer Luna at `low` for deterministic support work. Use Astra at `medium` or `high` when the task needs stronger capability; reserve `xhigh` and `max` for justified depth.
- Pass both `model` and `reasoning_effort` when selecting a route. With the collaboration tool's `fork_turns`, use `"none"` or a positive integer string for overrides; full-history forks (`"all"` or omitted) inherit the parent's model and effort and do not accept overrides. Give a limited-context agent enough task context to work independently.
- Increase effort when the problem is insufficient depth. Increase model tier when it is insufficient capability. Do not repeat completed work merely to try a stronger route, or assume an effort label provides equal capability across models.
- Otherwise decide autonomously. Ask only when a requested route is unavailable or the quality-versus-allowance choice could change correctness, safety, or scope.

## Sources and freshness

Checked 2026-09-10 against official documentation and the live `collaboration.spawn_agent` schema. Runtime support takes precedence for dispatch; task assignments and escalation thresholds above are local policy.

- [GPT-6 Astra model and API reasoning levels](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Astra guidance and task-cost considerations](https://developers.openai.com/api/docs/guides/latest-model)
- [Model selection, Max, and Ultra](https://learn.chatgpt.com/docs/models)
- [Subagent models, reasoning, and inheritance](https://learn.chatgpt.com/docs/agent-configuration/subagents)
