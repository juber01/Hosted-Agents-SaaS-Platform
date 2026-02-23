from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Lock
import time
from typing import Any
from urllib import request

from fastapi import Header, HTTPException
import jwt

from saas_platform.config import Settings


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    customer_user_id: str


@dataclass(frozen=True)
class AdminPrincipal:
    subject: str
    roles: frozenset[str]
    scopes: frozenset[str]
    tenant_ids: frozenset[str]

    @property
    def is_platform_admin(self) -> bool:
        return "platform_admin" in self.roles

    def can_access_tenant(self, tenant_id: str) -> bool:
        return self.is_platform_admin or "*" in self.tenant_ids or tenant_id in self.tenant_ids


_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE_LOCK = Lock()


class TenantAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authenticate(
        self,
        path_tenant_id: str,
        x_tenant_id: str,
        x_customer_user_id: str,
        x_api_key: str,
        authorization: str,
    ) -> TenantContext:
        if not x_tenant_id or not x_customer_user_id:
            raise HTTPException(status_code=400, detail="X-Tenant-Id and X-Customer-User-Id are required")
        if path_tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="Path tenant_id does not match header tenant")

        auth_configured = bool(self.settings.tenant_api_keys) or bool(self.settings.jwt_shared_secret) or _is_jwks_enabled(
            self.settings
        )
        if auth_configured:
            if self._is_valid_api_key(tenant_id=x_tenant_id, api_key=x_api_key):
                return TenantContext(tenant_id=x_tenant_id, customer_user_id=x_customer_user_id)
            jwt_subject = self._get_valid_jwt_subject(tenant_id=x_tenant_id, authorization=authorization)
            if jwt_subject:
                if jwt_subject != x_customer_user_id:
                    raise HTTPException(status_code=403, detail="X-Customer-User-Id must match token subject")
                return TenantContext(tenant_id=x_tenant_id, customer_user_id=jwt_subject)
            raise HTTPException(status_code=401, detail="Unauthorized tenant credentials")

        if self.settings.app_env.strip().lower() in {"prod", "production"}:
            raise HTTPException(status_code=500, detail="Tenant authentication is not configured")

        return TenantContext(tenant_id=x_tenant_id, customer_user_id=x_customer_user_id)

    def _is_valid_api_key(self, tenant_id: str, api_key: str) -> bool:
        expected = self.settings.tenant_api_keys.get(tenant_id)
        return bool(expected and api_key and api_key == expected)

    def _get_valid_jwt_subject(self, tenant_id: str, authorization: str) -> str | None:
        try:
            payload = _decode_bearer_jwt(settings=self.settings, authorization=authorization)
            claim_tenant = str(payload.get("tenant_id") or payload.get("tid") or "")
            if claim_tenant != tenant_id:
                return None
            claim_subject = str(payload.get("oid") or payload.get("sub") or payload.get("upn") or "").strip()
            return claim_subject or None
        except Exception:
            return None


class AdminAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authenticate(self, authorization: str) -> AdminPrincipal:
        claims = _decode_bearer_jwt(settings=self.settings, authorization=authorization)
        subject = str(claims.get("sub") or claims.get("oid") or claims.get("upn") or "unknown")
        roles = _extract_string_set(claims.get("roles")) | _extract_string_set(claims.get("role"))
        scopes = _extract_scopes(claims)
        tenant_ids = _extract_tenant_ids(claims)
        return AdminPrincipal(
            subject=subject,
            roles=frozenset(roles),
            scopes=frozenset(scopes),
            tenant_ids=frozenset(tenant_ids),
        )

    def authorize(
        self,
        principal: AdminPrincipal,
        required_roles: set[str] | None = None,
        required_scopes: set[str] | None = None,
        tenant_id: str | None = None,
    ) -> None:
        role_ok = bool(required_roles and principal.roles.intersection(required_roles))
        scope_ok = bool(required_scopes and principal.scopes.intersection(required_scopes))
        if (required_roles or required_scopes) and not (role_ok or scope_ok):
            raise HTTPException(status_code=403, detail="Admin principal lacks required role or scope")

        if tenant_id and not principal.can_access_tenant(tenant_id):
            raise HTTPException(status_code=403, detail="Admin principal is not authorized for this tenant")


def _decode_bearer_jwt(settings: Settings, authorization: str) -> dict[str, Any]:
    token = _extract_bearer_token(authorization)

    if _is_jwks_enabled(settings):
        return _decode_bearer_jwt_with_jwks(settings=settings, token=token)

    if settings.jwt_shared_secret:
        return _decode_bearer_jwt_with_shared_secret(settings=settings, token=token)

    raise HTTPException(
        status_code=500,
        detail="JWT auth is not configured. Set JWKS config or JWT_SHARED_SECRET.",
    )


def _extract_bearer_token(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


def _decode_bearer_jwt_with_shared_secret(settings: Settings, token: str) -> dict[str, Any]:
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_shared_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return claims
    except Exception as err:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from err


def _decode_bearer_jwt_with_jwks(settings: Settings, token: str) -> dict[str, Any]:
    jwks_url = settings.jwt_jwks_url.strip()
    issuer = settings.jwt_issuer.strip()
    audience = settings.jwt_audience.strip()
    if not (jwks_url and issuer and audience):
        raise HTTPException(
            status_code=500,
            detail="JWT_JWKS_URL, JWT_ISSUER, and JWT_AUDIENCE must all be configured for JWKS auth",
        )

    try:
        signing_key = _resolve_jwks_signing_key(
            token=token,
            jwks_url=jwks_url,
            cache_ttl_seconds=max(settings.jwt_jwks_cache_ttl_seconds, 0),
        )
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=[settings.jwt_algorithm],
            audience=audience,
            issuer=issuer,
        )
        return claims
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from err


def _resolve_jwks_signing_key(token: str, jwks_url: str, cache_ttl_seconds: int) -> Any:
    try:
        headers = jwt.get_unverified_header(token)
    except Exception as err:
        raise HTTPException(status_code=401, detail="Invalid bearer token header") from err

    kid = str(headers.get("kid") or "").strip()
    if not kid:
        raise HTTPException(status_code=401, detail="Invalid bearer token header")

    jwks_payload = _get_jwks_payload(jwks_url=jwks_url, cache_ttl_seconds=cache_ttl_seconds)
    keys = jwks_payload.get("keys")
    if not isinstance(keys, list):
        raise HTTPException(status_code=401, detail="Invalid JWKS payload")

    for entry in keys:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kid") or "") != kid:
            continue
        try:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(entry))
        except Exception as err:
            raise HTTPException(status_code=401, detail="Invalid JWKS signing key") from err

    raise HTTPException(status_code=401, detail="Signing key not found in JWKS")


def _get_jwks_payload(jwks_url: str, cache_ttl_seconds: int) -> dict[str, Any]:
    now = time.time()
    with _JWKS_CACHE_LOCK:
        cached = _JWKS_CACHE.get(jwks_url)
        if cached and cached[0] > now:
            return cached[1]

    try:
        with request.urlopen(jwks_url, timeout=5) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JWKS payload must be an object")
    except Exception as err:
        raise HTTPException(status_code=401, detail="Unable to load JWKS") from err

    expires_at = now + max(cache_ttl_seconds, 0)
    with _JWKS_CACHE_LOCK:
        _JWKS_CACHE[jwks_url] = (expires_at, payload)
    return payload


def _is_jwks_enabled(settings: Settings) -> bool:
    return bool(
        settings.jwt_jwks_url.strip()
        or settings.jwt_issuer.strip()
        or settings.jwt_audience.strip()
    )


def _extract_scopes(claims: dict[str, Any]) -> set[str]:
    scopes = set()
    for key in ("scp", "scope"):
        value = claims.get(key)
        if isinstance(value, str):
            scopes.update(part.strip() for part in value.split(" ") if part.strip())
        elif isinstance(value, list):
            scopes.update(str(item).strip() for item in value if str(item).strip())
    return scopes


def _extract_tenant_ids(claims: dict[str, Any]) -> set[str]:
    tenant_ids = set()
    tenant_ids.update(_extract_string_set(claims.get("tenant_ids")))
    direct = str(claims.get("tenant_id") or claims.get("tid") or "").strip()
    if direct:
        tenant_ids.add(direct)
    return tenant_ids


def _extract_string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        normalized = value.replace(",", " ")
        parts = [part.strip() for part in normalized.split(" ")]
        return {part for part in parts if part}
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def tenant_headers(
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_customer_user_id: str = Header(..., alias="X-Customer-User-Id"),
    x_api_key: str = Header(default="", alias="X-Api-Key"),
    authorization: str = Header(default="", alias="Authorization"),
) -> tuple[str, str, str, str]:
    return x_tenant_id, x_customer_user_id, x_api_key, authorization
