from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status as _OtelStatus
    from opentelemetry.trace import StatusCode as _OtelStatusCode
except ModuleNotFoundError:
    _otel_trace = None
    _OtelStatus = None
    _OtelStatusCode = None


class _NoopSpan:
    def set_attribute(self, _key: str, _value: Any) -> None:
        return

    def record_exception(self, _error: BaseException) -> None:
        return

    def set_status(self, _status: Any) -> None:
        return


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None) -> Generator[_NoopSpan | Any, None, None]:
    if _otel_trace is None:
        span = _NoopSpan()
        if attributes:
            span_set_attributes(span, attributes)
        yield span
        return

    tracer = _otel_trace.get_tracer("saas_platform")
    with tracer.start_as_current_span(name) as span:
        if attributes:
            span_set_attributes(span, attributes)
        yield span


def span_set_attributes(span: _NoopSpan | Any, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(key, value)
            continue
        span.set_attribute(key, str(value))


def span_record_error(span: _NoopSpan | Any, error: Exception, failure_type: str) -> None:
    span.set_attribute("failure_type", failure_type)
    span.record_exception(error)
    if _OtelStatus is not None and _OtelStatusCode is not None:
        span.set_status(_OtelStatus(_OtelStatusCode.ERROR, str(error)))


def telemetry_tags(
    *,
    tenant_id: str | None = None,
    agent_id: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    plan: str | None = None,
    model: str | None = None,
    environment: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_estimate: float | None = None,
    latency_ms: int | None = None,
    failure_type: str | None = None,
) -> dict[str, str | int | float]:
    tags: dict[str, str | int | float] = {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "request_id": request_id,
        "job_id": job_id,
        "plan": plan,
        "model": model,
        "environment": environment,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_estimate": cost_estimate,
        "latency_ms": latency_ms,
        "failure_type": failure_type,
    }
    return {key: value for key, value in tags.items() if value is not None}
