from __future__ import annotations

from saas_platform.domain.interfaces import ProvisioningQueue, TenantCatalog


def process_next_job(queue: ProvisioningQueue, catalog: TenantCatalog) -> bool:
    """Process one queued provisioning job in an idempotent way."""
    job = queue.claim_next()
    if job is None:
        return False

    try:
        tenant = catalog.get_tenant(job.tenant_id)
        if tenant is None:
            queue.mark_failed(job.job_id, "tenant not found")
            return False

        if tenant.status != "active":
            tenant.status = "active"
            catalog.upsert_tenant(tenant)

        queue.mark_done(job.job_id)
        return True
    except Exception as err:
        queue.mark_failed(job.job_id, str(err))
        return False
