"""Produce upstream test fixtures with this repository's real writer."""
import importlib
import sys
from pathlib import Path

from nup.pack import pack
from nup.edit import edit

if '--raw' in sys.argv:
    importlib.import_module('nup.pack').zstandard = None
pack(sys.argv[2], sys.argv[1])
if '--edited' in sys.argv:
    edit(sys.argv[2], publisher='Consumer compatibility publisher')
