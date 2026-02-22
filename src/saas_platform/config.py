from __future__ import annotations

from dataclasses import dataclass
import ast
import json
import os

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    app_env: str
    tenant_catalog_dsn: str
    provisioning_queue_backend: str
    provisioning_worker_poll_seconds: int
    provisioning_job_max_attempts: int
    provisioning_retry_base_seconds: int
    azure_storage_queue_account_url: str
    azure_storage_queue_connection_string: str
    azure_storage_queue_name: str
    azure_storage_queue_dead_letter_queue_name: str
    azure_service_bus_fully_qualified_namespace: str
    azure_service_bus_connection_string: str
    azure_service_bus_queue_name: str
    azure_service_bus_dead_letter_queue_name: str
    azure_ai_project_endpoint: str
    azure_ai_project_api_key: str
    azure_use_managed_identity: bool
    azure_managed_identity_client_id: str
    allow_api_key_fallback: bool
    key_vault_url: str
    tenant_api_keys: dict[str, str]
    rate_limit_backend: str
    rate_limit_redis_url: str
    rate_limit_redis_key_prefix: str
    rate_limit_redis_fail_open: bool
    jwt_jwks_url: str
    jwt_issuer: str
    jwt_audience: str
    jwt_jwks_cache_ttl_seconds: int
    jwt_shared_secret: str
    jwt_algorithm: str
    default_rate_limit_rpm: int


def _parse_tenant_api_keys(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()

    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("TENANT_API_KEYS_JSON must be a JSON object")
        return {str(k): str(v) for k, v in payload.items() if str(v)}
    except json.JSONDecodeError:
        pass

    try:
        literal = ast.literal_eval(text)
        if isinstance(literal, dict):
            return {str(k): str(v) for k, v in literal.items() if str(v)}
    except Exception:
        pass

    raise ValueError("Invalid TENANT_API_KEYS_JSON")


def _parse_bool(raw: str, default: bool) -> bool:
    text = (raw or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on"}


def get_settings() -> Settings:
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    return Settings(
        app_env=os.getenv("APP_ENV", "dev"),
        tenant_catalog_dsn=os.getenv("TENANT_CATALOG_DSN", ""),
        provisioning_queue_backend=os.getenv("PROVISIONING_QUEUE_BACKEND", "storage_queue"),
        provisioning_worker_poll_seconds=int(os.getenv("PROVISIONING_WORKER_POLL_SECONDS", "2")),
        provisioning_job_max_attempts=int(os.getenv("PROVISIONING_JOB_MAX_ATTEMPTS", "3")),
        provisioning_retry_base_seconds=int(os.getenv("PROVISIONING_RETRY_BASE_SECONDS", "5")),
        azure_storage_queue_account_url=os.getenv("AZURE_STORAGE_QUEUE_ACCOUNT_URL", ""),
        azure_storage_queue_connection_string=os.getenv("AZURE_STORAGE_QUEUE_CONNECTION_STRING", ""),
        azure_storage_queue_name=os.getenv("AZURE_STORAGE_QUEUE_NAME", "provisioning-jobs"),
        azure_storage_queue_dead_letter_queue_name=os.getenv(
            "AZURE_STORAGE_QUEUE_DEAD_LETTER_QUEUE_NAME", "provisioning-jobs-deadletter"
        ),
        azure_service_bus_fully_qualified_namespace=os.getenv("AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE", ""),
        azure_service_bus_connection_string=os.getenv("AZURE_SERVICE_BUS_CONNECTION_STRING", ""),
        azure_service_bus_queue_name=os.getenv("AZURE_SERVICE_BUS_QUEUE_NAME", "provisioning-jobs"),
        azure_service_bus_dead_letter_queue_name=os.getenv(
            "AZURE_SERVICE_BUS_DEAD_LETTER_QUEUE_NAME", "provisioning-jobs-deadletter"
        ),
        azure_ai_project_endpoint=os.getenv("AZURE_AI_PROJECT_ENDPOINT", ""),
        azure_ai_project_api_key=os.getenv("AZURE_AI_PROJECT_API_KEY", ""),
        azure_use_managed_identity=_parse_bool(os.getenv("AZURE_USE_MANAGED_IDENTITY", "true"), default=True),
        azure_managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID", ""),
        allow_api_key_fallback=_parse_bool(os.getenv("ALLOW_API_KEY_FALLBACK", "false"), default=False),
        key_vault_url=os.getenv("KEY_VAULT_URL", ""),
        tenant_api_keys=_parse_tenant_api_keys(os.getenv("TENANT_API_KEYS_JSON", "")),
        rate_limit_backend=os.getenv("RATE_LIMIT_BACKEND", "memory"),
        rate_limit_redis_url=os.getenv("RATE_LIMIT_REDIS_URL", ""),
        rate_limit_redis_key_prefix=os.getenv("RATE_LIMIT_REDIS_KEY_PREFIX", "saas:ratelimit"),
        rate_limit_redis_fail_open=_parse_bool(os.getenv("RATE_LIMIT_REDIS_FAIL_OPEN", "true"), default=True),
        jwt_jwks_url=os.getenv("JWT_JWKS_URL", ""),
        jwt_issuer=os.getenv("JWT_ISSUER", ""),
        jwt_audience=os.getenv("JWT_AUDIENCE", ""),
        jwt_jwks_cache_ttl_seconds=int(os.getenv("JWT_JWKS_CACHE_TTL_SECONDS", "300")),
        jwt_shared_secret=os.getenv("JWT_SHARED_SECRET", ""),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        default_rate_limit_rpm=int(os.getenv("DEFAULT_RATE_LIMIT_RPM", "60")),
    )
