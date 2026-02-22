# Hosted Agents SaaS Platform (Greenfield)

This is a clean-slate repo scaffold for the SMB multitenant architecture.

## What this repo is for

- Shared control plane for tenant onboarding, config, and policy
- Shared execution gateway for tenant-aware agent runs
- Queue-driven provisioning worker
- Tenant-scoped usage metering and quota enforcement
- Pluggable adapters for Foundry, storage, and secrets

## What this repo is not

- It is not a direct continuation of the current UK-CGT-focused runtime.
- Domain-specific flows (like UK CGT) should be implemented as tenant agent extensions later.

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
- `POST /v1/tenants`
- `GET /v1/tenants/{tenant_id}`
- `POST /v1/provisioning/jobs/run-next`
- `POST /v1/tenants/{tenant_id}/runs`

## Phase 1 notes

- If `TENANT_CATALOG_DSN` is set, the app uses Postgres-backed tenant catalog, provisioning queue, and usage metering.
- If `TENANT_CATALOG_DSN` is empty, in-memory adapters are used for local development.
- Use Alembic to manage schema changes in real environments.
