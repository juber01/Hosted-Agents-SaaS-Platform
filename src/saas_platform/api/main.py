from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException

from saas_platform.adapters.foundry import FoundryAgentGateway
from saas_platform.adapters.storage import (
    InMemoryPlanCatalog,
    InMemoryProvisioningQueue,
    InMemoryTenantCatalog,
    InMemoryUsageMeter,
)
from saas_platform.config import Settings, get_settings
from saas_platform.domain.interfaces import PlanCatalog, ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import (
    CreatePlanRequest,
    CreateTenantRequest,
    CreateTenantResponse,
    ExecuteRunRequest,
    ExecuteRunResponse,
    Plan,
    PlanLimits,
    ProvisioningJob,
    Tenant,
    TenantBillingRecord,
    TenantUsageSummary,
    UpdateTenantPlanRequest,
    UsageEvent,
)
from saas_platform.policies.auth import AdminAuthService, AdminPrincipal, TenantAuthService, tenant_headers
from saas_platform.policies.quota import QuotaCounter, QuotaPolicy, allow_request
from saas_platform.policies.rate_limit import FixedWindowRateLimiter
from saas_platform.provisioning.worker import process_next_job
from saas_platform.telemetry import telemetry_tags


@dataclass
class AppContext:
    settings: Settings
    catalog: TenantCatalog
    plans: PlanCatalog
    queue: ProvisioningQueue
    usage: UsageMeter
    auth: TenantAuthService
    admin_auth: AdminAuthService
    limiter: FixedWindowRateLimiter
    gateway: FoundryAgentGateway


_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def _default_plans() -> list[Plan]:
    return [
        Plan(
            plan_id="starter",
            display_name="Starter",
            limits=PlanLimits(monthly_messages=5_000, monthly_token_cap=2_000_000, max_agents=3),
        ),
        Plan(
            plan_id="growth",
            display_name="Growth",
            limits=PlanLimits(monthly_messages=25_000, monthly_token_cap=10_000_000, max_agents=15),
        ),
        Plan(
            plan_id="enterprise",
            display_name="Enterprise",
            limits=PlanLimits(monthly_messages=200_000, monthly_token_cap=120_000_000, max_agents=100),
        ),
    ]


def _seed_default_plans(plans: PlanCatalog) -> None:
    for plan in _default_plans():
        if plans.get_plan(plan.plan_id) is None:
            plans.upsert_plan(plan)


def _current_month_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _normalize_month(month: str | None) -> str:
    if month is None:
        return _current_month_utc()
    text = month.strip()
    if not _MONTH_PATTERN.match(text):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError as err:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM") from err
    return text


def _build_context(settings: Settings) -> AppContext:
    if settings.tenant_catalog_dsn:
        try:
            from saas_platform.adapters.postgres import (
                PostgresPlanCatalog,
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
        catalog = PostgresTenantCatalog(sf)
        plans = PostgresPlanCatalog(sf)
        queue = PostgresProvisioningQueue(sf)
        usage = PostgresUsageMeter(sf)
    else:
        catalog = InMemoryTenantCatalog()
        plans = InMemoryPlanCatalog()
        queue = InMemoryProvisioningQueue()
        usage = InMemoryUsageMeter()

    _seed_default_plans(plans)

    return AppContext(
        settings=settings,
        catalog=catalog,
        plans=plans,
        queue=queue,
        usage=usage,
        auth=TenantAuthService(settings),
        admin_auth=AdminAuthService(settings),
        limiter=FixedWindowRateLimiter(settings.default_rate_limit_rpm),
        gateway=FoundryAgentGateway(settings),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    ctx = _build_context(active_settings)

    app = FastAPI(title="Hosted Agents SaaS Platform", version="0.2.0")
    app.state.ctx = ctx

    def _authorize_admin(
        *,
        authorization: str,
        required_roles: set[str] | None = None,
        required_scopes: set[str] | None = None,
        tenant_id: str | None = None,
    ) -> AdminPrincipal:
        principal = ctx.admin_auth.authenticate(authorization=authorization)
        ctx.admin_auth.authorize(
            principal=principal,
            required_roles=required_roles,
            required_scopes=required_scopes,
            tenant_id=tenant_id,
        )
        return principal

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/admin/debug/identity")
    def debug_identity(
        authorization: str = Header(default="", alias="Authorization"),
    ) -> dict[str, str | bool]:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin"},
            required_scopes={"admin.identity.read"},
        )
        return {
            "foundry_auth_mode": ctx.gateway.auth_mode,
            "azure_use_managed_identity": ctx.settings.azure_use_managed_identity,
            "allow_api_key_fallback": ctx.settings.allow_api_key_fallback,
            "key_vault_configured": bool(ctx.settings.key_vault_url),
        }

    @app.get("/v1/admin/plans", response_model=list[Plan])
    def list_plans(
        authorization: str = Header(default="", alias="Authorization"),
    ) -> list[Plan]:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin"},
            required_scopes={"plans.read"},
        )
        return ctx.plans.list_plans()

    @app.get("/v1/admin/plans/{plan_id}", response_model=Plan)
    def get_plan(
        plan_id: str,
        authorization: str = Header(default="", alias="Authorization"),
    ) -> Plan:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin"},
            required_scopes={"plans.read"},
        )
        plan = ctx.plans.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="plan not found")
        return plan

    @app.post("/v1/admin/plans", response_model=Plan, status_code=201)
    def upsert_plan(
        request: CreatePlanRequest,
        authorization: str = Header(default="", alias="Authorization"),
    ) -> Plan:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin"},
            required_scopes={"plans.write"},
        )
        plan = Plan(
            plan_id=request.plan_id,
            display_name=request.display_name,
            limits=PlanLimits(
                monthly_messages=request.monthly_messages,
                monthly_token_cap=request.monthly_token_cap,
                max_agents=request.max_agents,
            ),
            active=request.active,
        )
        ctx.plans.upsert_plan(plan)
        return plan

    @app.post("/v1/tenants", response_model=CreateTenantResponse, status_code=201)
    def create_tenant(request: CreateTenantRequest) -> CreateTenantResponse:
        selected_plan = ctx.plans.get_plan(request.plan)
        if selected_plan is None or not selected_plan.active:
            raise HTTPException(status_code=400, detail="invalid or inactive plan")

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

    @app.patch("/v1/admin/tenants/{tenant_id}/plan")
    def update_tenant_plan(
        tenant_id: str,
        request: UpdateTenantPlanRequest,
        authorization: str = Header(default="", alias="Authorization"),
    ) -> dict:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin", "tenant_admin"},
            required_scopes={"tenant.plan.write"},
            tenant_id=tenant_id,
        )
        tenant = ctx.catalog.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")

        selected_plan = ctx.plans.get_plan(request.plan_id)
        if selected_plan is None or not selected_plan.active:
            raise HTTPException(status_code=400, detail="invalid or inactive plan")

        tenant.plan = request.plan_id
        ctx.catalog.upsert_tenant(tenant)
        return tenant.model_dump(mode="json")

    @app.get("/v1/admin/tenants/{tenant_id}/usage", response_model=TenantUsageSummary)
    def tenant_usage(
        tenant_id: str,
        month: str | None = None,
        authorization: str = Header(default="", alias="Authorization"),
    ) -> TenantUsageSummary:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin", "tenant_admin", "billing_reader"},
            required_scopes={"tenant.usage.read", "billing.read"},
            tenant_id=tenant_id,
        )
        tenant = ctx.catalog.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        normalized_month = _normalize_month(month)
        return ctx.usage.summarize_tenant_month(tenant_id=tenant_id, month=normalized_month)

    @app.get("/v1/admin/usage/export", response_model=list[TenantBillingRecord])
    def export_usage(
        month: str | None = None,
        authorization: str = Header(default="", alias="Authorization"),
    ) -> list[TenantBillingRecord]:
        _authorize_admin(
            authorization=authorization,
            required_roles={"platform_admin", "billing_reader"},
            required_scopes={"usage.export", "billing.read"},
        )
        normalized_month = _normalize_month(month)
        return ctx.usage.summarize_all_tenants_month(month=normalized_month)

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
        plan = ctx.plans.get_plan(tenant.plan)
        if plan is None or not plan.active:
            raise HTTPException(status_code=409, detail="tenant plan is invalid or inactive")

        rate_key = f"{tenant_ctx.tenant_id}:{request.agent_id}"
        if not ctx.limiter.allow(rate_key):
            raise HTTPException(status_code=429, detail="tenant rate limit exceeded")

        month = _current_month_utc()
        usage_summary = ctx.usage.summarize_tenant_month(tenant_id=tenant_id, month=month)
        estimated_tokens = max(len(request.message) // 4, 1) * 2
        policy = QuotaPolicy(
            included_messages=plan.limits.monthly_messages,
            hard_token_cap=plan.limits.monthly_token_cap,
        )
        counter = QuotaCounter(
            messages_used=usage_summary.messages_used,
            tokens_used=usage_summary.tokens_used,
        )
        if not allow_request(policy=policy, counter=counter, estimated_tokens=estimated_tokens):
            raise HTTPException(status_code=429, detail="tenant monthly quota exceeded")

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
