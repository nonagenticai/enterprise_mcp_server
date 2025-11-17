"""User and auth models for Keycloak integration."""

from typing import List, Optional

from pydantic import BaseModel, Field


class KeycloakUser(BaseModel):
    """Keycloak user model with roles and permissions."""
    
    # Standard OIDC claims
    sub: str = Field(..., description="Subject (unique user ID)")
    preferred_username: str = Field(..., description="Username")
    email: Optional[str] = Field(None, description="User email")
    email_verified: bool = Field(False, description="Email verification status")
    name: Optional[str] = Field(None, description="Full name")
    given_name: Optional[str] = Field(None, description="First name")
    family_name: Optional[str] = Field(None, description="Last name")
    
    # Keycloak-specific claims
    realm_access: dict = Field(default_factory=dict, description="Realm roles")
    resource_access: dict = Field(default_factory=dict, description="Client roles")
    
    # Token metadata
    exp: Optional[int] = Field(None, description="Token expiration")
    iat: Optional[int] = Field(None, description="Issued at")
    
    def has_realm_role(self, role: str) -> bool:
        """Check if user has a specific realm role."""
        roles = self.realm_access.get("roles", [])
        return role in roles
    
    def has_client_role(self, client_id: str, role: str) -> bool:
        """Check if user has a specific client role."""
        client_roles = self.resource_access.get(client_id, {}).get("roles", [])
        return role in client_roles
    
    def get_all_roles(self) -> List[str]:
        """Get all realm and client roles for this user."""
        realm_roles = self.realm_access.get("roles", [])
        client_roles = []
        for client_data in self.resource_access.values():
            client_roles.extend(client_data.get("roles", []))
        return realm_roles + client_roles
    
    @property
    def is_admin(self) -> bool:
        """Check if user has admin role (realm or client)."""
        return self.has_realm_role("admin") or "admin" in self.get_all_roles()


class TokenResponse(BaseModel):
    """OAuth2 token response from Keycloak."""
    
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    refresh_expires_in: Optional[int] = None
    scope: Optional[str] = None
