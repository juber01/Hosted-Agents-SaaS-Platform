from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException
import jwt

from saas_platform.config import Settings


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    customer_id: str


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


def tenant_headers(
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_customer_id: str = Header(..., alias="X-Customer-Id"),
    x_api_key: str = Header(default="", alias="X-Api-Key"),
    authorization: str = Header(default="", alias="Authorization"),
) -> tuple[str, str, str, str]:
    return x_tenant_id, x_customer_id, x_api_key, authorization
