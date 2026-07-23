"""The engine wires a contract validator into the connector service (audit 4.6).

Previously ConnectorService was built with no validator, so
_validate_input/output_contract always early-returned and the contracts
framework never ran on the execute path.
"""

from __future__ import annotations

import pytest

from agent_orchestrator.contracts import ContractValidator
from agent_orchestrator.core.engine import OrchestrationEngine

from .test_core import _make_test_config_manager


@pytest.mark.asyncio
async def test_engine_injects_contract_validator(tmp_path):
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        service = engine._connector_service
        assert isinstance(service._contract_validator, ContractValidator)
        # A registry is exposed so callers can register contracts...
        assert engine.contract_registry is not None
        # ...and the injected validator validates against that same registry,
        # so anything registered on the engine is enforced on the execute path.
        assert service._contract_validator._registry is engine.contract_registry
    finally:
        await engine.stop()
