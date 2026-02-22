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
    azure_ai_project_endpoint: str
    azure_ai_project_api_key: str
    azure_use_managed_identity: bool
    azure_managed_identity_client_id: str
    allow_api_key_fallback: bool
    key_vault_url: str
    tenant_api_keys: dict[str, str]
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
        azure_ai_project_endpoint=os.getenv("AZURE_AI_PROJECT_ENDPOINT", ""),
        azure_ai_project_api_key=os.getenv("AZURE_AI_PROJECT_API_KEY", ""),
        azure_use_managed_identity=_parse_bool(os.getenv("AZURE_USE_MANAGED_IDENTITY", "true"), default=True),
        azure_managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID", ""),
        allow_api_key_fallback=_parse_bool(os.getenv("ALLOW_API_KEY_FALLBACK", "false"), default=False),
        key_vault_url=os.getenv("KEY_VAULT_URL", ""),
        tenant_api_keys=_parse_tenant_api_keys(os.getenv("TENANT_API_KEYS_JSON", "")),
        jwt_shared_secret=os.getenv("JWT_SHARED_SECRET", ""),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        default_rate_limit_rpm=int(os.getenv("DEFAULT_RATE_LIMIT_RPM", "60")),
    )
