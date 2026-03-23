"""Bidirectional conversion between Studio IR and runtime ProfileConfig."""

from studio.conversion.converter import (
    ir_to_profile,
    profile_to_ir,
)

__all__ = ["ir_to_profile", "profile_to_ir"]
