<!-- >>> codex-conductor policy >>> -->
## Cost-aware delegation (codex-conductor)

Before spawning a subagent, run
`conductor status --pretty`.
Choose the cheapest enabled tier that owns the task class. Keep decomposition,
integration, final review, and high-risk work at the frontier tier.

Closed task classes:
architecture, high_risk, integration, review_gate, implementation, refactor,
debug, cross_module_change, tests, docs, mechanical_edit, rename,
config_change, search, summarize, boilerplate, formatting, data_extraction.

High-risk triggers:
authentication/authorization, cryptography, payments/billing, database schema
migration, deleting or rewriting more than 200 lines, public API contract
change, concurrency/locking, build or release pipeline change,
security-sensitive input parsing, secrets handling, production configuration.

Every governed spawn/new task must include this envelope in the prompt:
`<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python3 -m unittest tests.test_ledger -v"],"new_task":true}</CONDUCTOR_TASK>`

Always set the `model` field explicitly. Children must be strictly cheaper than
their parent except the root may use up to two same-tier frontier subagents for
high-risk work. Depth is capped at 3. If the budget hook blocks a spawn, finish
the remaining work locally and summarize what was not delegated.

At the end of every run, execute
`conductor report --last`
and include the table in the final response.
<!-- <<< codex-conductor policy <<< -->
