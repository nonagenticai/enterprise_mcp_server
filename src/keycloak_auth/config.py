"""Keycloak configuration for enterprise_mcp_server."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class KeycloakSettings(BaseSettings):
    """Keycloak configuration settings."""

    keycloak_url: str = os.getenv("KEYCLOAK_URL", "https://keycloak.internal")
    realm_name: str = os.getenv("KEYCLOAK_REALM", "secure-apps")
    client_id: str = os.getenv("KEYCLOAK_CLIENT_ID", "mcp")
    client_secret: str = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

    # Optional: Enable/disable authentication
    auth_enabled: bool = os.getenv("AUTH_ENABLED", "true").lower() == "true"

    # SSL verification (set to false for self-signed certs in dev)
    ssl_verify: bool = os.getenv("KEYCLOAK_SSL_VERIFY", "true").lower() == "true"

    @property
    def token_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.realm_name}/protocol/openid-connect/token"

    @property
    def certs_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.realm_name}/protocol/openid-connect/certs"

    @property
    def userinfo_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.realm_name}/protocol/openid-connect/userinfo"

    @property
    def well_known_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.realm_name}/.well-known/openid-configuration"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env


@lru_cache
def get_keycloak_settings() -> KeycloakSettings:
    """Get cached Keycloak settings instance."""
    return KeycloakSettings()
