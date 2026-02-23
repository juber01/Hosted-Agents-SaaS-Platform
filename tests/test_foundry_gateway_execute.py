from __future__ import annotations

from dataclasses import dataclass

import pytest

from saas_platform.adapters.foundry import FoundryAgentGateway
from saas_platform.config import Settings


def _base_settings(**overrides):
    base = Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="storage_queue",
        provisioning_worker_poll_seconds=1,
        provisioning_job_max_attempts=3,
        provisioning_retry_base_seconds=1,
        azure_storage_queue_account_url="",
        azure_storage_queue_connection_string="",
        azure_storage_queue_name="provisioning-jobs",
        azure_storage_queue_dead_letter_queue_name="provisioning-jobs-deadletter",
        azure_service_bus_fully_qualified_namespace="",
        azure_service_bus_connection_string="",
        azure_service_bus_queue_name="provisioning-jobs",
        azure_service_bus_dead_letter_queue_name="provisioning-jobs-deadletter",
        azure_ai_project_endpoint="",
        azure_ai_project_api_key="",
        azure_use_managed_identity=True,
        azure_managed_identity_client_id="",
        allow_api_key_fallback=False,
        key_vault_url="",
        tenant_api_keys={},
        rate_limit_backend="memory",
        rate_limit_redis_url="",
        rate_limit_redis_key_prefix="saas:ratelimit",
        rate_limit_redis_fail_open=True,
        jwt_jwks_url="",
        jwt_issuer="",
        jwt_audience="",
        jwt_jwks_cache_ttl_seconds=300,
        jwt_shared_secret="",
        jwt_algorithm="HS256",
        default_rate_limit_rpm=60,
    )
    return Settings(**{**base.__dict__, **overrides})


def test_execute_returns_placeholder_when_endpoint_not_configured() -> None:
    gateway = FoundryAgentGateway(_base_settings())
    output = gateway.execute(tenant_id="tenant-1", agent_id="agent-1", message="hello")
    assert "foundry endpoint not configured" in output
    assert "hello" in output


def test_execute_rejects_api_key_mode_for_hosted_agents() -> None:
    gateway = FoundryAgentGateway(
        _base_settings(
            azure_ai_project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
            azure_use_managed_identity=False,
            allow_api_key_fallback=True,
            azure_ai_project_api_key="dev-key",
        )
    )
    with pytest.raises(RuntimeError, match="managed identity"):
        gateway.execute(tenant_id="tenant-1", agent_id="agent-1", message="hello")


@dataclass
class _FakeTextDetails:
    value: str


@dataclass
class _FakeMessageText:
    text: _FakeTextDetails


@dataclass
class _FakeThread:
    id: str


@dataclass
class _FakeRun:
    status: str
    last_error: str | None = None


class _FakeThreads:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def create(self, **kwargs) -> _FakeThread:
        return _FakeThread(id="thread-123")

    def delete(self, *, thread_id: str, **kwargs) -> None:
        self.deleted.append(thread_id)


class _FakeMessages:
    def create(self, thread_id: str, **kwargs) -> None:
        return None

    def get_last_message_text_by_role(self, thread_id: str, role, **kwargs) -> _FakeMessageText:
        return _FakeMessageText(text=_FakeTextDetails(value="agent response"))


class _FakeRuns:
    def create_and_process(self, thread_id: str, agent_id: str, **kwargs) -> _FakeRun:
        return _FakeRun(status="completed")


class _FakeAgents:
    def __init__(self) -> None:
        self.threads = _FakeThreads()
        self.messages = _FakeMessages()
        self.runs = _FakeRuns()


class _FakeProjectClient:
    def __init__(self) -> None:
        self.agents = _FakeAgents()


def test_execute_uses_agents_client_and_returns_text() -> None:
    gateway = FoundryAgentGateway(
        _base_settings(azure_ai_project_endpoint="https://example.services.ai.azure.com/api/projects/demo"),
        project_client_factory=lambda settings: _FakeProjectClient(),
    )

    output = gateway.execute(tenant_id="tenant-1", agent_id="agent-1", message="hello")

    assert output == "agent response"
