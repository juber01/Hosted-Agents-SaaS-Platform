from fastapi.testclient import TestClient
from contextlib import contextmanager
import jwt

from saas_platform.api.main import create_app
from saas_platform.config import Settings
from saas_platform.domain.models import CustomerAgentEntitlement, Tenant, TenantAgent


def _settings(**overrides) -> Settings:
    base = Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="storage_queue",
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
        tenant_api_keys={"tenant-dev": "dev-key-123"},
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


def _admin_headers(
    *,
    secret: str,
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
    tenant_ids: list[str] | None = None,
) -> dict[str, str]:
    claims: dict[str, object] = {"sub": "admin-user"}
    if roles:
        claims["roles"] = roles
    if scopes:
        claims["scp"] = " ".join(scopes)
    if tenant_ids:
        claims["tenant_ids"] = tenant_ids

    token = jwt.encode(claims, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _grant_agent_access(
    app,
    *,
    tenant_id: str,
    customer_user_id: str,
    agent_id: str,
    display_name: str | None = None,
) -> None:
    app.state.ctx.agent_access.upsert_tenant_agent(
        TenantAgent(
            tenant_id=tenant_id,
            agent_id=agent_id,
            display_name=display_name or agent_id,
            active=True,
        )
    )
    app.state.ctx.agent_access.grant_customer_agent(
        CustomerAgentEntitlement(
            tenant_id=tenant_id,
            customer_user_id=customer_user_id,
            agent_id=agent_id,
        )
    )


def test_tenant_provisioning_and_run_flow() -> None:
    app = create_app(_settings())
    client = TestClient(app)

    create = client.post("/v1/tenants", json={"name": "Acme", "plan": "starter"})
    assert create.status_code == 201
    body = create.json()
    tenant_id = body["tenant_id"]

    tenant_before = client.get(f"/v1/tenants/{tenant_id}")
    assert tenant_before.status_code == 200
    assert tenant_before.json()["status"] == "pending"

    process = client.post("/v1/provisioning/jobs/run-next")
    assert process.status_code == 200
    assert process.json()["processed"] is True

    tenant_after = client.get(f"/v1/tenants/{tenant_id}")
    assert tenant_after.status_code == 200
    assert tenant_after.json()["status"] == "active"

    run = client.post(
        f"/v1/tenants/{tenant_id}/runs",
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Customer-User-Id": "user-1",
            "X-Api-Key": "",
        },
        json={"agent_id": "support", "user_id": "user-1", "message": "hello"},
    )
    assert run.status_code == 401


def test_api_key_auth_and_rate_limit() -> None:
    settings = _settings(allow_api_key_fallback=True)

    app = create_app(settings)
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-dev", name="Acme", plan="starter", status="active")
    )
    _grant_agent_access(app, tenant_id="tenant-dev", customer_user_id="user-1", agent_id="support", display_name="Support")

    client = TestClient(app)

    headers = {
        "X-Tenant-Id": "tenant-dev",
        "X-Customer-User-Id": "user-1",
        "X-Api-Key": "dev-key-123",
    }

    first = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers=headers,
        json={"agent_id": "support", "user_id": "user-1", "message": "first"},
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers=headers,
        json={"agent_id": "support", "user_id": "user-1", "message": "second"},
    )
    assert second.status_code == 200

    third = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers=headers,
        json={"agent_id": "support", "user_id": "user-1", "message": "third"},
    )
    assert third.status_code == 429


def test_identity_debug_endpoint_prefers_managed_identity() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(_settings(jwt_shared_secret=secret))
    client = TestClient(app)

    response = client.get(
        "/v1/admin/debug/identity",
        headers=_admin_headers(secret=secret, roles=["platform_admin"]),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["foundry_auth_mode"] == "managed_identity"
    assert payload["azure_use_managed_identity"] is True


def test_plan_admin_and_tenant_quota_enforcement() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(
        _settings(
            allow_api_key_fallback=True,
            default_rate_limit_rpm=20,
            tenant_api_keys={},
            jwt_shared_secret=secret,
        )
    )
    client = TestClient(app)
    admin_headers = _admin_headers(secret=secret, roles=["platform_admin"])

    plan = client.post(
        "/v1/admin/plans",
        json={
            "plan_id": "tiny",
            "display_name": "Tiny",
            "monthly_messages": 1,
            "monthly_token_cap": 200,
            "max_agents": 1,
            "active": True,
        },
        headers=admin_headers,
    )
    assert plan.status_code == 201
    assert plan.json()["plan_id"] == "tiny"

    create_tenant = client.post("/v1/tenants", json={"name": "Tiny Co", "plan": "tiny"})
    assert create_tenant.status_code == 201
    tenant_id = create_tenant.json()["tenant_id"]

    process = client.post("/v1/provisioning/jobs/run-next")
    assert process.status_code == 200
    assert process.json()["processed"] is True

    _grant_agent_access(app, tenant_id=tenant_id, customer_user_id="user-1", agent_id="assistant", display_name="Assistant")

    headers = {
        "X-Tenant-Id": tenant_id,
        "X-Customer-User-Id": "user-1",
        "X-Api-Key": "",
        "Authorization": f"Bearer {jwt.encode({'tenant_id': tenant_id}, secret, algorithm='HS256')}",
    }

    first = client.post(
        f"/v1/tenants/{tenant_id}/runs",
        headers=headers,
        json={"agent_id": "assistant", "user_id": "user-1", "message": "hello"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/v1/tenants/{tenant_id}/runs",
        headers=headers,
        json={"agent_id": "assistant", "user_id": "user-1", "message": "again"},
    )
    assert second.status_code == 429
    assert second.json()["detail"] == "tenant monthly quota exceeded"


def test_usage_export_and_tenant_usage_summary() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(
        _settings(
            allow_api_key_fallback=True,
            default_rate_limit_rpm=20,
            jwt_shared_secret=secret,
        )
    )
    client = TestClient(app)
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-dev", name="Acme", plan="starter", status="active")
    )
    _grant_agent_access(app, tenant_id="tenant-dev", customer_user_id="user-1", agent_id="support", display_name="Support")

    run = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers={
            "X-Tenant-Id": "tenant-dev",
            "X-Customer-User-Id": "user-1",
            "X-Api-Key": "dev-key-123",
        },
        json={"agent_id": "support", "user_id": "user-1", "message": "meter this"},
    )
    assert run.status_code == 200

    usage = client.get(
        "/v1/admin/tenants/tenant-dev/usage",
        headers=_admin_headers(secret=secret, roles=["tenant_admin"], tenant_ids=["tenant-dev"]),
    )
    assert usage.status_code == 200
    usage_payload = usage.json()
    assert usage_payload["tenant_id"] == "tenant-dev"
    assert usage_payload["messages_used"] == 1
    assert usage_payload["tokens_used"] > 0

    export = client.get(
        "/v1/admin/usage/export",
        headers=_admin_headers(secret=secret, roles=["billing_reader"]),
    )
    assert export.status_code == 200
    rows = export.json()
    tenant_rows = [row for row in rows if row["tenant_id"] == "tenant-dev"]
    assert len(tenant_rows) == 1
    assert tenant_rows[0]["messages_used"] == 1


def test_admin_requires_bearer_jwt() -> None:
    app = create_app(_settings(jwt_shared_secret="admin-secret-1234567890-1234567890"))
    client = TestClient(app)

    response = client.get("/v1/admin/plans")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_admin_rbac_forbidden_without_required_role_or_scope() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(_settings(jwt_shared_secret=secret))
    client = TestClient(app)

    response = client.get(
        "/v1/admin/plans",
        headers=_admin_headers(secret=secret, roles=["viewer"], scopes=["tenant.usage.read"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin principal lacks required role or scope"


def test_admin_tenant_scope_enforced() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(_settings(jwt_shared_secret=secret, allow_api_key_fallback=True))
    client = TestClient(app)
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-a", name="A", plan="starter", status="active")
    )
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-b", name="B", plan="starter", status="active")
    )

    forbidden = client.get(
        "/v1/admin/tenants/tenant-b/usage",
        headers=_admin_headers(secret=secret, roles=["tenant_admin"], tenant_ids=["tenant-a"]),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Admin principal is not authorized for this tenant"

    allowed = client.get(
        "/v1/admin/tenants/tenant-a/usage",
        headers=_admin_headers(secret=secret, roles=["tenant_admin"], tenant_ids=["tenant-a"]),
    )
    assert allowed.status_code == 200


def test_admin_scope_only_tokens_follow_entra_mapping() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(_settings(jwt_shared_secret=secret))
    client = TestClient(app)

    plans = client.get(
        "/v1/admin/plans",
        headers=_admin_headers(secret=secret, scopes=["plans.read"]),
    )
    assert plans.status_code == 200

    create = client.post(
        "/v1/admin/plans",
        headers=_admin_headers(secret=secret, scopes=["plans.write"]),
        json={
            "plan_id": "scope-plan",
            "display_name": "Scope Plan",
            "monthly_messages": 100,
            "monthly_token_cap": 10000,
            "max_agents": 2,
            "active": True,
        },
    )
    assert create.status_code == 201

    export = client.get(
        "/v1/admin/usage/export",
        headers=_admin_headers(secret=secret, scopes=["billing.read"]),
    )
    assert export.status_code == 200


def test_api_execute_run_starts_telemetry_span(monkeypatch) -> None:
    settings = _settings(allow_api_key_fallback=True, default_rate_limit_rpm=20)
    app = create_app(settings)
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-dev", name="Acme", plan="starter", status="active")
    )
    _grant_agent_access(app, tenant_id="tenant-dev", customer_user_id="user-1", agent_id="support", display_name="Support")

    spans: list[str] = []

    class _Span:
        def set_attribute(self, _key: str, _value: object) -> None:
            return

        def record_exception(self, _err: BaseException) -> None:
            return

        def set_status(self, _status: object) -> None:
            return

    @contextmanager
    def _fake_start_span(name: str, _attributes: dict[str, object] | None = None):
        spans.append(name)
        yield _Span()

    import saas_platform.api.main as main_mod

    monkeypatch.setattr(main_mod, "start_span", _fake_start_span)

    client = TestClient(app)
    run = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers={
            "X-Tenant-Id": "tenant-dev",
            "X-Customer-User-Id": "user-1",
            "X-Api-Key": "dev-key-123",
        },
        json={"agent_id": "support", "user_id": "user-1", "message": "telemetry test"},
    )
    assert run.status_code == 200
    assert "api.runs.execute" in spans


def test_customer_agent_entitlement_admin_flow() -> None:
    secret = "admin-secret-1234567890-1234567890"
    app = create_app(_settings(allow_api_key_fallback=True, jwt_shared_secret=secret, default_rate_limit_rpm=20))
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-dev", name="Acme", plan="starter", status="active")
    )
    client = TestClient(app)

    run_headers = {
        "X-Tenant-Id": "tenant-dev",
        "X-Customer-User-Id": "cust-1",
        "X-Api-Key": "dev-key-123",
    }
    denied = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers=run_headers,
        json={"agent_id": "support", "user_id": "cust-1", "message": "hello"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "customer is not entitled to run this agent"

    admin_headers = _admin_headers(secret=secret, roles=["tenant_admin"], tenant_ids=["tenant-dev"])

    add_agent = client.post(
        "/v1/admin/tenants/tenant-dev/agents",
        headers=admin_headers,
        json={"agent_id": "support", "display_name": "Support", "active": True},
    )
    assert add_agent.status_code == 201

    grant = client.put(
        "/v1/admin/tenants/tenant-dev/customers/cust-1/agents/support",
        headers=admin_headers,
    )
    assert grant.status_code == 204

    list_access = client.get(
        "/v1/admin/tenants/tenant-dev/customers/cust-1/agents",
        headers=admin_headers,
    )
    assert list_access.status_code == 200
    assert list_access.json()["agent_ids"] == ["support"]

    allowed = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers=run_headers,
        json={"agent_id": "support", "user_id": "cust-1", "message": "hello"},
    )
    assert allowed.status_code == 200

    revoke = client.delete(
        "/v1/admin/tenants/tenant-dev/customers/cust-1/agents/support",
        headers=admin_headers,
    )
    assert revoke.status_code == 204

    denied_after_revoke = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers=run_headers,
        json={"agent_id": "support", "user_id": "cust-1", "message": "again"},
    )
    assert denied_after_revoke.status_code == 403
