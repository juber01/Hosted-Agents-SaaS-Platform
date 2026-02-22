from __future__ import annotations

import json
import logging

from saas_platform.domain.interfaces import ProvisioningQueue, TenantCatalog
from saas_platform.telemetry import span_record_error, span_set_attributes, start_span, telemetry_tags


_logger = logging.getLogger(__name__)


def process_next_job(
    queue: ProvisioningQueue,
    catalog: TenantCatalog,
    default_max_attempts: int = 3,
    retry_base_seconds: int = 5,
) -> bool:
    """Process one queued provisioning job in an idempotent way."""
    job = queue.claim_next()
    if job is None:
        with start_span("worker.provisioning.poll", {"worker.processed": False}):
            pass
        return False

    max_attempts = max(job.max_attempts, default_max_attempts, 1)
    span_attrs = telemetry_tags(
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        environment="worker",
    )
    span_attrs.update(
        {
            "provisioning.step": job.step,
            "provisioning.retries": job.retries,
            "provisioning.max_attempts": max_attempts,
        }
    )

    with start_span("worker.provisioning.process", span_attrs) as span:
        try:
            tenant = catalog.get_tenant(job.tenant_id)
            if tenant is None:
                queue.mark_dead_letter(job.job_id, "tenant not found")
                span_set_attributes(
                    span,
                    telemetry_tags(
                        tenant_id=job.tenant_id,
                        job_id=job.job_id,
                        failure_type="tenant_not_found",
                    ),
                )
                _log_event(
                    "provisioning_job_dead_letter",
                    job_id=job.job_id,
                    tenant_id=job.tenant_id,
                    step=job.step,
                    retries=job.retries + 1,
                    max_attempts=max_attempts,
                    reason="tenant not found",
                )
                return False

            if tenant.status != "active":
                tenant.status = "active"
                catalog.upsert_tenant(tenant)

            queue.mark_done(job.job_id)
            _log_event(
                "provisioning_job_completed",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                step=job.step,
                retries=job.retries,
            )
            return True
        except Exception as err:
            failure_type = err.__class__.__name__
            if job.retries + 1 >= max_attempts:
                queue.mark_dead_letter(job.job_id, str(err))
                span_record_error(span, err, failure_type=failure_type)
                _log_event(
                    "provisioning_job_dead_letter",
                    job_id=job.job_id,
                    tenant_id=job.tenant_id,
                    step=job.step,
                    retries=job.retries + 1,
                    max_attempts=max_attempts,
                    reason=str(err),
                    failure_type=failure_type,
                )
                return False

            delay_seconds = max(retry_base_seconds, 0) * (2 ** max(job.retries, 0))
            queue.mark_retry(job.job_id, str(err), retry_in_seconds=delay_seconds)
            span_record_error(span, err, failure_type=failure_type)
            span_set_attributes(span, {"provisioning.retry_in_seconds": delay_seconds})
            _log_event(
                "provisioning_job_retry",
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                step=job.step,
                retries=job.retries + 1,
                max_attempts=max_attempts,
                retry_in_seconds=delay_seconds,
                reason=str(err),
                failure_type=failure_type,
            )
            return False


def _log_event(event: str, **fields: object) -> None:
    payload = {"event": event, **fields}
    _logger.info("%s", json.dumps(payload, sort_keys=True, default=str))
