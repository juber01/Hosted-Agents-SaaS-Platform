from __future__ import annotations

from datetime import datetime, timedelta, timezone

from saas_platform.domain.interfaces import AgentAccessCatalog, PlanCatalog, ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import (
    CustomerAgentEntitlement,
    Plan,
    ProvisioningJob,
    Tenant,
    TenantAgent,
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


class InMemoryAgentAccessCatalog(AgentAccessCatalog):
    def __init__(self) -> None:
        self._tenant_agents: dict[tuple[str, str], TenantAgent] = {}
        self._entitlements: set[tuple[str, str, str]] = set()

    def upsert_tenant_agent(self, agent: TenantAgent) -> None:
        self._tenant_agents[(agent.tenant_id, agent.agent_id)] = agent

    def get_tenant_agent(self, tenant_id: str, agent_id: str) -> TenantAgent | None:
        return self._tenant_agents.get((tenant_id, agent_id))

    def list_tenant_agents(self, tenant_id: str) -> list[TenantAgent]:
        return sorted(
            [agent for (tid, _), agent in self._tenant_agents.items() if tid == tenant_id],
            key=lambda agent: agent.agent_id,
        )

    def grant_customer_agent(self, entitlement: CustomerAgentEntitlement) -> None:
        self._entitlements.add((entitlement.tenant_id, entitlement.customer_id, entitlement.agent_id))

    def revoke_customer_agent(self, tenant_id: str, customer_id: str, agent_id: str) -> None:
        self._entitlements.discard((tenant_id, customer_id, agent_id))

    def list_customer_agents(self, tenant_id: str, customer_id: str) -> list[str]:
        permitted = {
            agent_id
            for tid, cid, agent_id in self._entitlements
            if tid == tenant_id and cid in {customer_id, "*"}
        }
        return sorted(permitted)

    def is_customer_entitled(self, tenant_id: str, customer_id: str, agent_id: str) -> bool:
        agent = self.get_tenant_agent(tenant_id=tenant_id, agent_id=agent_id)
        if agent is None or not agent.active:
            return False
        return (tenant_id, customer_id, agent_id) in self._entitlements or (tenant_id, "*", agent_id) in self._entitlements


class InMemoryProvisioningQueue(ProvisioningQueue):
    def __init__(self) -> None:
        self._jobs: dict[str, ProvisioningJob] = {}
        self._job_order: list[str] = []

    def enqueue(self, job: ProvisioningJob) -> None:
        idempotency_key = job.idempotency_key or job.job_id
        for existing in self._jobs.values():
            if existing.idempotency_key == idempotency_key:
                return

        queued = job.model_copy(
            update={
                "idempotency_key": idempotency_key,
                "state": "queued",
                "available_at": job.available_at or datetime.now(timezone.utc),
            }
        )
        self._jobs[queued.job_id] = queued
        self._job_order.append(queued.job_id)

    def claim_next(self) -> ProvisioningJob | None:
        if not self._jobs:
            return None

        now = datetime.now(timezone.utc)
        candidates = [self._jobs[job_id] for job_id in self._job_order if job_id in self._jobs]
        for job in sorted(candidates, key=lambda item: item.available_at):
            if job.state != "queued" or job.available_at > now:
                continue
            job.state = "running"
            return job.model_copy()
        return None

    def mark_done(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = "done"

    def mark_retry(self, job_id: str, error: str, retry_in_seconds: int) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = "queued"
        job.retries += 1
        job.error = error[:500]
        job.available_at = datetime.now(timezone.utc) + timedelta(seconds=max(retry_in_seconds, 0))

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = "dead_letter"
        job.retries += 1
        job.error = error[:500]

    def get_job(self, job_id: str) -> ProvisioningJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return job.model_copy()


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
