import json
import unittest

from tests.helpers import FIXTURES


class ToolAdapterTests(unittest.TestCase):
    def test_spawn_payload_normalizes_and_extracts_envelope(self):
        from conductor.tool_adapter import normalize_tool_request

        payload = json.loads(
            (FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(
                encoding="utf-8"
            )
        )
        request = normalize_tool_request(payload, {})

        self.assertEqual(request.kind, "spawn")
        self.assertEqual(request.requested_model, "gpt-5.4")
        self.assertEqual(request.requested_effort, "medium")
        self.assertEqual(request.task_name, "tests_ledger")
        self.assertEqual(request.envelope.task_class, "tests")
        self.assertEqual(request.envelope.owned_paths, ("tests/test_ledger.py",))

    def test_spawn_payload_extracts_reasoning_effort(self):
        from conductor.tool_adapter import normalize_tool_request

        request = normalize_tool_request(
            {
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "tests_ledger",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "medium",
                },
            }
        )

        self.assertEqual(request.requested_model, "gpt-5.6-terra")
        self.assertEqual(request.requested_effort, "medium")

    def test_other_tool_is_ignored(self):
        from conductor.tool_adapter import normalize_tool_request

        payload = json.loads(
            (FIXTURES / "hook_payloads" / "pre_tool_use_other.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(normalize_tool_request(payload, {}).kind, "other")

    def test_invalid_envelopes_return_missing_envelope(self):
        from conductor.tool_adapter import normalize_tool_request

        payload = json.loads(
            (FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(
                encoding="utf-8"
            )
        )
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

    def test_provider_correlation_overrides_untrusted_tool_input(self):
        from conductor.tool_adapter import normalize_governed_payload

        payload = json.loads(
            (FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(
                encoding="utf-8"
            )
        )
        payload["tool_input"]["task_id"] = "spoofed-inner-id"
        payload["tool_call_id"] = "provider-call-id"

        exact = normalize_governed_payload(payload)
        self.assertIsNotNone(exact.operation)
        self.assertEqual(exact.operation.correlation_id, "provider-call-id")

        payload.pop("tool_call_id")
        missing = normalize_governed_payload(payload)
        self.assertIsNotNone(missing.operation)
        self.assertIsNone(missing.operation.correlation_id)


if __name__ == "__main__":
    unittest.main()
