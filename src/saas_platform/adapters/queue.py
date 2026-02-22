from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from saas_platform.domain.interfaces import ProvisioningQueue
from saas_platform.domain.models import ProvisioningJob


class StorageQueueProvisioningQueue(ProvisioningQueue):
    """Azure Storage Queue transport wrapper over a durable queue store."""

    def __init__(
        self,
        *,
        delegate: ProvisioningQueue,
        queue_name: str,
        connection_string: str | None = None,
        account_url: str | None = None,
        credential: Any | None = None,
        dead_letter_queue_name: str | None = None,
        visibility_timeout_seconds: int = 30,
    ) -> None:
        self._delegate = delegate
        self._queue_name = queue_name
        self._dead_letter_queue_name = dead_letter_queue_name or f"{queue_name}-deadletter"
        self._visibility_timeout_seconds = max(visibility_timeout_seconds, 1)
        self._inflight: dict[str, tuple[str, str]] = {}

        try:
            from azure.storage.queue import QueueServiceClient
        except ModuleNotFoundError as err:
            raise RuntimeError(
                "Storage queue backend requires 'azure-storage-queue'. Install dependencies before use."
            ) from err

        if connection_string:
            service = QueueServiceClient.from_connection_string(connection_string)
        elif account_url and credential is not None:
            service = QueueServiceClient(account_url=account_url, credential=credential)
        else:
            raise RuntimeError(
                "StorageQueueProvisioningQueue requires either connection_string or account_url+credential."
            )
        self._queue_client = service.get_queue_client(queue_name)
        self._dead_letter_client = service.get_queue_client(self._dead_letter_queue_name)

    def enqueue(self, job: ProvisioningJob) -> None:
        self._delegate.enqueue(job)
        self._send_signal({"job_id": job.job_id})

    def claim_next(self) -> ProvisioningJob | None:
        message = self._receive_signal()
        job = self._delegate.claim_next()

        if message is not None and job is not None:
            self._inflight[job.job_id] = message

        return job

    def mark_done(self, job_id: str) -> None:
        self._delegate.mark_done(job_id)
        self._ack_signal(job_id)

    def mark_retry(self, job_id: str, error: str, retry_in_seconds: int) -> None:
        self._delegate.mark_retry(job_id, error, retry_in_seconds)
        self._ack_signal(job_id)
        self._send_signal({"job_id": job_id, "retry": True}, visibility_timeout=max(retry_in_seconds, 0))

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        self._delegate.mark_dead_letter(job_id, error)
        self._ack_signal(job_id)
        self._send_dead_letter({"job_id": job_id, "error": error[:500]})

    def get_job(self, job_id: str) -> ProvisioningJob | None:
        return self._delegate.get_job(job_id)

    def _send_signal(self, payload: dict[str, Any], visibility_timeout: int = 0) -> None:
        self._queue_client.send_message(
            json.dumps(payload),
            visibility_timeout=max(visibility_timeout, 0),
        )

    def _receive_signal(self) -> tuple[str, str] | None:
        messages = self._queue_client.receive_messages(
            messages_per_page=1,
            visibility_timeout=self._visibility_timeout_seconds,
        )
        for message in messages:
            return message.id, message.pop_receipt
        return None

    def _ack_signal(self, job_id: str) -> None:
        inflight = self._inflight.pop(job_id, None)
        if inflight is None:
            return
        message_id, pop_receipt = inflight
        self._queue_client.delete_message(message_id, pop_receipt)

    def _send_dead_letter(self, payload: dict[str, Any]) -> None:
        self._dead_letter_client.send_message(json.dumps(payload))


class ServiceBusProvisioningQueue(ProvisioningQueue):
    """Azure Service Bus transport wrapper over a durable queue store."""

    def __init__(
        self,
        *,
        delegate: ProvisioningQueue,
        queue_name: str,
        connection_string: str | None = None,
        fully_qualified_namespace: str | None = None,
        credential: Any | None = None,
        dead_letter_queue_name: str | None = None,
    ) -> None:
        self._delegate = delegate
        self._queue_name = queue_name
        self._dead_letter_queue_name = dead_letter_queue_name or f"{queue_name}-deadletter"

        try:
            from azure.servicebus import ServiceBusClient
        except ModuleNotFoundError as err:
            raise RuntimeError("Service Bus backend requires 'azure-servicebus'. Install dependencies first.") from err

        if connection_string:
            self._client = ServiceBusClient.from_connection_string(connection_string)
        elif fully_qualified_namespace and credential is not None:
            self._client = ServiceBusClient(
                fully_qualified_namespace=fully_qualified_namespace,
                credential=credential,
            )
        else:
            raise RuntimeError(
                "ServiceBusProvisioningQueue requires either connection_string or fully_qualified_namespace+credential."
            )

    def enqueue(self, job: ProvisioningJob) -> None:
        self._delegate.enqueue(job)
        self._send_signal({"job_id": job.job_id})

    def claim_next(self) -> ProvisioningJob | None:
        self._receive_signal()
        return self._delegate.claim_next()

    def mark_done(self, job_id: str) -> None:
        self._delegate.mark_done(job_id)

    def mark_retry(self, job_id: str, error: str, retry_in_seconds: int) -> None:
        self._delegate.mark_retry(job_id, error, retry_in_seconds)
        schedule_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=max(retry_in_seconds, 0))
        self._send_signal(
            {"job_id": job_id, "retry": True},
            scheduled_time_utc=schedule_at,
        )

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        self._delegate.mark_dead_letter(job_id, error)
        self._send_dead_letter({"job_id": job_id, "error": error[:500]})

    def get_job(self, job_id: str) -> ProvisioningJob | None:
        return self._delegate.get_job(job_id)

    def _send_signal(
        self,
        payload: dict[str, Any],
        scheduled_time_utc: datetime | None = None,
    ) -> None:
        from azure.servicebus import ServiceBusMessage

        message = ServiceBusMessage(json.dumps(payload))
        with self._client.get_queue_sender(queue_name=self._queue_name) as sender:
            if scheduled_time_utc is not None:
                sender.schedule_messages(message, schedule_time_utc=scheduled_time_utc)
            else:
                sender.send_messages(message)

    def _send_dead_letter(self, payload: dict[str, Any]) -> None:
        from azure.servicebus import ServiceBusMessage

        with self._client.get_queue_sender(queue_name=self._dead_letter_queue_name) as sender:
            sender.send_messages(ServiceBusMessage(json.dumps(payload)))

    def _receive_signal(self) -> None:
        from azure.servicebus import ServiceBusReceiveMode

        with self._client.get_queue_receiver(
            queue_name=self._queue_name,
            max_wait_time=1,
            receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE,
        ) as receiver:
            receiver.receive_messages(max_message_count=1, max_wait_time=1)
