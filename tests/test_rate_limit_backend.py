from __future__ import annotations

import pytest

from saas_platform.api.main import create_app
from saas_platform.config import Settings
from saas_platform.policies.rate_limit import RedisFixedWindowRateLimiter


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
        default_rate_limit_rpm=2,
    )
    return Settings(**{**base.__dict__, **overrides})


class _FakeRedis:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._ttl: dict[str, int] = {}

    def incr(self, key: str) -> int:
        value = self._counts.get(key, 0) + 1
        self._counts[key] = value
        return value

    def expire(self, key: str, ttl_seconds: int) -> bool:
        self._ttl[key] = ttl_seconds
        return True


class _FailingRedis:
    def incr(self, _key: str) -> int:
        raise RuntimeError("redis down")

    def expire(self, _key: str, _ttl_seconds: int) -> bool:
        return True


def test_redis_rate_limiter_enforces_limit() -> None:
    limiter = RedisFixedWindowRateLimiter(
        requests_per_minute=2,
        redis_url="redis://example",
        redis_client=_FakeRedis(),
    )
    assert limiter.allow("tenant:agent")
    assert limiter.allow("tenant:agent")
    assert not limiter.allow("tenant:agent")


def test_redis_rate_limiter_fail_open() -> None:
    limiter = RedisFixedWindowRateLimiter(
        requests_per_minute=2,
        redis_url="redis://example",
        fail_open=True,
        redis_client=_FailingRedis(),
    )
    assert limiter.allow("tenant:agent")


def test_redis_rate_limiter_fail_closed() -> None:
    limiter = RedisFixedWindowRateLimiter(
        requests_per_minute=2,
        redis_url="redis://example",
        fail_open=False,
        redis_client=_FailingRedis(),
    )
    with pytest.raises(RuntimeError):
        limiter.allow("tenant:agent")


def test_app_uses_redis_rate_limiter_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import saas_platform.api.main as main_mod

    class _NoopRedisLimiter:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def allow(self, _key: str) -> bool:
            return True

    monkeypatch.setattr(main_mod, "RedisFixedWindowRateLimiter", _NoopRedisLimiter)
    app = create_app(
        _settings(
            rate_limit_backend="redis",
            rate_limit_redis_url="redis://localhost:6379/0",
        )
    )
    assert isinstance(app.state.ctx.limiter, _NoopRedisLimiter)


def test_app_raises_on_unknown_rate_limit_backend() -> None:
    with pytest.raises(RuntimeError):
        create_app(_settings(rate_limit_backend="unknown_backend"))
