"""Run BananaNative's unmodified loader/tool tests with our producer substituted."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

root, producer, workspace, mode = map(Path, sys.argv[1:5])
sys.path.insert(0, str(root / 'dm/tools/tests'))
import test_nup

def write_nup(src, out, *args):
    command = [sys.executable, str(producer), str(src), str(out), *args]
    if str(mode) == 'edited':
        command.append('--edited')
    result = subprocess.run(command, env={**os.environ, 'PYTHONPATH': str(workspace)}, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return out

test_nup.write_nup = write_nup
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(getattr(test_nup, name))
                              for name in ('Read', 'RawOnly', 'Tools', 'Descriptor'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.skipped:
    raise SystemExit(1)
