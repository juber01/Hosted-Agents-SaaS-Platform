from __future__ import annotations

from collections import deque

from saas_platform.domain.interfaces import ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import ProvisioningJob, Tenant, UsageEvent


class InMemoryTenantCatalog(TenantCatalog):
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    def upsert_tenant(self, tenant: Tenant) -> None:
        self._tenants[tenant.tenant_id] = tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)


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
