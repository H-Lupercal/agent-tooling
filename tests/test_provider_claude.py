import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import restore_env, set_env, write_config


CLAUDE_CONFIG = """
schema_version = 1

[budget]
run_usd_cap = 10.00
warn_at_fraction = 0.75
enforce = true

[policy]
max_depth = 2
require_strictly_cheaper = true
same_tier_spawns_from_root_max = 2
retry_same_tier_max = 1

[[tier]]
name = "frontier"
model = "claude-opus-4-8"
reasoning_effort = "high"
enabled = "always"
input_usd_per_mtok = 15.0
cached_input_usd_per_mtok = 1.5
output_usd_per_mtok = 75.0
relative_cost_weight = 100
est_task_usd = 2.00
max_concurrent = 2
may_spawn = true
task_classes = ["architecture", "high_risk", "integration", "review_gate"]

[[tier]]
name = "standard"
model = "claude-sonnet-5"
reasoning_effort = "medium"
enabled = "always"
input_usd_per_mtok = 3.0
cached_input_usd_per_mtok = 0.3
output_usd_per_mtok = 15.0
relative_cost_weight = 25
est_task_usd = 0.60
max_concurrent = 4
may_spawn = false
task_classes = ["implementation", "refactor", "debug", "cross_module_change"]

[[tier]]
name = "mini"
model = "claude-haiku-4-5"
reasoning_effort = "medium"
enabled = "always"
input_usd_per_mtok = 1.0
cached_input_usd_per_mtok = 0.1
output_usd_per_mtok = 5.0
relative_cost_weight = 6
est_task_usd = 0.15
max_concurrent = 6
may_spawn = false
task_classes = ["tests", "docs", "mechanical_edit", "rename", "config_change", "search", "summarize", "boilerplate", "formatting", "data_extraction"]
""".strip()


ENVELOPE = (
    '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"impl_worker",'
    '"task_class":"implementation","risk_triggers":[],"owned_paths":["conductor/providers/claude.py"],'
    '"acceptance_checks":["python3 -m unittest tests.test_provider_claude -v"],"new_task":true}</CONDUCTOR_TASK>'
)


def claude_task_payload(**tool_input):
    data = {
        "session_id": "claude-run",
        "transcript_path": "",
        "cwd": "/tmp/project",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Task",
        "tool_input": {
            "subagent_type": "general-purpose",
            "model": "sonnet",
            "description": "Implement Claude support",
            "prompt": ENVELOPE + "\nDo the work.",
        },
    }
    data["tool_input"].update(tool_input)
    return data


class ClaudeProviderTests(unittest.TestCase):
    def test_task_payload_normalizes_alias_and_emits_claude_decision(self):
        from conductor.providers.claude import PROVIDER

        request = PROVIDER.normalize_request(claude_task_payload())
        allowed = PROVIDER.emit_decision("approve", "spawn approved")
        denied = PROVIDER.emit_decision("block", "missing envelope")

        self.assertEqual(request.kind, "spawn")
        self.assertEqual(request.requested_model, "claude-sonnet-5")
        self.assertEqual(request.task_name, "impl_worker")
        self.assertEqual(request.envelope.task_class, "implementation")
        self.assertEqual(allowed["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_approval_is_pending_until_real_subagent_start(self):
        from conductor.config import load_ladder
        from conductor.identity import Caller
        from conductor.ledger import append_event, read_events
        from conductor.providers.claude import PROVIDER

        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(Path(tmp) / "conductor.toml", CLAUDE_CONFIG)),
            )
            try:
                ladder = load_ladder()
                request = PROVIDER.normalize_request(claude_task_payload())
                caller = Caller("claude-run", "claude-run", 0, 0, "claude-opus-4-8")

                pending = PROVIDER.post_approve_events(request, caller, ladder)
                self.assertEqual([event["event"] for event in pending], ["claude_spawn_pending"])
                append_event("claude-run", pending[0])

                PROVIDER.handle_lifecycle(
                    {
                        "hook_event_name": "SubagentStart",
                        "session_id": "claude-run",
                        "agent_id": "agent-1",
                        "agent_type": "general-purpose",
                    }
                )
                events = read_events("claude-run")
                starts = [event for event in events if event.get("event") == "subagent_start"]

                self.assertEqual(starts[-1]["thread_id"], "agent-1")
                self.assertEqual(starts[-1]["model"], "claude-sonnet-5")
                self.assertEqual(starts[-1]["tier"], "standard")
            finally:
                restore_env(old)

    def test_resolve_caller_inside_subagent_uses_active_start_record(self):
        from conductor.config import load_ladder
        from conductor.ledger import append_event
        from conductor.providers.claude import PROVIDER

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(root / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(root / "conductor.toml", CLAUDE_CONFIG)),
            )
            try:
                append_event(
                    "claude-run",
                    {
                        "event": "subagent_start",
                        "thread_id": "agent-1",
                        "parent_thread_id": "claude-run",
                        "model": "claude-sonnet-5",
                        "tier": "standard",
                    },
                )

                caller = PROVIDER.resolve_caller(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "claude-run",
                        "agent_id": "agent-1",
                        "tool_name": "Task",
                        "tool_input": {},
                    },
                    load_ladder(),
                )

                self.assertEqual(caller.run_id, "claude-run")
                self.assertEqual(caller.thread_id, "agent-1")
                self.assertEqual(caller.depth, 1)
                self.assertEqual(caller.tier_index, 1)
                self.assertEqual(caller.model, "claude-sonnet-5")
            finally:
                restore_env(old)

    def test_subagent_stop_records_sidechain_cost_delta_and_closes_matching_agent(self):
        from conductor.ledger import active_spawns, append_event, read_events
        from conductor.providers.claude import PROVIDER

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "transcript.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant",
                                "isSidechain": True,
                                "message": {
                                    "model": "claude-sonnet-5",
                                    "usage": {
                                        "input_tokens": 100,
                                        "cache_read_input_tokens": 20,
                                        "cache_creation_input_tokens": 30,
                                        "output_tokens": 40,
                                    },
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "isSidechain": False,
                                "message": {
                                    "model": "claude-opus-4-8",
                                    "usage": {"input_tokens": 999, "output_tokens": 999},
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(root / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(root / "conductor.toml", CLAUDE_CONFIG)),
            )
            try:
                append_event(
                    "claude-run",
                    {
                        "event": "subagent_start",
                        "thread_id": "agent-1",
                        "parent_thread_id": "claude-run",
                        "model": "claude-sonnet-5",
                        "tier": "standard",
                    },
                )

                PROVIDER.handle_lifecycle(
                    {
                        "hook_event_name": "SubagentStop",
                        "session_id": "claude-run",
                        "agent_id": "agent-1",
                        "status": "completed",
                        "transcript_path": str(transcript),
                    }
                )
                events = read_events("claude-run")
                costs = [event for event in events if event.get("event") == "cost_recorded"]

                self.assertEqual(costs[-1]["model"], "claude-sonnet-5")
                self.assertEqual(costs[-1]["tokens"]["input_tokens"], 150)
                self.assertEqual(costs[-1]["tokens"]["cached_input_tokens"], 20)
                self.assertEqual(costs[-1]["tokens"]["output_tokens"], 40)
                self.assertEqual(active_spawns(events), {"standard": []})
            finally:
                restore_env(old)


if __name__ == "__main__":
    unittest.main()
