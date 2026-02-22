from __future__ import annotations


def telemetry_tags(
    *,
    tenant_id: str,
    agent_id: str,
    request_id: str,
    plan: str,
    model: str,
    environment: str,
) -> dict[str, str]:
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "request_id": request_id,
        "plan": plan,
        "model": model,
        "environment": environment,
    }
