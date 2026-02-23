# Entitlement Rollout (Wildcard to Explicit)

This runbook migrates customer access from wildcard grants (`customer_user_id='*'`) to explicit per-customer grants.

## 1) Audit current state

```bash
./.venv/bin/python -m saas_platform.ops.entitlement_rollout \
  --dsn "$TENANT_CATALOG_DSN" \
  audit
```

## 2) Export mapping template

```bash
./.venv/bin/python -m saas_platform.ops.entitlement_rollout \
  --dsn "$TENANT_CATALOG_DSN" \
  export-template \
  --output /tmp/entitlement_mapping.csv
```

Fill `customer_user_id` for each tenant+agent row in the CSV.

CSV columns:
- `tenant_id`
- `agent_id`
- `customer_user_id`

## 3) Dry-run apply

```bash
./.venv/bin/python -m saas_platform.ops.entitlement_rollout \
  --dsn "$TENANT_CATALOG_DSN" \
  apply \
  --mapping-file /tmp/entitlement_mapping.csv \
  --drop-wildcards \
  --dry-run
```

## 4) Apply explicit grants and drop matching wildcards

```bash
./.venv/bin/python -m saas_platform.ops.entitlement_rollout \
  --dsn "$TENANT_CATALOG_DSN" \
  apply \
  --mapping-file /tmp/entitlement_mapping.csv \
  --drop-wildcards
```

This only drops wildcard rows for tenant+agent pairs present in the mapping file.
