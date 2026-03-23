"""Extension stub generation for connector providers, event handlers, and hooks."""

from studio.extensions.generator import (
    generate_connector_stub,
    generate_event_handler_stub,
    generate_hook_stub,
    generate_all_stubs,
    ExtensionStubResult,
)

__all__ = [
    "generate_connector_stub",
    "generate_event_handler_stub",
    "generate_hook_stub",
    "generate_all_stubs",
    "ExtensionStubResult",
]
