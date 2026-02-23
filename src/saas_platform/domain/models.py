from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Tenant(BaseModel):
    tenant_id: str
    name: str
    plan: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TenantAgent(BaseModel):
    tenant_id: str
    agent_id: str
    display_name: str
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CustomerAgentEntitlement(BaseModel):
    tenant_id: str
    customer_id: str
    agent_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanLimits(BaseModel):
    monthly_messages: int
    monthly_token_cap: int
    max_agents: int


class Plan(BaseModel):
    plan_id: str
    display_name: str
    limits: PlanLimits
    active: bool = True
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
    idempotency_key: str | None = None
    state: str = "queued"
    retries: int = 0
    max_attempts: int = 3
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    available_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UsageEvent(BaseModel):
    tenant_id: str
    agent_id: str
    request_id: str
    model: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_estimate: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TenantUsageSummary(BaseModel):
    tenant_id: str
    month: str
    messages_used: int
    tokens_used: int
    cost_estimate: float


class TenantBillingRecord(BaseModel):
    tenant_id: str
    month: str
    messages_used: int
    tokens_used: int
    cost_estimate: float


class CreateTenantRequest(BaseModel):
    name: str
    plan: str


class CreateTenantResponse(BaseModel):
    tenant_id: str
    status: str
    provisioning_job_id: str


class CreatePlanRequest(BaseModel):
    plan_id: str
    display_name: str
    monthly_messages: int
    monthly_token_cap: int
    max_agents: int
    active: bool = True


class UpdateTenantPlanRequest(BaseModel):
    plan_id: str


class UpsertTenantAgentRequest(BaseModel):
    agent_id: str
    display_name: str
    active: bool = True


class ExecuteRunRequest(BaseModel):
    agent_id: str
    user_id: str
    message: str


class ExecuteRunResponse(BaseModel):
    tenant_id: str
    request_id: str
    output_text: str
