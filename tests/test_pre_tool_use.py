import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, FIXTURES, restore_env, set_env, write_config, write_models_cache


class PreToolUseDecisionTests(unittest.TestCase):
    def setUp(self):
        from conductor.config import load_ladder
        from conductor.identity import Caller

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        old = set_env(CODEX_CONDUCTOR_HOME=str(self.root / "home"))
        self.addCleanup(restore_env, old)
        self.addCleanup(self.tmp.cleanup)
        self.ladder = load_ladder(write_config(self.root / "conductor.toml", DEFAULT_CONFIG))
        self.enabled = [0, 1, 2, 3]
        self.caller = Caller("run", "root-run", 0, 0, "gpt-5.5")
        self.payload = json.loads((FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(encoding="utf-8"))

    def decide(self, payload=None, events=None, caller=None):
        from conductor.hooks.pre_tool_use import decide

        return decide(payload or self.payload, self.ladder, events or [], self.enabled, caller or self.caller)

    def test_valid_root_frontier_to_standard_approves(self):
        self.payload["tool_input"]["message"] = self.payload["tool_input"]["message"].replace('"task_class":"tests"', '"task_class":"implementation"')
        self.assertEqual(self.decide().decision, "approve")

    def test_task_class_must_use_cheapest_enabled_owner_or_stronger_fallback(self):
        self.assertEqual(self.decide().rule, "R6_CLASS")

        from conductor.hooks.pre_tool_use import decide

        self.assertEqual(decide(self.payload, self.ladder, [], [0, 1], self.caller).decision, "approve")

    def test_missing_run_id_blocks(self):
        self.assertEqual(self.decide(caller=replace(self.caller, run_id=None)).rule, "R1")

    def test_missing_envelope_blocks(self):
        payload = json.loads(json.dumps(self.payload))
        payload["tool_input"]["message"] = "missing"

        self.assertEqual(self.decide(payload=payload).rule, "R2")

    def test_same_tier_root_exception_allows_two_then_blocks(self):
        payload = json.loads(json.dumps(self.payload))
        payload["tool_input"]["model"] = "gpt-5.5"
        payload["tool_input"]["message"] = payload["tool_input"]["message"].replace('"task_class":"tests"', '"task_class":"high_risk"')
        events = [
            {"event": "spawn_approved", "caller_depth": 0, "caller_tier": "frontier", "tier": "frontier"},
            {"event": "spawn_approved", "caller_depth": 0, "caller_tier": "frontier", "tier": "frontier"},
        ]

        self.assertEqual(self.decide(payload=payload, events=[]).decision, "approve")
        self.assertEqual(self.decide(payload=payload, events=events).rule, "R8")

    def test_stronger_or_equal_non_root_child_blocks(self):
        payload = json.loads(json.dumps(self.payload))
        payload["tool_input"]["model"] = "gpt-5.5"
        payload["tool_input"]["message"] = payload["tool_input"]["message"].replace('"task_class":"tests"', '"task_class":"high_risk"')
        caller = replace(self.caller, depth=1, tier_index=1, model="gpt-5.4")

        self.assertEqual(self.decide(payload=payload, caller=caller).rule, "R8")

    def test_disabled_requested_tier_blocks(self):
        from conductor.hooks.pre_tool_use import decide

        payload = json.loads(json.dumps(self.payload))
        payload["tool_input"]["model"] = "gpt-5.4-mini"
        decision = decide(payload, self.ladder, [], [0, 1], self.caller)
        self.assertEqual(decision.rule, "R6")

    def test_high_risk_requires_frontier(self):
        payload = json.loads(json.dumps(self.payload))
        payload["tool_input"]["message"] = payload["tool_input"]["message"].replace('"task_class":"tests"', '"task_class":"high_risk"')

        self.assertEqual(self.decide(payload=payload).rule, "R7")

    def test_depth_may_spawn_concurrency_and_budget_blocks(self):
        self.payload["tool_input"]["message"] = self.payload["tool_input"]["message"].replace('"task_class":"tests"', '"task_class":"implementation"')
        self.assertEqual(self.decide(caller=replace(self.caller, depth=3)).rule, "R3")
        self.assertEqual(self.decide(caller=replace(self.caller, tier_index=3, model="gpt-5.3-codex-spark")).rule, "R5")
        active = [{"event": "subagent_start", "tier": "standard", "thread_id": f"c{i}"} for i in range(4)]
        self.assertEqual(self.decide(events=active).rule, "R9")
        spent = [{"event": "cost_recorded", "usd": 9.9}]
        self.assertEqual(self.decide(events=spent).rule, "R10")

    def test_warn_only_budget_approves(self):
        from conductor.config import load_ladder
        from conductor.hooks.pre_tool_use import decide

        text = DEFAULT_CONFIG.replace("enforce = true", "enforce = false")
        ladder = load_ladder(write_config(self.root / "warn.toml", text))
        payload = json.loads(json.dumps(self.payload))
        payload["tool_input"]["message"] = payload["tool_input"]["message"].replace('"task_class":"tests"', '"task_class":"implementation"')
        decision = decide(payload, ladder, [{"event": "cost_recorded", "usd": 9.9}], self.enabled, self.caller)

        self.assertEqual(decision.decision, "approve")
        self.assertEqual(decision.rule, "R10_WARN")

    def test_unknown_caller_and_other_tools_approve(self):
        other = json.loads((FIXTURES / "hook_payloads" / "pre_tool_use_other.json").read_text(encoding="utf-8"))

        self.assertEqual(self.decide(payload=other).decision, "approve")
        self.assertEqual(self.decide(caller=replace(self.caller, tier_index=None, model="outside")).rule, "R4")


if __name__ == "__main__":
    unittest.main()
