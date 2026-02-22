from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException
import jwt

from saas_platform.config import Settings


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    customer_id: str


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


class TenantAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authenticate(
        self,
        path_tenant_id: str,
        x_tenant_id: str,
        x_customer_id: str,
        x_api_key: str,
        authorization: str,
    ) -> TenantContext:
        if not x_tenant_id or not x_customer_id:
            raise HTTPException(status_code=400, detail="X-Tenant-Id and X-Customer-Id are required")
        if path_tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="Path tenant_id does not match header tenant")

        if self.settings.tenant_api_keys or self.settings.jwt_shared_secret:
            if self._is_valid_api_key(tenant_id=x_tenant_id, api_key=x_api_key):
                return TenantContext(tenant_id=x_tenant_id, customer_id=x_customer_id)
            if self._is_valid_jwt(tenant_id=x_tenant_id, authorization=authorization):
                return TenantContext(tenant_id=x_tenant_id, customer_id=x_customer_id)
            raise HTTPException(status_code=401, detail="Unauthorized tenant credentials")

        return TenantContext(tenant_id=x_tenant_id, customer_id=x_customer_id)

    def _is_valid_api_key(self, tenant_id: str, api_key: str) -> bool:
        expected = self.settings.tenant_api_keys.get(tenant_id)
        return bool(expected and api_key and api_key == expected)

    def _is_valid_jwt(self, tenant_id: str, authorization: str) -> bool:
        if not self.settings.jwt_shared_secret:
            return False
        if not authorization or not authorization.lower().startswith("bearer "):
            return False

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return False

        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_shared_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
            claim_tenant = str(payload.get("tenant_id") or payload.get("tid") or "")
            return claim_tenant == tenant_id
        except Exception:
            return False


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
    if not settings.jwt_shared_secret:
        raise HTTPException(status_code=500, detail="JWT_SHARED_SECRET must be configured for admin auth")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_shared_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return claims
    except Exception as err:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from err


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
    x_customer_id: str = Header(..., alias="X-Customer-Id"),
    x_api_key: str = Header(default="", alias="X-Api-Key"),
    authorization: str = Header(default="", alias="Authorization"),
) -> tuple[str, str, str, str]:
    return x_tenant_id, x_customer_id, x_api_key, authorization
