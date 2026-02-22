from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Tenant(BaseModel):
    tenant_id: str
    name: str
    plan: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TenantConfig(BaseModel):
    tenant_id: str
    config_version: int = 1
    default_agent_template: str = "general-assistant"
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class ProvisioningJob(BaseModel):
    job_id: str
    tenant_id: str
    step: str
    state: str = "queued"
    retries: int = 0
    error: str | None = None


class UsageEvent(BaseModel):
    tenant_id: str
    agent_id: str
    request_id: str
    model: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_estimate: float


class CreateTenantRequest(BaseModel):
    name: str
    plan: str


class CreateTenantResponse(BaseModel):
    tenant_id: str
    status: str
    provisioning_job_id: str


class ExecuteRunRequest(BaseModel):
    agent_id: str
    user_id: str
    message: str


class ExecuteRunResponse(BaseModel):
    tenant_id: str
    request_id: str
    output_text: str
