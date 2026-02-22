from __future__ import annotations

from dataclasses import dataclass

from saas_platform.config import Settings
from saas_platform.domain.interfaces import AgentGateway


@dataclass(frozen=True)
class FoundryAuthPolicy:
    mode: str
    managed_identity_client_id: str | None = None


def resolve_foundry_auth_policy(settings: Settings) -> FoundryAuthPolicy:
    env = (settings.app_env or "").strip().lower()

    if env in {"prod", "production"} and not settings.azure_use_managed_identity:
        raise RuntimeError("Production policy requires managed identity for Foundry access")

    if settings.azure_use_managed_identity:
        client_id = settings.azure_managed_identity_client_id.strip() or None
        return FoundryAuthPolicy(mode="managed_identity", managed_identity_client_id=client_id)

    if settings.allow_api_key_fallback and settings.azure_ai_project_api_key:
        return FoundryAuthPolicy(mode="api_key")

    raise RuntimeError(
        "No Foundry auth mode available. Enable managed identity or explicitly allow API key fallback."
    )


class FoundryAgentGateway(AgentGateway):
    """Provider adapter seam with MI-first auth policy."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth_policy = resolve_foundry_auth_policy(settings)

    @property
    def auth_mode(self) -> str:
        return self._auth_policy.mode

    def execute(self, tenant_id: str, agent_id: str, message: str) -> str:
        # Real SDK calls will use managed identity credentials by default.
        return (
            f"[tenant={tenant_id}] [agent={agent_id}] [auth={self._auth_policy.mode}] "
            f"placeholder Foundry output for: {message[:120]}"
        )
