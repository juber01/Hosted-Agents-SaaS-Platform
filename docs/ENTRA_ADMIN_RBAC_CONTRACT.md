# Entra Admin RBAC Contract

This document defines how Microsoft Entra access token claims map to `/v1/admin/*` authorization checks.

## Validation configuration

- Configure JWKS validation inputs:
  - `JWT_JWKS_URL`
  - `JWT_ISSUER`
  - `JWT_AUDIENCE`
  - `JWT_JWKS_CACHE_TTL_SECONDS` (default 300s)
- `JWT_ALGORITHM` should typically be `RS256` for Entra-issued tokens.
- Shared-secret JWT mode is available as a fallback for non-production transitions.

## Token claims consumed

- `roles` or `role`:
  - App roles for application permissions or assigned service principals.
  - Parsed as a list (or comma/space-delimited string).
- `scp` or `scope`:
  - Delegated scopes.
  - Parsed as a space-delimited string (or list).
- `tenant_ids`:
  - Optional tenant scope restriction list for tenant admin principals.
- `tenant_id` or `tid`:
  - Optional single-tenant scope claim.

## Authorization model

- Endpoint access is granted if the principal has at least one required role OR at least one required scope.
- Tenant-scoped admin endpoints require tenant authorization:
  - `platform_admin` bypasses tenant scoping.
  - Otherwise token must include `tenant_ids` containing path tenant id (or `*`), or `tenant_id`/`tid` matching it.

## Endpoint policy map

- `GET /v1/admin/debug/identity`
  - roles: `platform_admin`
  - scopes: `admin.identity.read`
- `GET /v1/admin/plans`
  - roles: `platform_admin`
  - scopes: `plans.read`
- `GET /v1/admin/plans/{plan_id}`
  - roles: `platform_admin`
  - scopes: `plans.read`
- `POST /v1/admin/plans`
  - roles: `platform_admin`
  - scopes: `plans.write`
- `PATCH /v1/admin/tenants/{tenant_id}/plan`
  - roles: `platform_admin`, `tenant_admin`
  - scopes: `tenant.plan.write`
  - tenant-scoped: yes
- `GET /v1/admin/tenants/{tenant_id}/usage`
  - roles: `platform_admin`, `tenant_admin`, `billing_reader`
  - scopes: `tenant.usage.read`, `billing.read`
  - tenant-scoped: yes
- `GET /v1/admin/usage/export`
  - roles: `platform_admin`, `billing_reader`
  - scopes: `usage.export`, `billing.read`

## Example claims

Platform admin:

```json
{
  "sub": "ops-admin-1",
  "roles": ["platform_admin"]
}
```

Tenant billing reader (tenant scoped):

```json
{
  "sub": "billing-user-1",
  "roles": ["billing_reader"],
  "tenant_ids": ["tenant-123"]
}
```

Delegated scope-based caller:

```json
{
  "sub": "api-client-1",
  "scp": "plans.read tenant.usage.read",
  "tenant_ids": ["tenant-123"]
}
```
