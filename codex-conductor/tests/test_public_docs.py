import tomllib
import unittest
from importlib.resources import files
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "src/conductor/assets/policy/orchestration-policy.md",
    PROJECT_ROOT / "src/conductor/assets/policy/orchestration-policy.claude.md",
    PROJECT_ROOT / "docs/probe-report.md",
)


class PublicDocsTests(unittest.TestCase):
    def test_public_docs_do_not_reference_local_checkout(self):
        forbidden = (
            str(Path.home()),
            str(PROJECT_ROOT),
        )
        for path in PUBLIC_DOCS:
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                with self.subTest(path=str(path), value=value):
                    self.assertNotIn(value, text)

    def test_packaged_codex_ladder_uses_explicit_gpt_56_authority(self):
        from conductor.schemas import TASK_CLASSES, ConductorConfig

        raw = (
            files("conductor.assets")
            .joinpath("config", "conductor.toml")
            .read_text(encoding="utf-8")
        )
        config = ConductorConfig.model_validate(tomllib.loads(raw))

        self.assertEqual(
            [tier.model for tier in config.tiers],
            [
                "gpt-5.6-sol",
                "gpt-5.5",
                "gpt-5.6-terra",
                "gpt-5.4",
                "gpt-5.6-luna",
                "gpt-5.4-mini",
                "gpt-5.3-codex-spark",
            ],
        )
        self.assertEqual(config.tiers[0].generation_rank, 56)
        self.assertEqual(config.tiers[1].generation_rank, 55)
        self.assertEqual(
            config.tiers[0].relative_cost_weight,
            config.tiers[1].relative_cost_weight,
        )
        owners = [task for tier in config.tiers for task in tier.task_classes]
        self.assertEqual(set(owners), set(TASK_CLASSES))
        self.assertEqual(len(owners), len(TASK_CLASSES))

    def test_public_policy_says_codex_chooses_and_conductor_only_validates(self):
        policy = (
            PROJECT_ROOT / "src/conductor/assets/policy/orchestration-policy.md"
        ).read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("You choose the worker model and reasoning effort", policy)
        self.assertIn("never rewrites", policy)
        self.assertIn("GPT-5.5 caller cannot spawn a GPT-5.6 worker", policy)
        self.assertIn("GPT-5.6 Sol", readme)
        self.assertIn("same ChatGPT credit rates as GPT-5.5", readme)


if __name__ == "__main__":
    unittest.main()
