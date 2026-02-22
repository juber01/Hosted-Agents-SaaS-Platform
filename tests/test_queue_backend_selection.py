from __future__ import annotations

import pytest

from saas_platform.api.main import create_app
from saas_platform.config import Settings
from saas_platform.domain.interfaces import ProvisioningQueue
from saas_platform.domain.models import ProvisioningJob


def _settings(**overrides) -> Settings:
    base = Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="database",
        provisioning_worker_poll_seconds=1,
        provisioning_job_max_attempts=3,
        provisioning_retry_base_seconds=0,
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
        jwt_jwks_url="",
        jwt_issuer="",
        jwt_audience="",
        jwt_jwks_cache_ttl_seconds=300,
        jwt_shared_secret="",
        jwt_algorithm="HS256",
        default_rate_limit_rpm=60,
    )
    return Settings(**{**base.__dict__, **overrides})


class _NoopWrapper(ProvisioningQueue):
    def __init__(self, *, delegate: ProvisioningQueue, **_kwargs) -> None:
        self.delegate = delegate

    def enqueue(self, job: ProvisioningJob) -> None:
        self.delegate.enqueue(job)

    def claim_next(self) -> ProvisioningJob | None:
        return self.delegate.claim_next()

    def mark_done(self, job_id: str) -> None:
        self.delegate.mark_done(job_id)

    def mark_retry(self, job_id: str, error: str, retry_in_seconds: int) -> None:
        self.delegate.mark_retry(job_id, error, retry_in_seconds)

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        self.delegate.mark_dead_letter(job_id, error)

    def get_job(self, job_id: str) -> ProvisioningJob | None:
        return self.delegate.get_job(job_id)


def test_unsupported_queue_backend_raises() -> None:
    with pytest.raises(RuntimeError):
        create_app(_settings(provisioning_queue_backend="unsupported_backend"))


def test_storage_queue_backend_falls_back_without_connection_string() -> None:
    app = create_app(_settings(provisioning_queue_backend="storage_queue"))
    assert app.state.ctx.queue.__class__.__name__ == "InMemoryProvisioningQueue"


def test_service_bus_backend_falls_back_without_connection_string() -> None:
    app = create_app(_settings(provisioning_queue_backend="service_bus"))
    assert app.state.ctx.queue.__class__.__name__ == "InMemoryProvisioningQueue"


def test_storage_queue_backend_wraps_with_managed_identity_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import saas_platform.adapters.queue as queue_mod
    import saas_platform.api.main as main_mod

    monkeypatch.setattr(queue_mod, "StorageQueueProvisioningQueue", _NoopWrapper)
    monkeypatch.setattr(main_mod, "_managed_identity_credential", lambda _settings: object())
    app = create_app(
        _settings(
            provisioning_queue_backend="storage_queue",
            azure_storage_queue_account_url="https://example.queue.core.windows.net",
            azure_use_managed_identity=True,
        )
    )
    assert isinstance(app.state.ctx.queue, _NoopWrapper)


def test_service_bus_backend_wraps_with_managed_identity_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import saas_platform.adapters.queue as queue_mod
    import saas_platform.api.main as main_mod

    monkeypatch.setattr(queue_mod, "ServiceBusProvisioningQueue", _NoopWrapper)
    monkeypatch.setattr(main_mod, "_managed_identity_credential", lambda _settings: object())
    app = create_app(
        _settings(
            provisioning_queue_backend="service_bus",
            azure_service_bus_fully_qualified_namespace="example.servicebus.windows.net",
            azure_use_managed_identity=True,
        )
    )
    assert isinstance(app.state.ctx.queue, _NoopWrapper)


def test_storage_queue_connection_string_requires_explicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import saas_platform.adapters.queue as queue_mod

    monkeypatch.setattr(queue_mod, "StorageQueueProvisioningQueue", _NoopWrapper)

    with pytest.raises(RuntimeError):
        create_app(
            _settings(
                provisioning_queue_backend="storage_queue",
                azure_use_managed_identity=False,
                allow_api_key_fallback=False,
                azure_storage_queue_connection_string="UseDevelopmentStorage=true;",
            )
        )

    app = create_app(
        _settings(
            provisioning_queue_backend="storage_queue",
            azure_use_managed_identity=False,
            allow_api_key_fallback=True,
            azure_ai_project_api_key="fallback-key",
            azure_storage_queue_connection_string="UseDevelopmentStorage=true;",
        )
    )
    assert isinstance(app.state.ctx.queue, _NoopWrapper)


def test_service_bus_connection_string_requires_explicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import saas_platform.adapters.queue as queue_mod

    monkeypatch.setattr(queue_mod, "ServiceBusProvisioningQueue", _NoopWrapper)

    with pytest.raises(RuntimeError):
        create_app(
            _settings(
                provisioning_queue_backend="service_bus",
                azure_use_managed_identity=False,
                allow_api_key_fallback=False,
                azure_service_bus_connection_string=(
                    "Endpoint=sb://local/;SharedAccessKeyName=test;SharedAccessKey=x"
                ),
            )
        )

    app = create_app(
        _settings(
            provisioning_queue_backend="service_bus",
            azure_use_managed_identity=False,
            allow_api_key_fallback=True,
            azure_ai_project_api_key="fallback-key",
            azure_service_bus_connection_string="Endpoint=sb://local/;SharedAccessKeyName=test;SharedAccessKey=x",
        )
    )
    assert isinstance(app.state.ctx.queue, _NoopWrapper)
