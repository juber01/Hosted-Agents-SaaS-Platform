import pytest

from saas_platform.adapters.foundry import resolve_foundry_auth_policy
from saas_platform.config import Settings


def _base_settings(**overrides):
    base = Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="storage_queue",
        provisioning_worker_poll_seconds=1,
        provisioning_job_max_attempts=3,
        provisioning_retry_base_seconds=1,
        azure_storage_queue_connection_string="",
        azure_storage_queue_name="provisioning-jobs",
        azure_storage_queue_dead_letter_queue_name="provisioning-jobs-deadletter",
        azure_service_bus_connection_string="",
        azure_service_bus_queue_name="provisioning-jobs",
        azure_service_bus_dead_letter_queue_name="provisioning-jobs-deadletter",
        azure_ai_project_endpoint="",
        azure_ai_project_api_key="fallback-key",
        azure_use_managed_identity=True,
        azure_managed_identity_client_id="",
        allow_api_key_fallback=False,
        key_vault_url="",
        tenant_api_keys={},
        jwt_shared_secret="",
        jwt_algorithm="HS256",
        default_rate_limit_rpm=60,
    )
    return Settings(**{**base.__dict__, **overrides})


def test_prefers_managed_identity_when_enabled() -> None:
    policy = resolve_foundry_auth_policy(_base_settings())
    assert policy.mode == "managed_identity"


def test_uses_api_key_when_mi_disabled_and_allowed() -> None:
    policy = resolve_foundry_auth_policy(
        _base_settings(azure_use_managed_identity=False, allow_api_key_fallback=True)
    )
    assert policy.mode == "api_key"


def test_rejects_when_no_auth_mode_available() -> None:
    with pytest.raises(RuntimeError):
        resolve_foundry_auth_policy(
            _base_settings(
                azure_use_managed_identity=False,
                allow_api_key_fallback=False,
                azure_ai_project_api_key="",
            )
        )
