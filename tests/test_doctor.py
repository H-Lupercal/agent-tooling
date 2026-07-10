import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


class DoctorTests(unittest.TestCase):
    def test_codex_all_pass_after_install(self):
        from conductor.doctor import render_human, run_checks
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            agents = Path(tmp) / "AGENTS.md"
            install(codex_home=codex_home, agents_path=agents)
            report = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertEqual(report["schema_version"], 1)
            self.assertTrue(report["ok"])
            self.assertEqual(statuses["hooks_json"], "ok")
            self.assertEqual(statuses["hook_wrappers"], "ok")
            self.assertEqual(statuses["models_cache"], "warn")
            self.assertTrue(any("trust" in note.lower() for note in report["notes"]))
            self.assertIn("NOTE", render_human(report))

    def test_codex_missing_install_fails(self):
        from conductor.doctor import run_checks

        with tempfile.TemporaryDirectory() as tmp:
            report = run_checks(
                "codex", home=Path(tmp) / ".codex", policy_path=Path(tmp) / "AGENTS.md"
            )
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertFalse(report["ok"])
            self.assertEqual(statuses["hooks_json"], "fail")

    def test_claude_all_pass_after_install(self):
        from conductor.doctor import run_checks
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            claude_home = Path(tmp) / ".claude"
            claude_home.mkdir()
            claude_md = claude_home / "CLAUDE.md"
            install(
                provider="claude", claude_home=claude_home, claude_md_path=claude_md
            )
            report = run_checks("claude", home=claude_home, policy_path=claude_md)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertTrue(report["ok"])
            self.assertEqual(statuses["settings_hooks"], "ok")

    def test_manifest_drift_is_a_hard_failure_and_strict_promotes_warnings(self):
        from conductor.doctor import run_checks
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / ".codex"
            agents = root / "AGENTS.md"
            install(codex_home=codex_home, agents_path=agents)

            strict = run_checks(
                "codex", home=codex_home, policy_path=agents, strict=True
            )
            self.assertFalse(strict["ok"])
            self.assertTrue(strict["degraded"])

            wrapper = codex_home / "conductor" / "hooks" / "lifecycle.py"
            wrapper.write_text("# tampered\n", encoding="utf-8")
            report = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertFalse(report["ok"])
            self.assertEqual(statuses["manifest"], "fail")
            self.assertEqual(statuses["hook_wrappers"], "fail")

    def test_manifest_scope_tampering_is_a_hard_failure(self):
        from conductor.doctor import run_checks
        from conductor.install import install

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / ".codex"
            agents = root / "AGENTS.md"
            install(codex_home=codex_home, agents_path=agents)
            victim = root / "victim.txt"
            victim.write_text("untouched\n", encoding="utf-8")
            manifest_path = codex_home / "conductor" / "managed-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][str(victim)] = {
                "ownership": "full",
                "sha256": hashlib.sha256(victim.read_bytes()).hexdigest(),
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in report["checks"]}

            self.assertFalse(report["ok"])
            self.assertEqual(statuses["manifest"], "fail")
            self.assertEqual(victim.read_text(encoding="utf-8"), "untouched\n")

    def test_doctor_validates_store_context_and_detects_digest_drift(self):
        from conductor.config import config_digest, load_config
        from conductor.doctor import run_checks
        from conductor.install import install
        from conductor.schemas import RunContext
        from conductor.store import Store
        from tests.helpers import write_models_cache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / ".codex"
            agents = root / "AGENTS.md"
            install(codex_home=codex_home, agents_path=agents)
            write_models_cache(codex_home / "models_cache.json", ["gpt-5.5"])
            config = load_config(codex_home / "conductor" / "conductor.toml")
            now = datetime.now(UTC)
            context = RunContext(
                provider="codex",
                run_id="doctor-run",
                thread_id="doctor-run",
                root_model="gpt-5.5",
                model_source="operator",
                provider_contract="codex-current",
                contract_digest="0" * 64,
                mode="admission",
                generation=1,
                started_at=now,
                heartbeat_at=now,
                config_digest=config_digest(config),
            )
            store = Store(codex_home / "conductor" / "state" / "conductor.db")
            store.create_run(
                context.run_id,
                provider="codex",
                generation=1,
                mode="admission",
                context=context.model_dump(mode="json"),
            )

            healthy = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in healthy["checks"]}
            self.assertEqual(statuses["store"], "ok")
            self.assertEqual(statuses["run_context"], "ok")
            self.assertEqual(statuses["models_cache"], "ok")

            drifted = context.model_copy(update={"config_digest": "f" * 64})
            store.create_run(
                context.run_id,
                provider="codex",
                generation=1,
                mode="admission",
                context=drifted.model_dump(mode="json"),
            )
            report = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertEqual(statuses["run_context"], "fail")

            store.create_run(
                "invalid-latest",
                provider="codex",
                generation=1,
                mode="admission",
                context=None,
            )
            invalid = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in invalid["checks"]}
            self.assertFalse(invalid["ok"])
            self.assertEqual(statuses["run_context"], "fail")


if __name__ == "__main__":
    unittest.main()
