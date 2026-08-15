import sys
import tempfile
import unittest
from pathlib import Path

import run


class BootstrapTests(unittest.TestCase):
    def test_active_python_is_usable(self):
        self.assertTrue(run.python_is_usable(Path(sys.executable)))

    def test_missing_python_is_not_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(run.python_is_usable(Path(folder) / "missing-python"))


if __name__ == "__main__":
    unittest.main()

