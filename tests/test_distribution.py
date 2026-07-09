import importlib.metadata
import unittest

import toolbelt


class DistributionTests(unittest.TestCase):
    def test_public_metadata_and_console_entrypoint(self):
        self.assertEqual(
            toolbelt.__version__,
            importlib.metadata.version("toolbelt-ai"),
        )
        self.assertTrue(callable(toolbelt.main))


if __name__ == "__main__":
    unittest.main()
