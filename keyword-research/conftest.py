"""
conftest.py — Shared pytest configuration.

Mirrors gsc-monitor/conftest.py:

1. Puts the tool root on sys.path so `from core...` / `from fetchers...`
   imports work without per-test boilerplate.
2. ISOLATION: redirects RELATORIOS_DIR to a temp dir for the whole session so
   tests never touch the real `relatorios/` folder. core.cache and
   core.ledger derive their paths from core.storage at call time, so one
   variable covers everything.
"""

import os
import shutil
import sys
import tempfile

import pytest

# (1) tool root on the path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True, scope="session")
def _isolate_relatorios():
    """Point storage.RELATORIOS_DIR (and, via it, cache + ledger) at a tempdir."""
    import core.storage as storage

    original = storage.RELATORIOS_DIR
    tmp = tempfile.mkdtemp(prefix="kwr_test_relatorios_")
    storage.RELATORIOS_DIR = tmp
    try:
        yield tmp
    finally:
        storage.RELATORIOS_DIR = original
        shutil.rmtree(tmp, ignore_errors=True)
