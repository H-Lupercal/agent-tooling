<!-- >>> codex-conductor policy >>> -->
## Cost-aware delegation (codex-conductor, Claude Code)

Before spawning a subagent with the `Task` tool, run
`python3 -m conductor.status --provider claude --pretty`.
Choose the cheapest enabled tier that owns the task class. Keep decomposition,
integration, final review, and high-risk work on the frontier tier (yourself).

Closed task classes:
architecture, high_risk, integration, review_gate, implementation, refactor,
debug, cross_module_change, tests, docs, mechanical_edit, rename,
config_change, search, summarize, boilerplate, formatting, data_extraction.

High-risk triggers:
authentication/authorization, cryptography, payments/billing, database schema
migration, deleting or rewriting more than 200 lines, public API contract
change, concurrency/locking, build or release pipeline change,
security-sensitive input parsing, secrets handling, production configuration.

Every governed `Task` call must set the `model` field to the chosen tier's
model and include this envelope in the `prompt`:
`<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python3 -m unittest tests.test_ledger -v"],"new_task":true}</CONDUCTOR_TASK>`

Model field accepts the aliases `opus`, `sonnet`, `haiku` or full model ids.
The task class determines the required tier: if the `model` you pass does not
match the tier that owns the task class, the spawn is blocked with the correct
target. Children must be strictly cheaper than you (the frontier primary),
except that you may run up to two same-tier frontier subagents for high-risk
work. Subagents should not spawn further `Task` calls; if conductor blocks a
nested spawn, finish that work in the current agent and summarize what was not
delegated. If the budget hook blocks a spawn, finish the remaining work
yourself and summarize what was not delegated.

At the end of every run, execute
`python3 -m conductor.report --provider claude --last`
and include the table in the final response.
<!-- <<< codex-conductor policy <<< -->
