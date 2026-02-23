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
- For queue backends, prefer MI endpoints:
  - Storage Queue: `AZURE_STORAGE_QUEUE_ACCOUNT_URL`
  - Service Bus: `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE`
- Use queue connection strings only for temporary non-production fallback with `ALLOW_API_KEY_FALLBACK=true`.

## Admin API authorization

- `/v1/admin/*` endpoints require JWT bearer authentication.
- Authorization uses Entra-style role/scope claims mapped to endpoint permissions.
- Token validation should use Entra JWKS (`JWT_JWKS_URL`, `JWT_ISSUER`, `JWT_AUDIENCE`) in production.
- Use the explicit contract in:
  - `docs/ENTRA_ADMIN_RBAC_CONTRACT.md`

## IaC role definitions used

These are the RBAC role definition IDs referenced by the deployment template (`infra/azure/containerapps/main.bicep`):

- `Storage Queue Data Contributor`
  - role definition id: `974c5e8b-45b9-4653-ba55-5f855dd0fb88`
- `AcrPull`
  - role definition id: `7f951dda-4ed3-4680-a7ca-43fe172d538d`
- `Key Vault Secrets User`
  - role definition id: `4633458b-17de-408a-b874-0445c86b69e6`
- Optional Service Bus role
  - parameter: `serviceBusRoleDefinitionId`
  - applied only if `serviceBusEnabled=true` and a role ID is supplied

## Applied role assignments (current environment)

As of February 23, 2026 in Azure:

- Subscription: `2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d`
- Platform resource group: `rg-hosted-agents-saas-platform`
- Foundry scope resource group: `rg-juber-2589`

### Managed identity: `saasplat-api-mi`

- Principal id: `72cfd0f0-577f-4a1d-852d-fa8ddafcf43f`
- `AcrPull`
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourcegroups/rg-hosted-agents-saas-platform/providers/Microsoft.ContainerRegistry/registries/saasplatacr260222`
- `Storage Queue Data Contributor`
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourcegroups/rg-hosted-agents-saas-platform/providers/Microsoft.Storage/storageAccounts/saasplatst7k3iqmrvaiazy`
- `Key Vault Secrets User`
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourcegroups/rg-hosted-agents-saas-platform/providers/Microsoft.KeyVault/vaults/saasplatkv7k3iqmrvaiazy`
- `Azure AI User` (manually added for Foundry MI hosted-agent access)
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourceGroups/rg-juber-2589/providers/Microsoft.CognitiveServices/accounts/juber-2589-resource`
  - role assignment id: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourceGroups/rg-juber-2589/providers/Microsoft.CognitiveServices/accounts/juber-2589-resource/providers/Microsoft.Authorization/roleAssignments/4309488d-873d-4138-a866-27f7fa616278`

### Managed identity: `saasplat-worker-mi`

- Principal id: `5ffd6f07-326f-4f82-8ca6-5b274bab2f54`
- `AcrPull`
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourcegroups/rg-hosted-agents-saas-platform/providers/Microsoft.ContainerRegistry/registries/saasplatacr260222`
- `Storage Queue Data Contributor`
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourcegroups/rg-hosted-agents-saas-platform/providers/Microsoft.Storage/storageAccounts/saasplatst7k3iqmrvaiazy`
- `Key Vault Secrets User`
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourcegroups/rg-hosted-agents-saas-platform/providers/Microsoft.KeyVault/vaults/saasplatkv7k3iqmrvaiazy`
- `Azure AI User` (manually added for parity)
  - scope: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourceGroups/rg-juber-2589/providers/Microsoft.CognitiveServices/accounts/juber-2589-resource`
  - role assignment id: `/subscriptions/2ca5d3f8-241d-4ab9-a10c-24d1a9c6751d/resourceGroups/rg-juber-2589/providers/Microsoft.CognitiveServices/accounts/juber-2589-resource/providers/Microsoft.Authorization/roleAssignments/e3b2f2f8-041d-44b5-a0b5-9c9d4b4ae311`

## Current auth state (runtime)

- Managed identity is enabled:
  - `AZURE_USE_MANAGED_IDENTITY=true`
- API key fallback is disabled:
  - `ALLOW_API_KEY_FALLBACK=false`
- Foundry API key env/secret was removed from deployed apps.
