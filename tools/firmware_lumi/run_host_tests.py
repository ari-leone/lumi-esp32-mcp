"""Run upstream host tests with Windows temporary-directory cleanup support.

Some upstream build tests leave their cwd inside TemporaryDirectory. Windows
cannot remove the process working directory. Restore cwd only at cleanup;
assertions and test behavior remain unchanged.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

source = Path(sys.argv[1]).resolve()
original_cleanup = tempfile.TemporaryDirectory.cleanup


def cleanup(self):
    if os.name == "nt" and Path.cwd().is_relative_to(Path(self.name).resolve()):
        os.chdir(source)
    return original_cleanup(self)


tempfile.TemporaryDirectory.cleanup = cleanup
suite = unittest.defaultTestLoader.discover(str(source / "scripts/tests"))
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(not result.wasSuccessful())
