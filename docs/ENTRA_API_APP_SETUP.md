# Entra API App Setup (JWT Audience)

This platform now uses a dedicated Entra API app registration for JWT validation.

## Current values

- Tenant ID: `70f0f10f-7518-44ae-a734-bb6db401632f`
- API app display name: `hosted-agents-saas-platform-api`
- API app ID (`aud`): `58a191d5-b046-4cee-8a2f-17c82cadb15f`
- API app URI: `api://hosted-agents-saas-platform`
- Delegated scope: `access_as_user`
- Client app display name: `hosted-agents-saas-platform-client`
- Client app ID: `016c32fe-0cc7-45d8-a284-6944beb5dcf8`

## Verification commands

```bash
az ad app show --id 58a191d5-b046-4cee-8a2f-17c82cadb15f \
  --query "{appId:appId,identifierUris:identifierUris,scopeValues:api.oauth2PermissionScopes[].value}"

az ad app permission list --id 016c32fe-0cc7-45d8-a284-6944beb5dcf8

az account get-access-token \
  --scope api://hosted-agents-saas-platform/access_as_user \
  --query "{tokenType:tokenType,expiresOn:expiresOn,tenant:tenant}"
```

## Runtime alignment

- `JWT_JWKS_URL`: tenant JWKS endpoint
- `JWT_ISSUER`: tenant v2 issuer
- `JWT_AUDIENCE`: `58a191d5-b046-4cee-8a2f-17c82cadb15f`

