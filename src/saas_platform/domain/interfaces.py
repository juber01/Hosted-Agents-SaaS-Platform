from __future__ import annotations

from abc import ABC, abstractmethod

from saas_platform.domain.models import ProvisioningJob, Tenant, UsageEvent


class TenantCatalog(ABC):
    @abstractmethod
    def upsert_tenant(self, tenant: Tenant) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_tenant(self, tenant_id: str) -> Tenant | None:
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


class AgentGateway(ABC):
    @abstractmethod
    def execute(self, tenant_id: str, agent_id: str, message: str) -> str:
        raise NotImplementedError
