from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
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

    def test_scan_records_repo_relative_sources(self) -> None:
        from toolbelt.cli import _cmd_scan
        from toolbelt.manifest import load_manifest

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("node_react", td)
            args = type("Args", (), {"path": str(root), "json": True})()
            with redirect_stdout(StringIO()):
                self.assertEqual(_cmd_scan(args), 0)
            manifest = load_manifest(root)
            sources = [e["source"] for e in manifest["last_scan"]["evidence"]]
            file_sources = [s for s in sources if s not in {"codex config", "claude plugins", "brief"}]
            self.assertTrue(file_sources)
            self.assertTrue(all(not Path(source).is_absolute() for source in file_sources))

    def test_verify_missing_binary_marks_failed(self) -> None:
        from toolbelt.cli import _cmd_verify
        from toolbelt.manifest import load_manifest, save_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = load_manifest(root)
            manifest["tools"]["missing-tool"] = {
                "state": "installed",
                "verify": {"argv": ["definitely-not-a-toolbelt-binary"]},
            }
            save_manifest(root, manifest)

            args = type("Args", (), {"path": str(root), "tool": None, "json": False})()
            self.assertEqual(_cmd_verify(args), 1)
            rec = load_manifest(root)["tools"]["missing-tool"]
            self.assertEqual(rec["state"], "verify_failed")
            self.assertEqual(rec["verify"]["last_status"], "failed")


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


class RealApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_env = os.environ.copy()
        fake = ROOT / "tests" / "fake_bin"
        suffix = ".cmd" if os.name == "nt" else ""
        self.tmp = tempfile.mkdtemp()
        os.environ.update(
            {
                "TOOLBELT_CATALOG": str(FIXTURES / "e2e_catalog.toml"),
                "TOOLBELT_CLAUDE_BIN": str(fake / f"claude{suffix}"),
                "TOOLBELT_CODEX_BIN": str(fake / f"codex{suffix}"),
                "FAKE_BIN_LOG": str(Path(self.tmp) / "fake.log"),
                "TOOLBELT_CLAUDE_STATE": str(Path(self.tmp) / "claude_state.json"),
                "TOOLBELT_CODEX_CONFIG": str(Path(self.tmp) / "codex_config.toml"),
                "TOOLBELT_CLAUDE_PLUGINS": str(Path(self.tmp) / "installed_plugins.json"),
            }
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_apply_then_reconcile_and_remove(self) -> None:
        from toolbelt.apply import apply_plan, approve_interactively
        from toolbelt.catalog import load_catalog
        from toolbelt.evidence import scan
        from toolbelt.manifest import load_manifest
        from toolbelt.models import Action, Plan
        from toolbelt.plan import _reverse_steps, build_plan
        from toolbelt.recommend import recommend
        from toolbelt.reconcile import reconcile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            (root / "app.txt").write_text("hello\n", encoding="utf-8")
            catalog = load_catalog()

            recs = recommend(catalog, scan(root), mode="existing", root=root)
            plan = build_plan(recs, catalog, {"tools": {}}, mode="existing", project_root=root)
            plan = approve_interactively(plan, assume_yes=True, only=None)
            summary = apply_plan(plan, root, dry_run=False, catalog=catalog)

            self.assertEqual(summary["failed"], [])
            manifest = load_manifest(root)
            self.assertEqual(manifest["tools"]["e2e-mcp"]["state"], "installed")
            self.assertTrue((root / ".claude" / "skills" / "e2e" / "SKILL.md").exists())
            gitignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("toolbelt managed", gitignore)
            log = Path(os.environ["FAKE_BIN_LOG"]).read_text(encoding="utf-8")
            self.assertIn("mcp add", log)
            self.assertIn("plugin install", log)

            _plan, report = reconcile(root, catalog, manifest)
            self.assertEqual(report["classification"]["e2e-mcp"], "drifted_missing")

            record = manifest["tools"]["e2e-skill"]
            action = Action(
                id="a1",
                op="remove",
                tool_id="e2e-skill",
                kind=record["kind"],
                harnesses=tuple(record.get("harnesses", [])),
                purpose="Remove",
                provenance=record.get("provenance", ""),
                permissions=(),
                install_scope=record.get("install_scope", ""),
                secrets_required=(),
                evidence=(),
                steps=_reverse_steps(record),
                verify_argv=(),
                rollback="",
                approved=True,
            )
            rm = apply_plan(Plan(1, "", str(root), "existing", (action,)), root, dry_run=False)
            self.assertEqual(rm["failed"], [])
            self.assertEqual(load_manifest(root)["tools"]["e2e-skill"]["state"], "removed")
            self.assertFalse((root / ".claude" / "skills" / "e2e" / "SKILL.md").exists())


class ManifestDepthTests(unittest.TestCase):
    def test_nested_manifest_found_and_node_modules_skipped(self) -> None:
        from toolbelt.evidence import scan

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "packages" / "api").mkdir(parents=True)
            (root / "packages" / "api" / "package.json").write_text(
                '{"dependencies": {"pg": "^8"}}', encoding="utf-8"
            )
            (root / "node_modules" / "foo").mkdir(parents=True)
            (root / "node_modules" / "foo" / "package.json").write_text(
                '{"dependencies": {"leftpad": "1"}}', encoding="utf-8"
            )
            keys = {(e.type, e.key) for e in scan(root)}
            self.assertIn(("manifest_file", "package.json"), keys)
            self.assertIn(("manifest_dep", "package.json:pg"), keys)
            self.assertNotIn(("manifest_dep", "package.json:leftpad"), keys)


class ManagedBlockTests(unittest.TestCase):
    def test_conventions_tool_targets_both_harnesses(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.harness import concrete_steps

        tool = {t.id: t for t in load_catalog()}["skill-toolbelt-conventions"]
        steps = concrete_steps(tool, tool.install_scope)
        vias = {s.apply_via for s in steps}
        self.assertEqual(vias, {"scaffold", "managed_block"})
        block = next(s for s in steps if s.apply_via == "managed_block")
        self.assertEqual(block.block_path, "AGENTS.md")
        self.assertEqual(block.block_marker, "skill-toolbelt-conventions")

    def test_managed_block_is_idempotent_and_nondestructive(self) -> None:
        from toolbelt.harness import run_step
        from toolbelt.models import ApplyStep

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            agents = root / "AGENTS.md"
            agents.write_text("# House rules\n\nBe nice.\n", encoding="utf-8")
            log = root / "log.jsonl"
            add = ApplyStep(
                "managed_block",
                "codex",
                block_path="AGENTS.md",
                block_body="Managed line.",
                block_marker="skill-toolbelt-conventions",
            )
            self.assertEqual(run_step(add, cwd=root, dry_run=False, log=log, action_id="a1"), 0)
            text1 = agents.read_text(encoding="utf-8")
            self.assertIn("Be nice.", text1)
            self.assertIn("<!-- toolbelt:managed:skill-toolbelt-conventions -->", text1)
            self.assertIn("Managed line.", text1)

            run_step(add, cwd=root, dry_run=False, log=log, action_id="a1")
            self.assertEqual(agents.read_text(encoding="utf-8"), text1)
            self.assertEqual(text1.count("<!-- toolbelt:managed:skill-toolbelt-conventions -->"), 1)

            rm = ApplyStep(
                "managed_block_remove",
                "codex",
                block_path="AGENTS.md",
                block_marker="skill-toolbelt-conventions",
            )
            self.assertEqual(run_step(rm, cwd=root, dry_run=False, log=log, action_id="a1"), 0)
            text2 = agents.read_text(encoding="utf-8")
            self.assertIn("Be nice.", text2)
            self.assertNotIn("Managed line.", text2)
            self.assertNotIn("toolbelt:managed", text2)

    def test_managed_block_plan_roundtrips(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.evidence import scan
        from toolbelt.plan import build_plan, plan_from_json, plan_to_json
        from toolbelt.recommend import recommend

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            (root / "app.txt").write_text("hi\n", encoding="utf-8")
            catalog = load_catalog()
            recs = recommend(catalog, scan(root), mode="existing", root=root)
            plan = build_plan(recs, catalog, {"tools": {}}, mode="existing", project_root=root)
            self.assertEqual(plan_from_json(plan_to_json(plan)), plan)
            skill = next(a for a in plan.actions if a.tool_id == "skill-toolbelt-conventions")
            self.assertIn("codex", skill.harnesses)
            self.assertTrue(any(s.apply_via == "managed_block" for s in skill.steps))

    def test_catalog_rejects_invalid_managed_block_steps(self) -> None:
        from toolbelt.catalog import CatalogError, load_catalog

        base = (FIXTURES / "e2e_catalog.toml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.toml"
            missing.write_text(
                base
                + """

[[tool]]
id = "bad-managed-block"
kind = "skill"
name = "Bad"
summary = "Bad"
provenance = "test"
homepage = ""
approved = true
foundational = false
permissions = ["none"]
install_scope = "repo-committed"
secrets = []
artifacts = []
mcp_name = ""
verify_argv = []
catalog_version = "1"
  [[tool.match]]
  any_files = ["*"]
  [[tool.apply]]
  apply_via = "managed_block"
  harness = "codex"
  block_path = "AGENTS.md"
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CatalogError, "managed_block step needs block_path and block_body"):
                load_catalog(missing)

            reverse = Path(td) / "reverse.toml"
            reverse.write_text(
                base.replace('apply_via = "scaffold"', 'apply_via = "managed_block_remove"', 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CatalogError, "apply_via must be one of"):
                load_catalog(reverse)

    def test_remove_reverses_skill_file_and_agents_block(self) -> None:
        from toolbelt.apply import apply_plan, approve_interactively
        from toolbelt.catalog import load_catalog
        from toolbelt.evidence import scan
        from toolbelt.manifest import load_manifest
        from toolbelt.models import Action, Plan
        from toolbelt.plan import _reverse_steps, build_plan
        from toolbelt.recommend import recommend

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            (root / "app.txt").write_text("hi\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Existing\n\nKeep me.\n", encoding="utf-8")
            catalog = load_catalog()
            recs = recommend(catalog, scan(root), mode="existing", root=root)
            plan = build_plan(recs, catalog, {"tools": {}}, mode="existing", project_root=root)
            plan = Plan(
                plan.schema_version,
                plan.generated_at,
                plan.project_root,
                plan.mode,
                tuple(a for a in plan.actions if a.tool_id == "skill-toolbelt-conventions"),
            )
            plan = approve_interactively(plan, assume_yes=True, only=None)
            install = apply_plan(plan, root, dry_run=False, catalog=catalog)
            self.assertEqual(install["failed"], [])
            self.assertTrue((root / ".claude" / "skills" / "toolbelt-conventions" / "SKILL.md").exists())
            self.assertIn("toolbelt:managed:skill-toolbelt-conventions", (root / "AGENTS.md").read_text(encoding="utf-8"))

            manifest = load_manifest(root)
            record = manifest["tools"]["skill-toolbelt-conventions"]
            action = Action(
                id="a1",
                op="remove",
                tool_id="skill-toolbelt-conventions",
                kind=record["kind"],
                harnesses=tuple(record.get("harnesses", [])),
                purpose="Remove",
                provenance=record.get("provenance", ""),
                permissions=(),
                install_scope=record.get("install_scope", ""),
                secrets_required=(),
                evidence=(),
                steps=_reverse_steps(record),
                verify_argv=(),
                rollback="",
                approved=True,
            )
            remove = apply_plan(Plan(1, "", str(root), "existing", (action,)), root, dry_run=False)
            self.assertEqual(remove["failed"], [])
            self.assertFalse((root / ".claude" / "skills" / "toolbelt-conventions" / "SKILL.md").exists())
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Keep me.", agents)
            self.assertNotIn("toolbelt:managed:skill-toolbelt-conventions", agents)
            self.assertNotIn("AGENTS.md", (root / ".gitignore").read_text(encoding="utf-8"))


class DiscoveryTests(unittest.TestCase):
    def test_gaps_are_uncovered_actionable_signals(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.discover import gaps
        from toolbelt.evidence import scan

        catalog = load_catalog()
        with tempfile.TemporaryDirectory() as td:
            node = copy_fixture_repo("node_react", td)
            node_keys = {(g.signal.type, g.signal.key) for g in gaps(catalog, scan(node))}
            self.assertIn(("lang_ext", "typescript"), node_keys)
            self.assertNotIn(("manifest_dep", "package.json:@playwright/test"), node_keys)

            py = copy_fixture_repo("py_fastapi", td)
            py_keys = {(g.signal.type, g.signal.key) for g in gaps(catalog, scan(py))}
            self.assertNotIn(("lang_ext", "python"), py_keys)
            self.assertIn(("infra", "dockerfile"), py_keys)
            self.assertNotIn(("infra", "make"), py_keys)

            tf = copy_fixture_repo("terraform_infra", td)
            tf_keys = {(g.signal.type, g.signal.key) for g in gaps(catalog, scan(tf))}
            self.assertNotIn(("infra", "terraform"), tf_keys)

    def test_entry_template_carries_safety_rules(self) -> None:
        from toolbelt.discover import Gap, entry_template
        from toolbelt.models import Evidence

        tmpl = entry_template(Gap(Evidence("lang_ext", "rust", "42 files", 1, "src/main.rs"), "lsp"))
        self.assertIn("approved = false", tmpl)
        self.assertIn('langs = ["rust"]', tmpl)
        self.assertIn("catalog_version", tmpl)
        self.assertNotIn("NEVER put secret values", tmpl)

    def test_discover_command_is_read_only(self) -> None:
        from toolbelt.cli import _cmd_discover

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("py_fastapi", td)
            args = type("Args", (), {"path": str(root), "json": False})()
            with redirect_stdout(StringIO()) as buf:
                self.assertEqual(_cmd_discover(args), 0)
            self.assertFalse((root / ".toolbelt").exists())
            out = buf.getvalue()
            self.assertIn("Discovery for", out)
            self.assertIn("infra:dockerfile", out)
            self.assertNotIn("lang_ext:python", out)

    def test_discover_json_inventory_and_gap_shape(self) -> None:
        from toolbelt.cli import _cmd_discover

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("node_react", td)
            args = type("Args", (), {"path": str(root), "json": True})()
            with redirect_stdout(StringIO()) as buf:
                self.assertEqual(_cmd_discover(args), 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(set(payload), {"mode", "catalog_size", "gaps", "inventory", "brief"})
            self.assertIn("package.json:@playwright/test", payload["inventory"]["manifest_dep"])
            self.assertTrue(all(g["type"] in {"lang_ext", "infra"} for g in payload["gaps"]))
            self.assertIn(("lang_ext", "typescript"), {(g["type"], g["key"]) for g in payload["gaps"]})

    def test_safety_lint_flags_unsafe_proposal(self) -> None:
        from toolbelt.catalog import load_catalog, safety_lint

        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.toml"
            bad.write_text(
                '[[tool]]\n'
                'id = "mcp-bad"\nkind = "mcp_server"\nname = "Bad"\nsummary = "x"\n'
                'provenance = ""\nhomepage = ""\napproved = true\nfoundational = false\n'
                'permissions = []\ninstall_scope = "project"\nsecrets = []\nartifacts = []\n'
                'mcp_name = "bad"\nverify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  infra = ["redis"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "claude_mcp"\n  harness = "claude_code"\n'
                '  mcp_command = "npx"\n  mcp_args = ["-y", "server", "postgres://u:p@host/db"]\n',
                encoding="utf-8",
            )
            issues = safety_lint(load_catalog(bad))
            joined = " ".join(issues)
            self.assertIn("approved = false", joined)
            self.assertIn("provenance", joined)
            self.assertIn("homepage", joined)
            self.assertIn("permissions", joined)
            self.assertTrue(any("secret" in i for i in issues))

    def test_safety_lint_passes_clean_proposal(self) -> None:
        from toolbelt.catalog import load_catalog, safety_lint

        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.toml"
            good.write_text(
                '[[tool]]\n'
                'id = "lsp-example-new"\nkind = "lsp"\nname = "Example LSP"\nsummary = "x"\n'
                'provenance = "npm:example-lsp"\nhomepage = "https://example.com"\n'
                'approved = false\nfoundational = false\npermissions = ["process-spawn"]\n'
                'install_scope = "user"\nsecrets = []\nartifacts = []\nmcp_name = ""\n'
                'verify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  langs = ["rust"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "command"\n  harness = ""\n'
                '  command_argv = ["npm", "install", "-g", "example-lsp"]\n',
                encoding="utf-8",
            )
            live_ids = frozenset(t.id for t in load_catalog())
            self.assertEqual(safety_lint(load_catalog(good), existing_ids=live_ids), [])

    def test_safety_lint_flags_live_collisions(self) -> None:
        from toolbelt.catalog import load_catalog, safety_lint

        with tempfile.TemporaryDirectory() as td:
            proposal = Path(td) / "collision.toml"
            proposal.write_text(
                '[[tool]]\n'
                'id = "mcp-playwright"\nkind = "mcp_server"\nname = "Other Playwright"\nsummary = "x"\n'
                'provenance = "npm:other-playwright"\nhomepage = "https://example.com"\n'
                'approved = false\nfoundational = false\npermissions = ["process-spawn"]\n'
                'install_scope = "project"\nsecrets = []\nartifacts = []\n'
                'mcp_name = "playwright"\nverify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  infra = ["dockerfile"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "claude_mcp"\n  harness = "claude_code"\n'
                '  mcp_command = "npx"\n  mcp_args = ["-y", "other-playwright"]\n',
                encoding="utf-8",
            )
            live = load_catalog()
            existing_mcp = frozenset(
                (s.apply_via, t.mcp_name)
                for t in live
                for s in t.apply
                if s.apply_via in {"claude_mcp", "codex_mcp"} and t.mcp_name
            )
            issues = safety_lint(
                load_catalog(proposal),
                existing_ids=frozenset(t.id for t in live),
                existing_mcp=existing_mcp,
            )
            joined = " ".join(issues)
            self.assertIn("id already exists", joined)
            self.assertIn("already claimed", joined)

    def test_validate_command_targets_and_status_codes(self) -> None:
        from toolbelt.cli import _cmd_validate

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "catalog" / "proposed").mkdir(parents=True)
            args = type("Args", (), {"path": str(root), "target": None})()
            with redirect_stdout(StringIO()) as buf:
                self.assertEqual(_cmd_validate(args), 0)
            self.assertIn("no proposal files", buf.getvalue())

            bad = root / "bad.toml"
            bad.write_text(
                '[[tool]]\n'
                'id = "mcp-bad"\nkind = "mcp_server"\nname = "Bad"\nsummary = "x"\n'
                'provenance = ""\nhomepage = ""\napproved = true\nfoundational = false\n'
                'permissions = []\ninstall_scope = "project"\nsecrets = []\nartifacts = []\n'
                'mcp_name = "bad"\nverify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  infra = ["redis"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "claude_mcp"\n  harness = "claude_code"\n'
                '  mcp_command = "npx"\n  mcp_args = ["postgres://u:p@host/db"]\n',
                encoding="utf-8",
            )
            args = type("Args", (), {"path": str(root), "target": str(bad)})()
            with redirect_stdout(StringIO()) as buf:
                self.assertEqual(_cmd_validate(args), 2)
            out = buf.getvalue()
            self.assertIn("FAIL", out)
            self.assertIn("approved = false", out)
            self.assertIn("provenance", out)
            self.assertIn("homepage", out)
            self.assertIn("secret", out)

            good = root / "good.toml"
            good.write_text(
                '[[tool]]\n'
                'id = "lsp-example-new"\nkind = "lsp"\nname = "Example LSP"\nsummary = "x"\n'
                'provenance = "npm:example-lsp"\nhomepage = "https://example.com"\n'
                'approved = false\nfoundational = false\npermissions = ["process-spawn"]\n'
                'install_scope = "user"\nsecrets = []\nartifacts = []\nmcp_name = ""\n'
                'verify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  langs = ["rust"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "command"\n  harness = ""\n'
                '  command_argv = ["npm", "install", "-g", "example-lsp"]\n',
                encoding="utf-8",
            )
            args = type("Args", (), {"path": str(root), "target": str(good)})()
            with redirect_stdout(StringIO()) as buf:
                self.assertEqual(_cmd_validate(args), 0)
            self.assertIn("OK", buf.getvalue())


class PortabilityTests(unittest.TestCase):
    def test_save_manifest_works_without_fcntl(self) -> None:
        from toolbelt import manifest as m

        original = m.fcntl
        m.fcntl = None
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                data = m.load_manifest(root)
                data["tools"] = {"x": {"state": "installed"}}
                m.save_manifest(root, data)
                self.assertEqual(m.load_manifest(root)["tools"]["x"]["state"], "installed")
                self.assertFalse((root / ".toolbelt" / ".manifest.lock").exists())
        finally:
            m.fcntl = original

    def test_manifest_uses_lf_newlines(self) -> None:
        from toolbelt.manifest import load_manifest, save_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_manifest(root, load_manifest(root))
            raw = (root / ".toolbelt" / "manifest.json").read_bytes()
            self.assertNotIn(b"\r\n", raw)

    def test_evidence_sources_use_forward_slashes(self) -> None:
        from toolbelt.evidence import scan

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "packages" / "api").mkdir(parents=True)
            (root / "packages" / "api" / "package.json").write_text(
                '{"dependencies": {"pg": "^8"}}', encoding="utf-8"
            )
            for e in scan(root):
                self.assertNotIn("\\", e.source)
                self.assertNotIn("\\", e.detail)

    def test_github_actions_detected(self) -> None:
        from toolbelt.evidence import scan

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("terraform_infra", td)
            keys = {(e.type, e.key) for e in scan(root)}
            self.assertIn(("infra", "github_actions"), keys)


if __name__ == "__main__":
    unittest.main()
