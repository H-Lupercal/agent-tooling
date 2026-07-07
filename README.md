# codex-conductor

`codex-conductor` is a cost-aware orchestration layer for **Codex** and **Claude
Code** subagents. It keeps the primary model on the frontier tier, routes bounded
delegated work down to cheaper enabled models, and uses each runtime's **native
hooks** to block subagent spawns that violate the task envelope, tier ladder,
depth limit, concurrency caps, or delegated-spawn budget.

It is a **stdlib-only Python project** — no third-party dependencies. It does not
modify the Codex or Claude Code binary and it does not run a wrapper daemon.
Enforcement happens entirely through each provider's native hook system and is
intentionally a **guardrail, not a hard billing or security boundary**: hooks
fail open on internal errors, and already-running subagents are never killed.

## Requirements

- **Python 3.11 or newer.** The config loader uses the stdlib `tomllib` module
  and the hooks use `datetime.UTC`, both introduced in 3.11.
- **A POSIX host (Linux or macOS).** The ledger serializes concurrent writes
  with `fcntl.flock`, which is not available on Windows.
- **Codex CLI** and/or **Claude Code**, each with native hook support.

You can run everything straight from a checkout
(`PYTHONPATH="$PWD" python3 -m conductor.<command>`). Optionally, an editable
install adds a `conductor` command - see
[The `conductor` command](#the-conductor-command).

## What It Installs

The installer writes only marked, managed files or blocks, so it can be cleanly
uninstalled.

For Codex (`bash install.sh`):

- `~/.codex/hooks.json`
- `~/.codex/conductor/` (config, hook wrappers, ledger state)
- a managed `[agents]` block in `~/.codex/config.toml`
- a managed delegation-policy block in `~/AGENTS.md`

For Claude Code (`bash install.sh --provider claude`):

- merged hook entries in `~/.claude/settings.json` (existing non-conductor hooks
  are preserved)
- `~/.claude/conductor/` (config, hook wrappers, ledger state)
- a managed delegation-policy block in `~/.claude/CLAUDE.md`

The source project can be cloned anywhere. The installer renders the current
checkout path into the generated hook wrappers and installed policy, so the
provider home always points back at this checkout.

## How It Works

Codex reads the installed `~/AGENTS.md` policy; Claude Code reads the installed
`~/.claude/CLAUDE.md` policy. Both instruct the primary model to inspect state
before delegating:

```bash
PYTHONPATH=/path/to/codex-conductor python3 -m conductor.status --pretty
```

That reports the enabled tiers, current spend, reserved budget, active subagents,
and warnings.

Every governed spawn must carry a machine-readable task envelope in its prompt:

```text
<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python3 -m unittest tests.test_ledger -v"],"new_task":true}</CONDUCTOR_TASK>
```

The `PreToolUse` hook inspects the requested model and envelope before Codex
spawns or assigns a new task, or before Claude Code invokes the `Task` tool. Each
block reason is recorded in the ledger under a rule code:

- **R1** — the root run identity cannot be resolved
- **R2** — the task envelope is missing or invalid
- **R3** — the spawn would exceed `policy.max_depth`
- **R5** — the caller's tier has `may_spawn = false`
- **R6** — the requested model is not in the enabled ladder
- **R6_CLASS** — the task class is not routed to its cheapest enabled owner tier
- **R7** — high-risk work (task class `high_risk` or any `risk_triggers`) is
  routed below the frontier tier
- **R8** — the child is not strictly cheaper than the parent (including "never
  spawn a stronger model"), except the root's limited same-tier frontier
  exception for high-risk work
- **R9** — the requested tier is already at its `max_concurrent` cap
- **R10** — the delegated-spawn budget would be exceeded (if `budget.enforce =
  false`, this warns and approves instead of blocking)

A caller whose model is outside the ladder is logged and allowed through (rule
R4); enforcement resumes for any governed child it spawns.

Lifecycle hooks (`SubagentStart` / `SubagentStop`) append subagent start, stop,
and cost records to the per-run ledger under
`~/.codex/conductor/state/<run-id>/` or `~/.claude/conductor/state/<run-id>/`.

## Model Ladder

Tiers are listed **strongest first**; "cheaper" means later in the list.
Enforcement depends on this ordering — do not reorder tiers when editing config.

**The model ids below are defaults you are expected to edit** to match the models
your account can actually run. The Codex ids in particular are placeholders.

Codex defaults (`~/.codex/conductor/conductor.toml`):

| Tier | Model | May spawn | Intended Work |
|---|---|---|---|
| `frontier` | `gpt-5.5` | yes | architecture, high-risk work, integration, review gates |
| `standard` | `gpt-5.4` | yes | implementation, refactors, debugging, cross-module changes |
| `mini` | `gpt-5.4-mini` | yes | tests, docs, mechanical edits, renames, config changes |
| `spark` | `gpt-5.3-codex-spark` | no | search, summarization, boilerplate, formatting, data extraction |

Claude Code defaults (`~/.claude/conductor/conductor.toml`):

| Tier | Model | May spawn | Intended Work |
|---|---|---|---|
| `frontier` | `claude-opus-4-8` | yes | architecture, high-risk work, integration, review gates |
| `standard` | `claude-sonnet-5` | no | implementation, refactors, debugging, cross-module changes |
| `mini` | `claude-haiku-4-5` | no | tests, docs, mechanical edits, searches, summaries, formatting, data extraction |

`enabled` may be `always`, `auto`, or `never`. An `auto` tier is enabled only
when its model appears in Codex's local model cache
(`~/.codex/models_cache.json`); the Codex `mini` and `spark` tiers ship as
`auto`. When an owner tier is unavailable, that task class falls back to the next
stronger **enabled** tier.

Because `may_spawn = false` on every Claude tier except `frontier`, Claude
delegation is a **single hop**: the primary spawns subagents, and those subagents
do the work themselves rather than re-delegating.

Claude `Task` calls may pass the model as a full id or as an alias — `opus`,
`sonnet`, `haiku`, `fable` — which conductor normalizes to the configured model
ids before enforcing the ladder.

## Install

Run the offline test suite first:

```bash
cd /path/to/codex-conductor
python3 -m unittest discover -s tests -v
```

Install into the real Codex home:

```bash
bash install.sh
```

The installer **refuses to proceed** if it finds unmanaged `[agents]`,
`[hooks]`, or `[rollout_budget]` tables in `~/.codex/config.toml`, or a foreign
`~/.codex/hooks.json`. Use `--dry-run` to preview the exact diffs first.

Install into the real Claude Code home:

```bash
bash install.sh --provider claude
```

The Claude installer merges managed hook entries into `~/.claude/settings.json`
and preserves existing non-conductor hooks.

## Required Hook Trust

After installing Codex support, open the Codex CLI and trust the new hooks once:

```text
/hooks
```

Codex records hook trust by hash, so it may ask you to review and re-trust if the
hook definitions change. For one-off vetted automation you can also run:

```bash
codex exec --dangerously-bypass-hook-trust "..."
```

Use that only when you already trust the installed hook source.

For Claude Code, review `~/.claude/settings.json` after install if your setup
requires hook approval or managed-settings review.

## The `conductor` command

An editable install from the checkout adds a single `conductor` entry point:

```bash
pip install -e .
```

Use `-e` (editable): the project keeps operating from its checkout - the
installer renders that checkout path into the hooks - so a non-editable install
is not supported. The command groups every subcommand:

```bash
conductor status --provider codex --pretty
conductor report --provider claude --last
conductor doctor --provider claude
conductor install --provider claude
conductor uninstall
conductor gc --keep 20            # keep the newest 20 run ledgers, delete the rest
conductor gc --older-than-days 30 # delete run ledgers older than 30 days
```

`conductor <cmd>` is exactly equivalent to
`PYTHONPATH="$PWD" python3 -m conductor.<cmd>`; use whichever you prefer. Run
`conductor gc` between sessions, not during an active run.

## Daily Use

Run these from the repository checkout. By default they read the **Codex** home
(`~/.codex/conductor`); pass `--provider claude` (below) or set
`CODEX_CONDUCTOR_HOME=~/.claude/conductor` to target a Claude Code install.

Inspect the current run state:

```bash
PYTHONPATH="$PWD" python3 -m conductor.status --pretty
```

Render the latest cost report:

```bash
PYTHONPATH="$PWD" python3 -m conductor.report --last
```

Report a specific run, or emit JSON:

```bash
PYTHONPATH="$PWD" python3 -m conductor.report --run <run-id>
PYTHONPATH="$PWD" python3 -m conductor.report --last --json
```

To inspect a Claude Code install, add `--provider claude` to either command:

```bash
PYTHONPATH="$PWD" python3 -m conductor.status --provider claude --pretty
PYTHONPATH="$PWD" python3 -m conductor.report --provider claude --last
```

The installed policy tells the primary agent to append the report at the end of
each delegated run.

## Health check

Verify an install end-to-end for either provider:

```bash
PYTHONPATH="$PWD" python3 -m conductor.doctor --provider codex
PYTHONPATH="$PWD" python3 -m conductor.doctor --provider claude
```

`doctor` checks Python/platform support, config validity and pricing, hook
installation, the delegation-policy block, and (for Codex) the model cache. It
prints one line per check and exits non-zero if any check fails. Add `--json`
for machine-readable output.

## Cost Report

The report groups spend by tier and estimates savings against a **frontier
baseline** — the hypothetical cost of every recorded token if it had all run on
the frontier tier. That baseline assumes identical token counts across tiers and
that all delegated work would otherwise have been done at frontier, so treat
`savings_pct` as an optimistic estimate, not an exact figure.

## Pricing

Default prices are placeholders. Until you edit the installed config, reports
print:

```text
PRICING UNVERIFIED
```

Set real prices in the provider's installed config:

```text
~/.codex/conductor/conductor.toml     # Codex
~/.claude/conductor/conductor.toml    # Claude Code
```

Until prices are set, budget estimates and reports use relative cost weights
(`relative_cost_weight`) rather than real dollar pricing.

## Environment Variables

The Claude install sets these same `CODEX_`-prefixed variables to its `~/.claude`
paths, so the names apply to both providers.

- `CODEX_CONDUCTOR_HOME` — state/config root; default `~/.codex/conductor`
- `CODEX_CONDUCTOR_CONFIG` — config file path; default
  `$CODEX_CONDUCTOR_HOME/conductor.toml`, falling back to the checkout's
  `config/conductor.toml`
- `CONDUCTOR_RUN_USD_CAP` — override the delegated-spawn budget for the current
  process
- `CODEX_CONDUCTOR_SESSIONS_ROOT` — Codex rollout root; default `~/.codex/sessions`
- `CODEX_MODELS_CACHE` — model cache path; default `~/.codex/models_cache.json`
- `RUN_LIVE=1` — enables the opt-in live probe / E2E scripts

## Guarantees & Limitations

- **Fail-open.** Hooks that hit an unexpected internal error approve the request
  and log to `state/errors.log` so the agent is never bricked. Controlled policy
  failures (missing envelope, budget overflow, etc.) return explicit blocks.
- **No retroactive enforcement.** Budget and concurrency limits apply only to
  new governed spawns. Already-running subagents are never killed.
- **Not a security boundary.** A determined agent that omits the envelope or
  calls an unmatched tool is simply not governed. This is a cost guardrail, not a
  sandbox.
- **Estimated costs.** With `PRICING UNVERIFIED`, all dollar figures are relative
  weights, not real spend.

## Verification

Offline verification (no provider/API usage):

```bash
cd /path/to/codex-conductor
python3 -m unittest discover -s tests -v
python3 -m compileall conductor
```

The live probe and smoke scripts are intentionally opt-in and may spend
provider/API usage:

```bash
RUN_LIVE=1 make probe
RUN_LIVE=1 make e2e
```

Note: `probe/probe.py` is currently a manual-run placeholder — it prints setup
guidance rather than driving a live provider. Live end-to-end validation is a
manual step, not part of the automated suite.

## Uninstall

```bash
cd /path/to/codex-conductor
bash uninstall.sh                    # Codex
bash uninstall.sh --provider claude  # Claude Code
```

Uninstall removes only managed blocks and managed hook entries. Ledger state
under the provider's `conductor/state/` directory is left in place; delete it
manually if you want to reclaim the space.
