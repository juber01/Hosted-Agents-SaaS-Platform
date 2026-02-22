from __future__ import annotations

from collections import deque

from saas_platform.domain.interfaces import PlanCatalog, ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import (
    Plan,
    ProvisioningJob,
    Tenant,
    TenantBillingRecord,
    TenantUsageSummary,
    UsageEvent,
)


class InMemoryTenantCatalog(TenantCatalog):
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    def upsert_tenant(self, tenant: Tenant) -> None:
        self._tenants[tenant.tenant_id] = tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)


class InMemoryPlanCatalog(PlanCatalog):
    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}

    def upsert_plan(self, plan: Plan) -> None:
        self._plans[plan.plan_id] = plan

    def get_plan(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def list_plans(self) -> list[Plan]:
        return sorted(self._plans.values(), key=lambda plan: plan.plan_id)


class InMemoryProvisioningQueue(ProvisioningQueue):
    def __init__(self) -> None:
        self.jobs: deque[ProvisioningJob] = deque()

    def enqueue(self, job: ProvisioningJob) -> None:
        self.jobs.append(job)

    def claim_next(self) -> ProvisioningJob | None:
        if not self.jobs:
            return None
        job = self.jobs.popleft()
        job.state = "running"
        return job

    def mark_done(self, job_id: str) -> None:
        return None

    def mark_failed(self, job_id: str, error: str) -> None:
        return None


class InMemoryUsageMeter(UsageMeter):
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> None:
        self.events.append(event)

    def summarize_tenant_month(self, tenant_id: str, month: str) -> TenantUsageSummary:
        events = [
            event
            for event in self.events
            if event.tenant_id == tenant_id and event.created_at.strftime("%Y-%m") == month
        ]
        return TenantUsageSummary(
            tenant_id=tenant_id,
            month=month,
            messages_used=len(events),
            tokens_used=sum(event.tokens_in + event.tokens_out for event in events),
            cost_estimate=sum(event.cost_estimate for event in events),
        )

    def summarize_all_tenants_month(self, month: str) -> list[TenantBillingRecord]:
        grouped: dict[str, TenantBillingRecord] = {}
        for event in self.events:
            if event.created_at.strftime("%Y-%m") != month:
                continue
            existing = grouped.get(event.tenant_id)
            if existing is None:
                grouped[event.tenant_id] = TenantBillingRecord(
                    tenant_id=event.tenant_id,
                    month=month,
                    messages_used=1,
                    tokens_used=event.tokens_in + event.tokens_out,
                    cost_estimate=event.cost_estimate,
                )
                continue
            grouped[event.tenant_id] = TenantBillingRecord(
                tenant_id=existing.tenant_id,
                month=month,
                messages_used=existing.messages_used + 1,
                tokens_used=existing.tokens_used + event.tokens_in + event.tokens_out,
                cost_estimate=existing.cost_estimate + event.cost_estimate,
            )
        return sorted(grouped.values(), key=lambda record: record.tenant_id)
