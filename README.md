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
- `POST /v1/provisioning/jobs/run-next`
- `POST /v1/tenants/{tenant_id}/runs`

## Phase 1 notes

- If `TENANT_CATALOG_DSN` is set, the app uses Postgres-backed tenant catalog, provisioning queue, and usage metering.
- If `TENANT_CATALOG_DSN` is empty, in-memory adapters are used for local development.
- Postgres runtime does not create schema objects at startup; run `alembic upgrade head` before starting services.
- Run execution is enforced by plan quotas (monthly messages and monthly token cap).

## Admin auth and RBAC

- Admin JWT validation uses `JWT_SHARED_SECRET` and `JWT_ALGORITHM`.
- Role claims can be supplied in `roles` (list) or `role`.
- Scope claims can be supplied in `scp` or `scope`.
- Tenant-scoped admin actions require tenant access via one of:
  - `roles` includes `platform_admin` (global bypass)
  - `tenant_ids` contains the path tenant id (or `*`)
  - `tenant_id`/`tid` matches the path tenant id
