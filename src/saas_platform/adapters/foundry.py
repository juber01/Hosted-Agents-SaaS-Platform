from __future__ import annotations

from saas_platform.domain.interfaces import AgentGateway


class FoundryAgentGateway(AgentGateway):
    """Provider adapter seam.

    Real SDK calls are intentionally behind this adapter so API handlers stay provider-agnostic.
    """

    def execute(self, tenant_id: str, agent_id: str, message: str) -> str:
        return (
            f"[tenant={tenant_id}] [agent={agent_id}] "
            f"placeholder Foundry output for: {message[:120]}"
        )
