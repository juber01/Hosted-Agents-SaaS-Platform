# Migration Map From `Hosted-Agents-SaaS-Model`

## Goal

Reuse what is already strong, avoid carrying forward single-solution coupling, and rebuild platform-critical layers cleanly.

## Copy With Minimal Changes

- `src/hosted_agents_saas/services/auth.py`
  - Keep tenant header/JWT validation patterns.
  - Refactor to use tenant user roles from catalog instead of static env maps.
- `src/hosted_agents_saas/services/rate_limit.py`
  - Keep algorithm shape, move counters to Redis for multi-instance safety.
- `src/hosted_agents_saas/services/agent_runtime.py` (selected parts only)
  - Keep adapter seams and per-agent extension registry idea.
  - Remove UK-CGT-specific conversational logic from core runtime.
- `src/hosted_agents_saas/repositories/cosmos.py` (selected query patterns)
  - Reuse tenant partitioning conventions and thread/usage item styles where relevant.

## Rewrite (Do Not Lift Directly)

- `src/hosted_agents_saas/models.py`
  - Replace with platform entities: tenants, users, plans, quotas, provisioning jobs, usage events, secret refs.
- `src/hosted_agents_saas/api/main.py`
  - Replace with control-plane-first API (tenant onboarding, plan management, provisioning, agent registry, billing exports).
- `src/hosted_agents_saas/config.py`
  - Replace env surface with platform config (Postgres, queue, Key Vault, telemetry, billing provider).
- `scripts/deploy_app_service_dev.sh`
  - Replace with infra-aware deployment split for control plane and worker services.

## Sunset (Keep Only As Historical Reference)

- UK CGT domain engine and prompts in `src/hosted_agents_saas/services/uk_cgt_calculator.py`
- Direct `/cgt/calculate` route in `src/hosted_agents_saas/api/main.py`
- Teams-specific wiring in `src/hosted_agents_saas/api/main.py`

## Migration Sequence

1. Stand up new repo core: tenant catalog schema, queue contracts, provider adapter interfaces.
2. Port auth + rate-limit primitives.
3. Implement tenant provisioning worker with idempotent steps.
4. Port Foundry runtime calls behind new adapter interface.
5. Add usage metering schema and billing export pipeline.
6. Re-add channel-specific adapters (Teams/web) as optional edge modules.

## Non-Negotiable Guardrails

- Every request must resolve and enforce `tenant_id` server-side.
- Every storage key/query must be tenant-scoped.
- Every telemetry event must include `tenant_id`, `agent_id`, `request_id`, and `plan`.
- Runtime app identity should not require resource-creation permissions in production.
