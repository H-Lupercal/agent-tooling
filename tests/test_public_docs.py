from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
