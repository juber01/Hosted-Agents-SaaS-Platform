from __future__ import annotations

import json

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
import jwt
import pytest

from saas_platform.config import Settings
from saas_platform.policies.auth import AdminAuthService, TenantAuthService


def _settings(**overrides) -> Settings:
    base = Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="database",
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
        jwt_jwks_url="https://example/.well-known/jwks.json",
        jwt_issuer="https://login.microsoftonline.com/test-tenant/v2.0",
        jwt_audience="api://hosted-agents-saas-platform",
        jwt_jwks_cache_ttl_seconds=300,
        jwt_shared_secret="",
        jwt_algorithm="RS256",
        default_rate_limit_rpm=60,
    )
    return Settings(**{**base.__dict__, **overrides})


def _install_mock_jwks(monkeypatch: pytest.MonkeyPatch, jwks_payload: dict) -> None:
    import saas_platform.policies.auth as auth_mod

    class _MockResponse:
        def __init__(self, payload: dict) -> None:
            self._raw = json.dumps(payload).encode("utf-8")

        def read(self) -> bytes:
            return self._raw

        def __enter__(self) -> "_MockResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    auth_mod._JWKS_CACHE.clear()
    monkeypatch.setattr(auth_mod.request, "urlopen", lambda _url, timeout=5: _MockResponse(jwks_payload))


def _build_rsa_token(claims: dict[str, object], *, kid: str = "kid-1") -> tuple[str, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})
    return token, {"keys": [jwk]}


def test_admin_auth_accepts_valid_jwks_token(monkeypatch: pytest.MonkeyPatch) -> None:
    claims = {
        "sub": "admin-user",
        "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
        "aud": "api://hosted-agents-saas-platform",
        "roles": ["platform_admin"],
    }
    token, jwks = _build_rsa_token(claims)
    _install_mock_jwks(monkeypatch, jwks)

    principal = AdminAuthService(_settings()).authenticate(f"Bearer {token}")
    assert principal.subject == "admin-user"
    assert "platform_admin" in principal.roles


def test_tenant_auth_accepts_valid_jwks_token(monkeypatch: pytest.MonkeyPatch) -> None:
    claims = {
        "sub": "tenant-user",
        "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
        "aud": "api://hosted-agents-saas-platform",
        "tenant_id": "tenant-123",
    }
    token, jwks = _build_rsa_token(claims, kid="kid-tenant")
    _install_mock_jwks(monkeypatch, jwks)

    tenant_ctx = TenantAuthService(_settings()).authenticate(
        path_tenant_id="tenant-123",
        x_tenant_id="tenant-123",
        x_customer_id="user-1",
        x_api_key="",
        authorization=f"Bearer {token}",
    )
    assert tenant_ctx.tenant_id == "tenant-123"


def test_jwks_auth_rejects_invalid_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    claims = {
        "sub": "admin-user",
        "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
        "aud": "api://wrong-audience",
        "roles": ["platform_admin"],
    }
    token, jwks = _build_rsa_token(claims, kid="kid-bad-aud")
    _install_mock_jwks(monkeypatch, jwks)

    with pytest.raises(HTTPException) as err:
        AdminAuthService(_settings()).authenticate(f"Bearer {token}")
    assert err.value.status_code == 401


def test_jwks_auth_requires_complete_config() -> None:
    settings = _settings(jwt_issuer="", jwt_shared_secret="")
    with pytest.raises(HTTPException) as err:
        AdminAuthService(settings).authenticate("Bearer dummy-token")
    assert err.value.status_code == 500
