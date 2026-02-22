from __future__ import annotations

from saas_platform.domain.interfaces import ProvisioningQueue, TenantCatalog


def process_next_job(
    queue: ProvisioningQueue,
    catalog: TenantCatalog,
    default_max_attempts: int = 3,
    retry_base_seconds: int = 5,
) -> bool:
    """Process one queued provisioning job in an idempotent way."""
    job = queue.claim_next()
    if job is None:
        return False

    max_attempts = max(job.max_attempts, default_max_attempts, 1)

    try:
        tenant = catalog.get_tenant(job.tenant_id)
        if tenant is None:
            queue.mark_dead_letter(job.job_id, "tenant not found")
            return False

        if tenant.status != "active":
            tenant.status = "active"
            catalog.upsert_tenant(tenant)

        queue.mark_done(job.job_id)
        return True
    except Exception as err:
        if job.retries + 1 >= max_attempts:
            queue.mark_dead_letter(job.job_id, str(err))
            return False

        delay_seconds = max(retry_base_seconds, 0) * (2 ** max(job.retries, 0))
        queue.mark_retry(job.job_id, str(err), retry_in_seconds=delay_seconds)
        return False
