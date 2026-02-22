from __future__ import annotations


def _secret_name(tenant_id: str, key_name: str) -> str:
    raw = f"tenant-{tenant_id}-{key_name}".lower().strip()
    safe = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in raw)
    return safe.strip("-")[:120]


class SecretReferenceStore:
    """In-memory secret reference store for local development."""

    def __init__(self) -> None:
        self._refs: dict[str, str] = {}

    def set_reference(self, tenant_id: str, key_name: str, vault_uri: str) -> None:
        self._refs[f"{tenant_id}:{key_name}"] = vault_uri

    def get_reference(self, tenant_id: str, key_name: str) -> str | None:
        return self._refs.get(f"{tenant_id}:{key_name}")


class KeyVaultSecretReferenceStore:
    """Key Vault-backed secret storage using managed identity by default."""

    def __init__(
        self,
        *,
        vault_url: str,
        use_managed_identity: bool = True,
        managed_identity_client_id: str = "",
        allow_api_key_fallback: bool = False,
        credential=None,
    ) -> None:
        if not vault_url:
            raise ValueError("vault_url is required")

        if credential is None:
            if use_managed_identity:
                try:
                    from azure.identity import DefaultAzureCredential
                except ModuleNotFoundError as err:
                    raise RuntimeError("azure-identity is required for managed identity auth") from err

                credential = DefaultAzureCredential(
                    managed_identity_client_id=(managed_identity_client_id.strip() or None),
                    exclude_interactive_browser_credential=True,
                )
            elif allow_api_key_fallback:
                raise RuntimeError("Key-based Key Vault auth fallback is not implemented; use managed identity")
            else:
                raise RuntimeError("No Key Vault auth mode available")

        try:
            from azure.keyvault.secrets import SecretClient
        except ModuleNotFoundError as err:
            raise RuntimeError("azure-keyvault-secrets is required for Key Vault adapter") from err

        self._client = SecretClient(vault_url=vault_url, credential=credential)
        self._vault_url = vault_url

    def set_secret_value(self, tenant_id: str, key_name: str, value: str) -> str:
        name = _secret_name(tenant_id, key_name)
        created = self._client.set_secret(name=name, value=value)
        return created.id

    def get_secret_value(self, tenant_id: str, key_name: str) -> str | None:
        name = _secret_name(tenant_id, key_name)
        secret = self._client.get_secret(name)
        return secret.value
