from __future__ import annotations

from abc import ABC, abstractmethod

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


class TenantCatalog(ABC):
    @abstractmethod
    def upsert_tenant(self, tenant: Tenant) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_tenant(self, tenant_id: str) -> Tenant | None:
        raise NotImplementedError


class PlanCatalog(ABC):
    @abstractmethod
    def upsert_plan(self, plan: Plan) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_plan(self, plan_id: str) -> Plan | None:
        raise NotImplementedError

    @abstractmethod
    def list_plans(self) -> list[Plan]:
        raise NotImplementedError


class AgentAccessCatalog(ABC):
    @abstractmethod
    def upsert_tenant_agent(self, agent: TenantAgent) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_tenant_agent(self, tenant_id: str, agent_id: str) -> TenantAgent | None:
        raise NotImplementedError

    @abstractmethod
    def list_tenant_agents(self, tenant_id: str) -> list[TenantAgent]:
        raise NotImplementedError

    @abstractmethod
    def grant_customer_agent(self, entitlement: CustomerAgentEntitlement) -> None:
        raise NotImplementedError

    @abstractmethod
    def revoke_customer_agent(self, tenant_id: str, customer_id: str, agent_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_customer_agents(self, tenant_id: str, customer_id: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def is_customer_entitled(self, tenant_id: str, customer_id: str, agent_id: str) -> bool:
        raise NotImplementedError


class ProvisioningQueue(ABC):
    @abstractmethod
    def enqueue(self, job: ProvisioningJob) -> None:
        raise NotImplementedError

    @abstractmethod
    def claim_next(self) -> ProvisioningJob | None:
        raise NotImplementedError

    @abstractmethod
    def mark_done(self, job_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_retry(self, job_id: str, error: str, retry_in_seconds: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_dead_letter(self, job_id: str, error: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> ProvisioningJob | None:
        raise NotImplementedError


class UsageMeter(ABC):
    @abstractmethod
    def record(self, event: UsageEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def summarize_tenant_month(self, tenant_id: str, month: str) -> TenantUsageSummary:
        raise NotImplementedError

    @abstractmethod
    def summarize_all_tenants_month(self, month: str) -> list[TenantBillingRecord]:
        raise NotImplementedError


class AgentGateway(ABC):
    @abstractmethod
    def execute(self, tenant_id: str, agent_id: str, message: str) -> str:
        raise NotImplementedError
