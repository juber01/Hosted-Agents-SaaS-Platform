from fastapi.testclient import TestClient

from saas_platform.api.main import create_app
from saas_platform.config import Settings
from saas_platform.domain.models import Tenant


def _settings() -> Settings:
    return Settings(
        app_env="dev",
        tenant_catalog_dsn="",
        provisioning_queue_backend="storage_queue",
        azure_ai_project_endpoint="",
        azure_ai_project_api_key="",
        tenant_api_keys={"tenant-dev": "dev-key-123"},
        jwt_shared_secret="",
        jwt_algorithm="HS256",
        default_rate_limit_rpm=2,
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
            "X-Customer-Id": "user-1",
            "X-Api-Key": "",
        },
        json={"agent_id": "support", "user_id": "user-1", "message": "hello"},
    )
    assert run.status_code == 401


def test_api_key_auth_and_rate_limit() -> None:
    app = create_app(_settings())
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
