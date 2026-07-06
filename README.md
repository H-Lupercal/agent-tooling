# codex-conductor

`codex-conductor` is a cost-aware orchestration layer for Codex subagents. It
keeps the primary model on `gpt-5.5`, routes bounded delegated work to cheaper
enabled models, and uses Codex hooks to block subagent spawns that violate the
task envelope, tier ladder, depth limit, concurrency caps, or delegated-spawn
budget.

It is a stdlib-only Python project. It does not modify the Codex binary and it
does not run a wrapper daemon. Enforcement happens through Codex's native hook
system and is intentionally a guardrail, not a hard billing or security
boundary.

## What It Installs

The installer writes only marked, managed files or blocks:

- `/home/neil/.codex/hooks.json`
- `/home/neil/.codex/conductor/`
- a managed `[agents]` block in `/home/neil/.codex/config.toml`
- a managed delegation policy block in `/home/neil/AGENTS.md`

The source project lives at:

```bash
/home/neil/VSproj/codex-conductor
```

## How It Works

Codex reads the installed `AGENTS.md` policy. Before spawning subagents, the
primary model runs:

```bash
PYTHONPATH=/home/neil/VSproj/codex-conductor python3 -m conductor.status --pretty
```

That reports the enabled tiers, current spend, reserved budget, active
subagents, and warnings.

Every governed spawn must include a machine-readable task envelope:

```text
<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python3 -m unittest tests.test_ledger -v"],"new_task":true}</CONDUCTOR_TASK>
```

The `PreToolUse` hook checks the requested model and task envelope before Codex
spawns or assigns a new task. It blocks requests when:

- the root run identity cannot be resolved
- the task envelope is missing or invalid
- the spawn would exceed max depth
- the caller tier is not allowed to spawn
- the requested model is not in the enabled ladder
- the task class is not routed to its cheapest enabled owner tier
- high-risk work is routed below the frontier tier
- the child is not strictly cheaper than the parent, except the root's limited
  high-risk frontier exception
- the requested tier is already at its concurrency cap
- the delegated-spawn budget would be exceeded

Lifecycle hooks write subagent start/stop and cost records to the ledger under
`/home/neil/.codex/conductor/state/`.

## Model Ladder

Default tiers are configured in `/home/neil/.codex/conductor/conductor.toml`
after install:

| Tier | Model | Intended Work |
|---|---|---|
| `frontier` | `gpt-5.5` | architecture, high-risk work, integration, review gates |
| `standard` | `gpt-5.4` | implementation, refactors, debugging, cross-module changes |
| `mini` | `gpt-5.4-mini` | tests, docs, mechanical edits, renames, config changes |
| `spark` | `gpt-5.3-codex-spark` | search, summarization, boilerplate, formatting, data extraction |

`mini` and `spark` are enabled automatically only when the models appear in
Codex's local model cache. If an auto tier is unavailable, its classes fall
back to the next stronger enabled tier.

## Install

Run the offline test suite first:

```bash
cd /home/neil/VSproj/codex-conductor
python3 -m unittest discover -s tests -v
```

Install into the real Codex home:

```bash
bash install.sh
```

The installer refuses to proceed if it finds unmanaged `[agents]`, `[hooks]`,
or `[rollout_budget]` tables in `~/.codex/config.toml`, or a foreign
`~/.codex/hooks.json`.

## Required Hook Trust

After installing, open the Codex CLI and trust the new hooks once:

```text
/hooks
```

Codex records hook trust by hash. If the hook definitions change, Codex may ask
you to review and trust them again.

For one-off vetted automation, Codex also supports:

```bash
codex exec --dangerously-bypass-hook-trust "..."
```

Use that only when you already trust the installed hook source.

## Daily Use

To inspect the current run state:

```bash
PYTHONPATH=/home/neil/VSproj/codex-conductor python3 -m conductor.status --pretty
```

To render the latest cost report:

```bash
PYTHONPATH=/home/neil/VSproj/codex-conductor python3 -m conductor.report --last
```

To report a specific run:

```bash
PYTHONPATH=/home/neil/VSproj/codex-conductor python3 -m conductor.report --run <run-id>
```

The installed policy tells the primary Codex agent to include the report at the
end of each delegated run.

## Pricing

Default prices are placeholders. Until you edit the installed config, reports
show:

```text
PRICING UNVERIFIED
```

Set real prices here:

```bash
/home/neil/.codex/conductor/conductor.toml
```

Until prices are set, budget estimates use relative cost weights rather than
real dollar pricing.

## Operational Notes

Live Codex probe/E2E was not run during implementation to avoid token/API
spend. Offline tests were run instead.

You still need to trust the new hooks once in the Codex CLI via `/hooks`.

Prices are placeholders, so reports show `PRICING UNVERIFIED` until you edit
`/home/neil/.codex/conductor/conductor.toml`.

Hooks fail open on unexpected internal errors so Codex does not get bricked.
Controlled policy failures, such as missing task envelopes or budget overflow,
return explicit blocks.

Already-running subagents are never killed by conductor. Budget enforcement
applies only to new governed spawns.

## Environment Variables

- `CODEX_CONDUCTOR_HOME`: state/config root, default `/home/neil/.codex/conductor`
- `CODEX_CONDUCTOR_CONFIG`: config file path, default `$CODEX_CONDUCTOR_HOME/conductor.toml`
- `CONDUCTOR_RUN_USD_CAP`: override delegated-spawn budget for the current process
- `CODEX_CONDUCTOR_SESSIONS_ROOT`: Codex rollout root, default `/home/neil/.codex/sessions`
- `CODEX_MODELS_CACHE`: model cache path, default `/home/neil/.codex/models_cache.json`
- `RUN_LIVE=1`: enables live probe/E2E scripts

## Verification

Offline verification:

```bash
cd /home/neil/VSproj/codex-conductor
python3 -m unittest discover -s tests -v
python3 -m compileall conductor
```

The live probe and smoke scripts are intentionally opt-in:

```bash
RUN_LIVE=1 make probe
RUN_LIVE=1 make e2e
```

Those commands may spend Codex/API usage.

## Uninstall

```bash
cd /home/neil/VSproj/codex-conductor
bash uninstall.sh
```

Uninstall removes only managed blocks and the managed `hooks.json`. Ledger state
under `/home/neil/.codex/conductor/state/` is left in place.
