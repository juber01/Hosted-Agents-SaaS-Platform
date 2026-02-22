# Azure Identity and RBAC Baseline

## Policy

- Use managed identity for service-to-service authentication by default.
- Use Azure RBAC roles instead of storing long-lived service keys in application settings.
- Allow API-key fallback only when explicitly enabled and only for non-production transitions.

## Recommended role assignments

Assign these to the app and worker managed identities (least privilege):

- Foundry/AI project access:
  - role with permission to invoke agent/project runtime in your Foundry project scope
- Key Vault:
  - `Key Vault Secrets User` for read-only runtime access
  - `Key Vault Secrets Officer` only where write/update of tenant secrets is required
- Queue backend:
  - `Storage Queue Data Contributor` (if using Storage Queue)
  - equivalent Service Bus data role (if using Service Bus)
- Storage/knowledge artifacts (if used):
  - `Storage Blob Data Contributor` for tenant-scoped paths

## Operational guardrails

- Keep `AZURE_USE_MANAGED_IDENTITY=true` in all environments.
- Keep `ALLOW_API_KEY_FALLBACK=false` in production.
- Scope RBAC assignments to the minimal resource scope needed.
- Audit all role assignments and admin changes.
