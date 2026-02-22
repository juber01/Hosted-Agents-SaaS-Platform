from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException

from saas_platform.adapters.foundry import FoundryAgentGateway
from saas_platform.adapters.storage import InMemoryProvisioningQueue, InMemoryTenantCatalog, InMemoryUsageMeter
from saas_platform.config import Settings, get_settings
from saas_platform.domain.interfaces import ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import (
    CreateTenantRequest,
    CreateTenantResponse,
    ExecuteRunRequest,
    ExecuteRunResponse,
    ProvisioningJob,
    Tenant,
    UsageEvent,
)
from saas_platform.policies.auth import TenantAuthService, tenant_headers
from saas_platform.policies.rate_limit import FixedWindowRateLimiter
from saas_platform.provisioning.worker import process_next_job
from saas_platform.telemetry import telemetry_tags


@dataclass
class AppContext:
    settings: Settings
    catalog: TenantCatalog
    queue: ProvisioningQueue
    usage: UsageMeter
    auth: TenantAuthService
    limiter: FixedWindowRateLimiter
    gateway: FoundryAgentGateway


def _build_context(settings: Settings) -> AppContext:
    if settings.tenant_catalog_dsn:
        try:
            from saas_platform.adapters.postgres import (
                PostgresProvisioningQueue,
                PostgresSessionFactory,
                PostgresTenantCatalog,
                PostgresUsageMeter,
            )
        except ModuleNotFoundError as err:
            raise RuntimeError(
                "Postgres mode requires SQLAlchemy/Alembic dependencies. "
                "Install project dependencies before setting TENANT_CATALOG_DSN."
            ) from err

        sf = PostgresSessionFactory(settings.tenant_catalog_dsn)
        sf.create_all()
        catalog = PostgresTenantCatalog(sf)
        queue = PostgresProvisioningQueue(sf)
        usage = PostgresUsageMeter(sf)
    else:
        catalog = InMemoryTenantCatalog()
        queue = InMemoryProvisioningQueue()
        usage = InMemoryUsageMeter()

    return AppContext(
        settings=settings,
        catalog=catalog,
        queue=queue,
        usage=usage,
        auth=TenantAuthService(settings),
        limiter=FixedWindowRateLimiter(settings.default_rate_limit_rpm),
        gateway=FoundryAgentGateway(),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    ctx = _build_context(active_settings)

    app = FastAPI(title="Hosted Agents SaaS Platform", version="0.2.0")
    app.state.ctx = ctx

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants", response_model=CreateTenantResponse, status_code=201)
    def create_tenant(request: CreateTenantRequest) -> CreateTenantResponse:
        tenant_id = str(uuid4())
        job_id = str(uuid4())

        ctx.catalog.upsert_tenant(Tenant(tenant_id=tenant_id, name=request.name, plan=request.plan))
        ctx.queue.enqueue(ProvisioningJob(job_id=job_id, tenant_id=tenant_id, step="bootstrap"))

        return CreateTenantResponse(tenant_id=tenant_id, status="pending", provisioning_job_id=job_id)

    @app.get("/v1/tenants/{tenant_id}")
    def get_tenant(tenant_id: str) -> dict:
        tenant = ctx.catalog.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        return tenant.model_dump(mode="json")

    @app.post("/v1/provisioning/jobs/run-next")
    def run_next_provisioning_job() -> dict[str, bool]:
        processed = process_next_job(queue=ctx.queue, catalog=ctx.catalog)
        return {"processed": processed}

    @app.post("/v1/tenants/{tenant_id}/runs", response_model=ExecuteRunResponse)
    def execute_run(
        tenant_id: str,
        request: ExecuteRunRequest,
        headers: tuple[str, str, str, str] = Depends(tenant_headers),
    ) -> ExecuteRunResponse:
        x_tenant_id, x_customer_id, x_api_key, authorization = headers
        tenant_ctx = ctx.auth.authenticate(
            path_tenant_id=tenant_id,
            x_tenant_id=x_tenant_id,
            x_customer_id=x_customer_id,
            x_api_key=x_api_key,
            authorization=authorization,
        )

        tenant = ctx.catalog.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        if tenant.status != "active":
            raise HTTPException(status_code=409, detail="tenant is not active yet")

        rate_key = f"{tenant_ctx.tenant_id}:{request.agent_id}"
        if not ctx.limiter.allow(rate_key):
            raise HTTPException(status_code=429, detail="tenant rate limit exceeded")

        request_id = str(uuid4())
        output_text = ctx.gateway.execute(tenant_id=tenant_id, agent_id=request.agent_id, message=request.message)

        ctx.usage.record(
            UsageEvent(
                tenant_id=tenant_id,
                agent_id=request.agent_id,
                request_id=request_id,
                model="provider-default",
                latency_ms=0,
                tokens_in=max(len(request.message) // 4, 1),
                tokens_out=max(len(output_text) // 4, 1),
                cost_estimate=0.0,
            )
        )

        _ = telemetry_tags(
            tenant_id=tenant_id,
            agent_id=request.agent_id,
            request_id=request_id,
            plan=tenant.plan,
            model="provider-default",
            environment=ctx.settings.app_env,
        )

        return ExecuteRunResponse(tenant_id=tenant_id, request_id=request_id, output_text=output_text)

    return app


app = create_app()
