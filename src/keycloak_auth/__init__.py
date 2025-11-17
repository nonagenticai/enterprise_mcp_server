"""Keycloak authentication module for enterprise_mcp_server."""

from .config import KeycloakSettings, get_keycloak_settings
from .models import KeycloakUser, TokenResponse
from .validator import KeycloakTokenValidator, get_token_validator
from .middleware import KeycloakAuthMiddleware
from .dependencies import get_current_user, require_role, require_any_role

__all__ = [
    "KeycloakSettings",
    "get_keycloak_settings",
    "KeycloakUser",
    "TokenResponse",
    "KeycloakTokenValidator",
    "get_token_validator",
    "KeycloakAuthMiddleware",
    "get_current_user",
    "require_role",
    "require_any_role",
]
