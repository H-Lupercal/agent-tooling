import json
import unittest

from tests.helpers import FIXTURES


class ToolAdapterTests(unittest.TestCase):
    def test_spawn_payload_normalizes_and_extracts_envelope(self):
        from conductor.tool_adapter import normalize_tool_request

        payload = json.loads((FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(encoding="utf-8"))
        request = normalize_tool_request(payload, {})

        self.assertEqual(request.kind, "spawn")
        self.assertEqual(request.requested_model, "gpt-5.4")
        self.assertEqual(request.task_name, "tests_ledger")
        self.assertEqual(request.envelope.task_class, "tests")
        self.assertEqual(request.envelope.owned_paths, ("tests/test_ledger.py",))

    def test_other_tool_is_ignored(self):
        from conductor.tool_adapter import normalize_tool_request

        payload = json.loads((FIXTURES / "hook_payloads" / "pre_tool_use_other.json").read_text(encoding="utf-8"))

        self.assertEqual(normalize_tool_request(payload, {}).kind, "other")

    def test_invalid_envelopes_return_missing_envelope(self):
        from conductor.tool_adapter import normalize_tool_request

        payload = json.loads((FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(encoding="utf-8"))
        cases = [
            "no envelope",
            "<CONDUCTOR_TASK>{not-json}</CONDUCTOR_TASK>",
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"x","task_class":"unknown","risk_triggers":[],"owned_paths":["x"],"acceptance_checks":["check"],"new_task":true}</CONDUCTOR_TASK>',
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"x","task_class":"tests","risk_triggers":["bad"],"owned_paths":["x"],"acceptance_checks":["check"],"new_task":true}</CONDUCTOR_TASK>',
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"x","task_class":"tests","risk_triggers":[],"owned_paths":[],"acceptance_checks":["check"],"new_task":true}</CONDUCTOR_TASK>',
        ]
        for message in cases:
            with self.subTest(message=message):
                payload["tool_input"]["message"] = message
                self.assertIsNone(normalize_tool_request(payload, {}).envelope)


if __name__ == "__main__":
    unittest.main()
