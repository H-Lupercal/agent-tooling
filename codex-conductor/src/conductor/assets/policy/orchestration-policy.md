<!-- >>> codex-conductor policy >>> -->
## Cost-aware delegation (codex-conductor)

Before spawning a subagent, run
`conductor status --last --pretty`.
You choose the worker model and reasoning effort using the task's actual
context. Treat task-class ownership as a recommendation, not an automatic
router. Keep decomposition, integration, final review, and high-risk work at
the frontier tier.

Closed task classes:
architecture, high_risk, integration, review_gate, implementation, refactor,
debug, cross_module_change, tests, docs, mechanical_edit, rename,
config_change, search, summarize, boilerplate, formatting, data_extraction.

High-risk triggers:
authentication/authorization, cryptography, payments/billing, database schema
migration, deleting or rewriting more than 200 lines, public API contract
change, concurrency/locking, build or release pipeline change,
security-sensitive input parsing, secrets handling, production configuration.

Every governed spawn/new task must include this envelope. For Codex native
`collaboration.spawn_agent`, append it to the plaintext `task_name` after a
newline and wrap it in `<HOOK_CONTEXT>...</HOOK_CONTEXT>`; Codex strips that
suffix before creating the child path. The `message` argument is encrypted
before local hooks can inspect it. For other governed tools, include the
envelope in the prompt:
`<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python -m pytest tests/test_ledger.py -q"],"new_task":true}</CONDUCTOR_TASK>`

In routing mode, pass `model` on an override spawn. You may also pass
`reasoning_effort`; when omitted, Conductor selects the highest effort supported
by the worker that does not exceed the caller. Conductor never rewrites an
explicit model or effort selection. The caller is the authority
ceiling: a child may not exceed its generation, configured capability, or
effort, and descendants inherit the reduced ceiling.
A GPT-5.5 caller cannot spawn a GPT-5.6 worker.
Use `fork_turns="all"` without either
override to inherit both dimensions exactly.

If a request is denied, retry with any combination named by the denial that is
within the caller ceiling, keep the work local, or restructure it. Exact
same-model workers at the same or lower effort are allowed at any depth, subject
to the ordinary depth, concurrency, and budget limits. Depth is capped at 3.
Never claim routing savings for equal-cost models or outside `mode=routing`.

At the end of every run, execute
`conductor report --last`
and include the table in the final response.
<!-- <<< codex-conductor policy <<< -->
