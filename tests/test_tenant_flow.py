from fastapi.testclient import TestClient

from saas_platform.api.main import create_app
from saas_platform.config import Settings
from saas_platform.domain.models import Tenant


def _settings(**overrides) -> Settings:
    base = Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="storage_queue",
        azure_ai_project_endpoint="",
        azure_ai_project_api_key="",
        azure_use_managed_identity=True,
        azure_managed_identity_client_id="",
        allow_api_key_fallback=False,
        key_vault_url="",
        tenant_api_keys={"tenant-dev": "dev-key-123"},
        jwt_shared_secret="",
        jwt_algorithm="HS256",
        default_rate_limit_rpm=2,
    )
    return Settings(**{**base.__dict__, **overrides})


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
            "X-Customer-Id": "user-1",
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

    client = TestClient(app)

    headers = {
        "X-Tenant-Id": "tenant-dev",
        "X-Customer-Id": "user-1",
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
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/v1/admin/debug/identity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["foundry_auth_mode"] == "managed_identity"
    assert payload["azure_use_managed_identity"] is True


def test_plan_admin_and_tenant_quota_enforcement() -> None:
    app = create_app(
        _settings(
            allow_api_key_fallback=True,
            default_rate_limit_rpm=20,
            tenant_api_keys={},
        )
    )
    client = TestClient(app)

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
    )
    assert plan.status_code == 201
    assert plan.json()["plan_id"] == "tiny"

    create_tenant = client.post("/v1/tenants", json={"name": "Tiny Co", "plan": "tiny"})
    assert create_tenant.status_code == 201
    tenant_id = create_tenant.json()["tenant_id"]

    process = client.post("/v1/provisioning/jobs/run-next")
    assert process.status_code == 200
    assert process.json()["processed"] is True

    headers = {
        "X-Tenant-Id": tenant_id,
        "X-Customer-Id": "user-1",
        "X-Api-Key": "",
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
    app = create_app(_settings(allow_api_key_fallback=True, default_rate_limit_rpm=20))
    client = TestClient(app)
    app.state.ctx.catalog.upsert_tenant(
        Tenant(tenant_id="tenant-dev", name="Acme", plan="starter", status="active")
    )

    run = client.post(
        "/v1/tenants/tenant-dev/runs",
        headers={
            "X-Tenant-Id": "tenant-dev",
            "X-Customer-Id": "user-1",
            "X-Api-Key": "dev-key-123",
        },
        json={"agent_id": "support", "user_id": "user-1", "message": "meter this"},
    )
    assert run.status_code == 200

    usage = client.get("/v1/admin/tenants/tenant-dev/usage")
    assert usage.status_code == 200
    usage_payload = usage.json()
    assert usage_payload["tenant_id"] == "tenant-dev"
    assert usage_payload["messages_used"] == 1
    assert usage_payload["tokens_used"] > 0

    export = client.get("/v1/admin/usage/export")
    assert export.status_code == 200
    rows = export.json()
    tenant_rows = [row for row in rows if row["tenant_id"] == "tenant-dev"]
    assert len(tenant_rows) == 1
    assert tenant_rows[0]["messages_used"] == 1
