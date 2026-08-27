---
name: routing-subagents
description: Use when a Codex task has independent workstreams, needs independent review, or contains high-risk decisions that may justify subagents.
---

# Routing Subagents

Delegate only when it improves time or confidence. Choose the cheapest supported model and lowest reasoning effort likely to succeed without retrying. Treat ChatGPT-login usage qualitatively; no fixed effort multiplier is published.

## Decide whether to delegate

- Supported model or effort choices explicitly made by the user override automatic routing; ask before substituting an unavailable choice.
- `spawn_agent` metadata determines availability; the main model picker does not.
- Delegate bounded independent work or independent judgment. Keep tightly coupled implementation, integration, and final synthesis with the primary; read-only mapping or review may still be delegated.
- Batch high-volume work into balanced shards rather than spawning per item.

## Choose the model

Consider only advertised rows:

| Model | Use |
|---|---|
| `gpt-5.6-luna` | Deterministic, mechanical, read-heavy, or high-volume work |
| `gpt-5.6-terra` | Routine implementation, debugging, analysis, or review |
| `gpt-5.6-sol` | Ambiguous, cross-cutting, high-consequence, or frontier work |
| `gpt-5.3-codex-spark` | Narrow latency-sensitive coding |

Current efforts: Sol/Terra support `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`; Luna supports through `max`; Spark follows runtime metadata.

For security-critical root cause, data-loss risk, or irreversible decisions, use Sol at `xhigh` for decisive analysis or independent validation, and `max` for one final quality-critical validator. Other models may gather bounded evidence.

## Choose reasoning effort

| Effort | Use |
|---|---|
| `low` | Deterministic, tightly scoped work |
| `medium` | Routine coding, analysis, and review |
| `high` | Difficult but well-scoped multi-step work |
| `xhigh` | Ambiguous or high-risk investigation |
| `max` | Final quality-critical single-agent judgment |
| `ultra` | Orchestration of at least three independent workstreams |

`ultra` is not a stronger `max`. Assign it only to a spawned orchestrator; never suggest retuning the current primary. Preserve explicit `max` as `max`.

## Dispatch and escalate

- Give each subagent a bounded goal, scope, constraints, expected output, and verification responsibility.
- Default ordinary implementation and review to Terra at `medium`; prefer Luna at `low` for deterministic support work.
- Increase effort when the problem is insufficient depth. Increase model tier when it is insufficient capability. Do not repeat completed work merely to try a stronger route.
- Otherwise decide autonomously. Ask only when a requested route is unavailable or the quality-versus-allowance choice could change correctness, safety, or scope.
