<!-- >>> codex-conductor policy >>> -->
## Cost-aware delegation (codex-conductor, Claude Code)

Before spawning a subagent with the `Task` tool, run
`conductor status --provider claude --last --pretty`.
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

Every governed `Task` call sets the `model` field to the worker model you
choose (or omits it to run the worker on your own model) and includes this
envelope in the `prompt`:
`<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python -m pytest tests/test_ledger.py -q"],"new_task":true}</CONDUCTOR_TASK>`

Model field accepts the aliases `opus`, `sonnet`, `haiku` or full model ids.
You choose the worker model; Conductor validates only that your choice does not
exceed your own model generation or capability ceiling, and never rewrites the
request or picks a replacement. Reasoning effort is fixed by the chosen subagent
definition rather than the `Task` call, so Conductor does not enforce an effort
ceiling for Claude. Children must be strictly cheaper than you (the frontier
primary), except that you may run up to two same-tier frontier subagents for
high-risk work, and high-risk work stays on the frontier tier. Subagents should
not spawn further `Task` calls; if conductor blocks a
nested spawn, finish that work in the current agent and summarize what was not
delegated. If the budget hook blocks a spawn, finish the remaining work
yourself and summarize what was not delegated.

At the end of every run, execute
`conductor report --provider claude --last`
and include the table in the final response.
<!-- <<< codex-conductor policy <<< -->
