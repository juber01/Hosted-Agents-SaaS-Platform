# Azure Container Apps Deployment

This folder contains step `#1` infrastructure scaffolding for split deployment:

- API service: `prefix-api`
- Provisioning worker service: `prefix-worker`
- Managed identities (UAMI) for API and worker
- Key Vault (RBAC mode)
- Postgres flexible server + app DB
- Azure Managed Redis cache for distributed rate limiting
- Storage queue resources for provisioning signals
- Optional Service Bus namespace/queues
- Container Apps environment + Log Analytics + Application Insights

## Prerequisites

- Azure CLI logged in (`az login`)
- Target resource group exists (or create one)
- A container image pushed to ACR (or other registry)
- Entra app registration set up for admin JWT issuer/audience/JWKS

## 1) Build and push image

From repo root:

```bash
az acr build \
  --registry <acrName> \
  --image saas-platform:<tag> \
  .
```

## 2) Prepare parameters

Copy and edit:

```bash
cp infra/azure/containerapps/main.parameters.example.json \
   infra/azure/containerapps/main.parameters.json
```

Update at minimum:

- `prefix`
- `location`
- `containerImage`
- `containerRegistryName`
- `jwtJwksUrl`
- `jwtIssuer`
- `jwtAudience`
  - Use the Entra API app registration `appId` GUID (the value that appears in bearer token `aud`).
- `postgresAdminUser`
- `postgresAdminPassword`

## 3) Deploy infrastructure

```bash
az deployment group create \
  --resource-group <rgName> \
  --template-file infra/azure/containerapps/main.bicep \
  --parameters @infra/azure/containerapps/main.parameters.json \
  --parameters postgresAdminPassword='<strong-password>'
```

The deployment outputs include API URL, identity principal IDs, and key service names.

## 4) Run database migrations

After the API app is up, run Alembic once inside the API container:

```bash
az containerapp exec \
  --resource-group <rgName> \
  --name <prefix>-api \
  --command "python -m alembic upgrade head"
```

## 5) Validate deployment

```bash
curl -sS https://<api-fqdn>/health
```

Expected response:

```json
{"status":"ok"}
```

## Notes

- Managed identity + RBAC is used where supported by adapters (`Storage Queue`, `Service Bus`, `Key Vault`, `Foundry`).
- `allowApiKeyFallback` should stay `false` in production.
- Redis guidance:
  - Start with `redisManagedSkuName=MemoryOptimized_M10` for SMB session/app cache workloads.
  - If Redis deployment is intentionally disabled (`redisEnabled=false`), the app falls back to in-memory rate limiting.
- `queueBackend` options:
  - `database`
  - `storage_queue` (default)
  - `service_bus` (set `serviceBusEnabled=true` and provide a Service Bus role definition id if needed)
- Postgres connectivity in this phase is password DSN based (`TENANT_CATALOG_DSN`).
