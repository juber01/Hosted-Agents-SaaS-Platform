from __future__ import annotations

from abc import ABC, abstractmethod

from saas_platform.domain.models import Plan, ProvisioningJob, Tenant, TenantBillingRecord, TenantUsageSummary, UsageEvent


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
    def mark_failed(self, job_id: str, error: str) -> None:
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
