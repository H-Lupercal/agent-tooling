import tempfile
import unittest
from pathlib import Path


class FileLockTests(unittest.TestCase):
    def test_lock_unlock_reacquire(self):
        from conductor.filelock import lock_exclusive, unlock

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".lock"
            with path.open("a", encoding="utf-8") as handle:
                lock_exclusive(handle)
                unlock(handle)
            with path.open("a", encoding="utf-8") as handle:
                lock_exclusive(handle)
                unlock(handle)


if __name__ == "__main__":
    unittest.main()
