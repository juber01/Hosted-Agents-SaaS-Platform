# Hosted Agents SaaS Platform (Greenfield)

This is a clean-slate repo scaffold for the SMB multitenant architecture.

## What this repo is for

- Shared control plane for tenant onboarding, config, and policy
- Shared execution gateway for tenant-aware agent runs
- Queue-driven provisioning worker
- Tenant-scoped usage metering and quota enforcement
- Pluggable adapters for Foundry, storage, and secrets

## Identity and access default

- Managed identity + RBAC is the default for Azure service access.
- API key auth is disabled by default (`ALLOW_API_KEY_FALLBACK=false`) and should only be enabled temporarily in non-production environments.
- Production policy in the Foundry adapter requires managed identity.
- `/v1/admin/*` endpoints require JWT bearer auth; anonymous admin access is blocked.

## Layout

- `src/saas_platform/api`: FastAPI control-plane surface
- `src/saas_platform/domain`: core entities and interfaces
- `src/saas_platform/policies`: quota/rate/auth policy logic
- `src/saas_platform/adapters`: provider and persistence adapters
- `src/saas_platform/provisioning`: async provisioning workflow
- `docs`: migration map and architecture decisions

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn saas_platform.api.main:app --app-dir src --reload --port 8080
```

Run provisioning worker (separate process):

```bash
saas-platform-worker
```

Process a single job and exit:

```bash
saas-platform-worker --once
```

## Azure deployment (step 1)

- Split API and worker deployment scaffolding is in `infra/azure/containerapps/main.bicep`.
- This template deploys Container Apps + UAMI identities, Key Vault (RBAC mode), Postgres, Redis, Storage Queue, and optional Service Bus.
- Use `infra/azure/containerapps/main.parameters.example.json` as your starting parameter file.
- Deployment runbook:
  - `infra/azure/containerapps/README.md`

## Cost estimate

Estimate daily/monthly run-rate from live Azure resource configuration and current retail prices:

```bash
./scripts/estimate_cost.py --resource-group rg-hosted-agents-saas-platform
```

## Endpoints

- `GET /health`
- `GET /v1/admin/debug/identity`
- `GET /v1/admin/plans`
- `GET /v1/admin/plans/{plan_id}`
- `POST /v1/admin/plans`
- `PATCH /v1/admin/tenants/{tenant_id}/plan`
- `GET /v1/admin/tenants/{tenant_id}/usage`
- `GET /v1/admin/usage/export`
- `POST /v1/tenants`
- `GET /v1/tenants/{tenant_id}`
- `POST /v1/provisioning/jobs/run-next` (debug/local fallback)
- `POST /v1/tenants/{tenant_id}/runs`

## Phase 1 notes

- If `TENANT_CATALOG_DSN` is set, the app uses Postgres-backed tenant catalog, provisioning queue, and usage metering.
- If `TENANT_CATALOG_DSN` is empty, in-memory adapters are used for local development.
- Postgres runtime does not create schema objects at startup; run `alembic upgrade head` before starting services.
- Postgres client pool defaults are tuned for low-tier SMB databases:
  - `POSTGRES_POOL_SIZE=3`
  - `POSTGRES_MAX_OVERFLOW=0`
  - `POSTGRES_POOL_TIMEOUT_SECONDS=10`
  - `POSTGRES_POOL_RECYCLE_SECONDS=900`
- Foundry execution:
  - Set `AZURE_AI_PROJECT_ENDPOINT` to enable live hosted-agent execution.
  - `POST /v1/tenants/{tenant_id}/runs` uses `agent_id` as the Foundry agent id.
  - `FOUNDRY_RUN_POLL_INTERVAL_SECONDS` controls run polling interval.
- Run execution is enforced by plan quotas (monthly messages and monthly token cap).
- Provisioning jobs support idempotency keys, retry backoff, and dead-letter state.
- `PROVISIONING_QUEUE_BACKEND=database` uses only Postgres/in-memory queue state.
- `PROVISIONING_QUEUE_BACKEND=storage_queue` wraps the base queue with Azure Storage Queue signaling:
  - MI/RBAC path: set `AZURE_STORAGE_QUEUE_ACCOUNT_URL` and keep `AZURE_USE_MANAGED_IDENTITY=true`.
  - Connection-string path: set `AZURE_STORAGE_QUEUE_CONNECTION_STRING` and `ALLOW_API_KEY_FALLBACK=true`.
- `PROVISIONING_QUEUE_BACKEND=service_bus` wraps the base queue with Azure Service Bus signaling:
  - MI/RBAC path: set `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE` and keep `AZURE_USE_MANAGED_IDENTITY=true`.
  - Connection-string path: set `AZURE_SERVICE_BUS_CONNECTION_STRING` and `ALLOW_API_KEY_FALLBACK=true`.
- Rate limiting backend:
  - `RATE_LIMIT_BACKEND=memory` keeps per-instance in-memory limiting.
  - `RATE_LIMIT_BACKEND=redis` enables distributed fixed-window limiting via `RATE_LIMIT_REDIS_URL`.
  - `RATE_LIMIT_REDIS_FAIL_OPEN=true` allows requests if Redis is unavailable (availability-first mode).

## Admin auth and RBAC

- Admin/tenant bearer JWT validation is JWKS-based when configured:
  - `JWT_JWKS_URL`, `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_JWKS_CACHE_TTL_SECONDS`
- Shared-secret JWT validation (`JWT_SHARED_SECRET`) is supported as a fallback for non-production transitions.
- `JWT_ALGORITHM` should align with your token mode (`RS256` for Entra JWKS, `HS256` for shared-secret fallback).
- Role claims can be supplied in `roles` (list) or `role`.
- Scope claims can be supplied in `scp` or `scope`.
- Tenant-scoped admin actions require tenant access via one of:
  - `roles` includes `platform_admin` (global bypass)
  - `tenant_ids` contains the path tenant id (or `*`)
  - `tenant_id`/`tid` matches the path tenant id
- Full Entra mapping contract:
  - `docs/ENTRA_ADMIN_RBAC_CONTRACT.md`

## Observability

- API and worker paths emit OpenTelemetry spans when an OTel tracer provider/exporter is configured.
- Shared attributes include tenant, agent, plan, request/job ids, latency, token counts, cost estimate, and failure type.
- Worker retry/dead-letter transitions emit structured JSON log events for operational triage.
