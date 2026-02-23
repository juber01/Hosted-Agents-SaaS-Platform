from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable, Protocol

from saas_platform.config import Settings
from saas_platform.domain.interfaces import AgentGateway

_logger = logging.getLogger(__name__)


class _AgentsClientLike(Protocol):
    threads: object
    messages: object
    runs: object


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

    def __init__(
        self,
        settings: Settings,
        project_client_factory: Callable[[Settings], object] | None = None,
    ) -> None:
        self._settings = settings
        self._auth_policy = resolve_foundry_auth_policy(settings)
        self._project_client_factory = project_client_factory or _default_project_client_factory
        self._project_client: object | None = None

    @property
    def auth_mode(self) -> str:
        return self._auth_policy.mode

    def execute(self, tenant_id: str, agent_id: str, message: str) -> str:
        endpoint = self._settings.azure_ai_project_endpoint.strip()
        if not endpoint:
            # Keep local/dev execution usable without Foundry provisioning.
            return (
                f"[tenant={tenant_id}] [agent={agent_id}] [auth={self._auth_policy.mode}] "
                f"foundry endpoint not configured; local placeholder output for: {message[:120]}"
            )

        if self._auth_policy.mode != "managed_identity":
            raise RuntimeError(
                "Hosted-agent execution requires managed identity authentication. "
                "Set AZURE_USE_MANAGED_IDENTITY=true for Foundry execution."
            )

        from azure.ai.agents.models import MessageRole, RunStatus

        agents = self._agents_client()
        thread_id = ""
        try:
            thread = agents.threads.create(
                metadata={
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                }
            )
            thread_id = str(getattr(thread, "id", "") or "")
            if not thread_id:
                raise RuntimeError("Foundry did not return a thread id")

            agents.messages.create(
                thread_id=thread_id,
                role=MessageRole.USER,
                content=message,
                metadata={"tenant_id": tenant_id, "agent_id": agent_id},
            )

            run = agents.runs.create_and_process(
                thread_id=thread_id,
                agent_id=agent_id,
                polling_interval=max(self._settings.foundry_run_poll_interval_seconds, 1),
                metadata={"tenant_id": tenant_id, "agent_id": agent_id},
            )

            run_status = getattr(run, "status", "")
            status = str(getattr(run_status, "value", run_status) or "").lower()
            if status != RunStatus.COMPLETED.value:
                run_error = getattr(run, "last_error", None)
                raise RuntimeError(f"Foundry run failed with status={status}, error={run_error}")

            message_text = agents.messages.get_last_message_text_by_role(
                thread_id=thread_id,
                role=MessageRole.AGENT,
            )
            if message_text is None:
                raise RuntimeError("Foundry run completed but returned no agent message")

            text_details = getattr(message_text, "text", None)
            text_value = str(getattr(text_details, "value", "") or "").strip()
            if not text_value:
                raise RuntimeError("Foundry run completed but returned empty agent text")
            return text_value
        except Exception:
            _logger.exception("foundry_execute_failed tenant=%s agent=%s", tenant_id, agent_id)
            raise
        finally:
            if thread_id:
                try:
                    agents.threads.delete(thread_id=thread_id)
                except Exception:
                    _logger.warning("foundry_thread_delete_failed thread_id=%s", thread_id)

    def _agents_client(self) -> _AgentsClientLike:
        if self._project_client is None:
            self._project_client = self._project_client_factory(self._settings)
        agents = getattr(self._project_client, "agents", None)
        if agents is None:
            raise RuntimeError("Foundry project client did not expose an agents client")
        return agents


def _default_project_client_factory(settings: Settings) -> object:
    endpoint = settings.azure_ai_project_endpoint.strip()
    if not endpoint:
        raise RuntimeError("AZURE_AI_PROJECT_ENDPOINT is required for Foundry execution")

    if not settings.azure_use_managed_identity:
        raise RuntimeError("Foundry project client requires managed identity mode")

    try:
        from azure.ai.projects import AIProjectClient
    except ModuleNotFoundError as err:
        raise RuntimeError("Foundry execution requires 'azure-ai-projects'.") from err

    try:
        from azure.identity import DefaultAzureCredential
    except ModuleNotFoundError as err:
        raise RuntimeError("Foundry managed identity execution requires 'azure-identity'.") from err

    client_id = settings.azure_managed_identity_client_id.strip() or None
    credential = DefaultAzureCredential(managed_identity_client_id=client_id)
    return AIProjectClient(endpoint=endpoint, credential=credential)
