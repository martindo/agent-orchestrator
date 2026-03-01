"""CLI entry point: python -m agent_orchestrator."""

import sys
from pathlib import Path

# Add package root for _setup_packages
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import _setup_packages  # noqa: F401,E402 - side-effect import

from agent_orchestrator.cli.commands import main  # noqa: E402

if __name__ == "__main__":
    main()
