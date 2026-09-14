"""Pytest bootstrap for the intent-engine suite.

Puts the service root on sys.path so `import app.*` resolves regardless of the
directory pytest was invoked from, and makes `tests/` importable for the shared
case data.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE_ROOT = os.path.dirname(_HERE)

for path in (_SERVICE_ROOT, _HERE):
    if path not in sys.path:
        sys.path.insert(0, path)
