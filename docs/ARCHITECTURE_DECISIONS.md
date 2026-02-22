# Architecture Decisions

## ADR-001: Greenfield repo instead of in-place rewrite

Decision:
Create a new platform-first repository for multitenant SaaS control plane and execution routing.

Reason:
The current repo is a proven runtime slice but is optimized around a specific bot flow and deployment path.
A clean repository reduces migration risk and lets tenant lifecycle, quotas, provisioning, and billing drive design.

## ADR-002: Shared control plane and shared execution pool as default

Decision:
Start with shared control plane + shared worker/runtime and enforce strict logical tenant isolation.

Reason:
This aligns cost/performance with SMB constraints and keeps an upgrade path to dedicated tiers.

## ADR-003: Provider adapters are hard boundaries

Decision:
Foundry, storage, and secret systems are integrated through adapter interfaces only.

Reason:
This prevents route handlers from becoming provider-specific and makes tier migrations simpler.
