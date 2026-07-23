"""The `python -m agent_orchestrator` entry point imports cleanly (audit 5.3).

Removed the leftover `_setup_packages` side-effect import (which injected a
sibling `../coderswarm-packages` onto sys.path) — this guards against it (or a
similar dangling import) creeping back.
"""

from __future__ import annotations

import importlib


def test_main_entrypoint_imports():
    mod = importlib.import_module("agent_orchestrator.__main__")
    assert callable(mod.main)
