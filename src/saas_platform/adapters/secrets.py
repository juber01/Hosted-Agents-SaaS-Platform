from __future__ import annotations


class SecretReferenceStore:
    """Placeholder for Key Vault secret-reference adapter."""

    def __init__(self) -> None:
        self._refs: dict[str, str] = {}

    def set_reference(self, tenant_id: str, key_name: str, vault_uri: str) -> None:
        self._refs[f"{tenant_id}:{key_name}"] = vault_uri

    def get_reference(self, tenant_id: str, key_name: str) -> str | None:
        return self._refs.get(f"{tenant_id}:{key_name}")
