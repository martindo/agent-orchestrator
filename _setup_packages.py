"""
Set up sys.path for coderswarm-packages (src-layout packages).

Import this module to make all coderswarm-packages accessible.
Handles both flat packages (oracle, decision_os) and src-layout packages
(coderswarm-resilience, coderswarm-metrics, etc.).

Usage:
    import _setup_packages  # noqa: F401 - side-effect import
"""
import sys
from pathlib import Path

_PACKAGES_DIR = Path(__file__).resolve().parent.parent / "coderswarm-packages"


def _setup() -> None:
    """Add coderswarm-packages directories to sys.path."""
    if not _PACKAGES_DIR.is_dir():
        return

    # Add root for flat packages (oracle, decision_os, coderswarm_core, etc.)
    root = str(_PACKAGES_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)

    # Add src/ dirs for src-layout packages
    for pkg_dir in _PACKAGES_DIR.iterdir():
        if pkg_dir.is_dir():
            src_dir = pkg_dir / "src"
            if src_dir.is_dir():
                src_str = str(src_dir)
                if src_str not in sys.path:
                    sys.path.insert(0, src_str)


# Auto-setup on import
_setup()
