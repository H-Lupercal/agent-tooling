from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, ROOT, copy_fixture_repo, fixture_state_env


class CoreBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_env = os.environ.copy()
        os.environ.update(fixture_state_env(ROOT))

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_catalog_loads_seed_tools(self) -> None:
        from toolbelt.catalog import load_catalog

        tools = load_catalog()
        self.assertEqual(len(tools), 9)
        self.assertEqual([t.id for t in tools], sorted(t.id for t in tools))
        self.assertIn("mcp-playwright", {t.id for t in tools})

    def test_evidence_scans_node_python_and_existing_tools(self) -> None:
        from toolbelt.evidence import evidence_sha256, scan

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("node_react", td)
            evidence = scan(root)
            keys = {(e.type, e.key) for e in evidence}
            self.assertIn(("manifest_file", "package.json"), keys)
            self.assertIn(("manifest_dep", "package.json:@playwright/test"), keys)
            self.assertIn(("lang_ext", "typescript"), keys)
            self.assertIn(("test_setup", "playwright"), keys)
            self.assertIn(("existing_tool", "codex_mcp:playwright"), keys)
            self.assertEqual(evidence_sha256(evidence), evidence_sha256(list(reversed(evidence))))

            py = copy_fixture_repo("py_fastapi", td)
            py_keys = {(e.type, e.key) for e in scan(py)}
            self.assertIn(("manifest_dep", "pyproject.toml:fastapi"), py_keys)
            self.assertIn(("test_setup", "pytest"), py_keys)
            self.assertIn(("infra", "dockerfile"), py_keys)

    def test_brief_greenfield_and_keywords(self) -> None:
        from toolbelt.brief import brief_goals, brief_stack, is_greenfield, parse_brief
        from toolbelt.catalog import load_catalog

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("greenfield_empty", td, git=False)
            brief = root / "brief.md"
            self.assertTrue(is_greenfield(root))
            (root / "x.py").write_text("print('x')\n", encoding="utf-8")
            self.assertFalse(is_greenfield(root))
            ev = parse_brief(brief, load_catalog())
            keys = {e.key for e in ev}
            self.assertTrue({"brief:e2e", "brief:end to end"} & keys)
            self.assertIn("brief:postgres", keys)
            self.assertGreaterEqual(set(brief_stack(brief)), {"python", "terraform", "typescript"})
            self.assertEqual(brief_goals(brief), ["Ship a Python service", "Use Terraform"])

    def test_recommend_and_plan_gate_provisional_matches(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.evidence import scan
        from toolbelt.plan import build_plan, plan_from_json, plan_to_json
        from toolbelt.recommend import recommend

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("node_react", td)
            catalog = load_catalog()
            recs = recommend(catalog, scan(root), mode="existing", root=root)
            by_id = {r.tool_id: r for r in recs}
            self.assertEqual(by_id["mcp-playwright"].confidence, 6)
            plan = build_plan(recs, catalog, {"tools": {}}, mode="existing", project_root=root)
            planned = [a.tool_id for a in plan.actions]
            self.assertIn("mcp-playwright", planned)
            self.assertNotIn("mcp-postgres", planned)
            self.assertEqual(plan_from_json(plan_to_json(plan)), plan)

    def test_harness_builds_argvs_and_reads_state(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.harness import claude_mcp_servers, claude_plugins, codex_mcp_servers, concrete_steps

        tools = {t.id: t for t in load_catalog()}
        steps = concrete_steps(tools["mcp-playwright"], "project")
        self.assertEqual(
            steps[0].argv,
            (
                os.environ["TOOLBELT_CLAUDE_BIN"],
                "mcp",
                "add",
                "-s",
                "project",
                "playwright",
                "--",
                "npx",
                "-y",
                "@playwright/mcp@latest",
            ),
        )
        for tool in tools.values():
            for step in concrete_steps(tool, tool.install_scope):
                self.assertNotIn("-e", step.argv)
                self.assertNotIn("--env", step.argv)
        self.assertIn("playwright", codex_mcp_servers())
        self.assertIn("superpowers@claude-plugins-official", claude_plugins())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"project-one": {}}}), encoding="utf-8")
            scoped = claude_mcp_servers(root)
            self.assertIn("project-one", scoped["project"])


class CliSmokeTests(unittest.TestCase):
    def test_scan_plan_apply_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("node_react", td)
            env = fixture_state_env(ROOT)
            log = Path(td) / "fake.log"
            env["FAKE_BIN_LOG"] = str(log)
            scan = subprocess.run(
                ["python3", "-m", "toolbelt", "scan", "--path", str(root), "--json"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(scan.stdout)
            self.assertIn("mcp-playwright", {r["tool_id"] for r in payload["recommendations"]})

            subprocess.run(
                ["python3", "-m", "toolbelt", "plan", "--path", str(root)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            before = (root / ".toolbelt" / "manifest.json").read_bytes()
            apply = subprocess.run(
                ["python3", "-m", "toolbelt", "apply", "--path", str(root), "--yes", "--dry-run"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("claude mcp add", apply.stdout)
            self.assertFalse(log.exists())
            self.assertEqual(before, (root / ".toolbelt" / "manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
