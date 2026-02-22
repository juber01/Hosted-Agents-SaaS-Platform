from __future__ import annotations

from contextlib import contextmanager
import logging

import pytest

from saas_platform.adapters.storage import InMemoryProvisioningQueue, InMemoryTenantCatalog
from saas_platform.domain.models import ProvisioningJob, Tenant
from saas_platform.provisioning.worker import process_next_job


def test_provisioning_worker_activates_tenant_and_marks_done() -> None:
    queue = InMemoryProvisioningQueue()
    catalog = InMemoryTenantCatalog()
    catalog.upsert_tenant(Tenant(tenant_id="tenant-1", name="Acme", plan="starter", status="pending"))

    queue.enqueue(
        ProvisioningJob(
            job_id="job-1",
            tenant_id="tenant-1",
            step="bootstrap",
            idempotency_key="tenant-1:bootstrap",
            max_attempts=3,
        )
    )

    processed = process_next_job(queue=queue, catalog=catalog, default_max_attempts=3, retry_base_seconds=0)
    assert processed is True

    job = queue.get_job("job-1")
    assert job is not None
    assert job.state == "done"
    assert catalog.get_tenant("tenant-1") is not None
    assert catalog.get_tenant("tenant-1").status == "active"


def test_provisioning_worker_dead_letters_missing_tenant() -> None:
    queue = InMemoryProvisioningQueue()
    catalog = InMemoryTenantCatalog()

    queue.enqueue(
        ProvisioningJob(
            job_id="job-2",
            tenant_id="tenant-missing",
            step="bootstrap",
            idempotency_key="tenant-missing:bootstrap",
            max_attempts=3,
        )
    )

    processed = process_next_job(queue=queue, catalog=catalog, default_max_attempts=3, retry_base_seconds=0)
    assert processed is False

    job = queue.get_job("job-2")
    assert job is not None
    assert job.state == "dead_letter"
    assert job.retries == 1
    assert job.error == "tenant not found"


def test_provisioning_worker_retries_then_dead_letters_on_exceptions() -> None:
    queue = InMemoryProvisioningQueue()
    catalog = InMemoryTenantCatalog()
    catalog.upsert_tenant(Tenant(tenant_id="tenant-2", name="Beta", plan="starter", status="active"))

    original_get_tenant = catalog.get_tenant

    def _failing_get_tenant(tenant_id: str) -> Tenant | None:
        raise RuntimeError("simulated failure")

    catalog.get_tenant = _failing_get_tenant  # type: ignore[method-assign]
    queue.enqueue(
        ProvisioningJob(
            job_id="job-3",
            tenant_id="tenant-2",
            step="bootstrap",
            idempotency_key="tenant-2:bootstrap",
            max_attempts=2,
        )
    )

    first = process_next_job(queue=queue, catalog=catalog, default_max_attempts=2, retry_base_seconds=0)
    assert first is False
    first_job = queue.get_job("job-3")
    assert first_job is not None
    assert first_job.state == "queued"
    assert first_job.retries == 1
    assert "simulated failure" in (first_job.error or "")

    second = process_next_job(queue=queue, catalog=catalog, default_max_attempts=2, retry_base_seconds=0)
    assert second is False
    second_job = queue.get_job("job-3")
    assert second_job is not None
    assert second_job.state == "dead_letter"
    assert second_job.retries == 2

    catalog.get_tenant = original_get_tenant  # type: ignore[method-assign]


def test_provisioning_queue_idempotency_key_deduplicates_jobs() -> None:
    queue = InMemoryProvisioningQueue()
    catalog = InMemoryTenantCatalog()
    catalog.upsert_tenant(Tenant(tenant_id="tenant-3", name="Gamma", plan="starter", status="pending"))

    queue.enqueue(
        ProvisioningJob(
            job_id="job-4a",
            tenant_id="tenant-3",
            step="bootstrap",
            idempotency_key="tenant-3:bootstrap",
        )
    )
    queue.enqueue(
        ProvisioningJob(
            job_id="job-4b",
            tenant_id="tenant-3",
            step="bootstrap",
            idempotency_key="tenant-3:bootstrap",
        )
    )

    first = process_next_job(queue=queue, catalog=catalog, default_max_attempts=3, retry_base_seconds=0)
    assert first is True
    second = process_next_job(queue=queue, catalog=catalog, default_max_attempts=3, retry_base_seconds=0)
    assert second is False

    assert queue.get_job("job-4a") is not None
    assert queue.get_job("job-4b") is None


def test_provisioning_worker_emits_structured_retry_and_dead_letter_logs(caplog: pytest.LogCaptureFixture) -> None:
    queue = InMemoryProvisioningQueue()
    catalog = InMemoryTenantCatalog()
    catalog.upsert_tenant(Tenant(tenant_id="tenant-4", name="Delta", plan="starter", status="active"))

    original_get_tenant = catalog.get_tenant

    def _failing_get_tenant(_tenant_id: str) -> Tenant | None:
        raise RuntimeError("log-test-failure")

    catalog.get_tenant = _failing_get_tenant  # type: ignore[method-assign]
    queue.enqueue(
        ProvisioningJob(
            job_id="job-5",
            tenant_id="tenant-4",
            step="bootstrap",
            idempotency_key="tenant-4:bootstrap",
            max_attempts=2,
        )
    )

    caplog.set_level(logging.INFO)
    process_next_job(queue=queue, catalog=catalog, default_max_attempts=2, retry_base_seconds=0)
    process_next_job(queue=queue, catalog=catalog, default_max_attempts=2, retry_base_seconds=0)
    catalog.get_tenant = original_get_tenant  # type: ignore[method-assign]

    logged = "\n".join(record.message for record in caplog.records)
    assert "provisioning_job_retry" in logged
    assert "provisioning_job_dead_letter" in logged
    assert "tenant-4" in logged


def test_provisioning_worker_starts_telemetry_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = InMemoryProvisioningQueue()
    catalog = InMemoryTenantCatalog()
    catalog.upsert_tenant(Tenant(tenant_id="tenant-5", name="Echo", plan="starter", status="pending"))
    queue.enqueue(
        ProvisioningJob(
            job_id="job-6",
            tenant_id="tenant-5",
            step="bootstrap",
            idempotency_key="tenant-5:bootstrap",
            max_attempts=3,
        )
    )

    spans: list[str] = []

    class _Span:
        def set_attribute(self, _key: str, _value: object) -> None:
            return

        def record_exception(self, _err: BaseException) -> None:
            return

        def set_status(self, _status: object) -> None:
            return

    @contextmanager
    def _fake_start_span(name: str, _attributes: dict[str, object] | None = None):
        spans.append(name)
        yield _Span()

    import saas_platform.provisioning.worker as worker_mod

    monkeypatch.setattr(worker_mod, "start_span", _fake_start_span)
    process_next_job(queue=queue, catalog=catalog, default_max_attempts=3, retry_base_seconds=0)
    assert "worker.provisioning.process" in spans
