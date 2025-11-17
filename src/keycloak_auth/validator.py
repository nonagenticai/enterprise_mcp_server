"""Keycloak token validation for requirements_api service."""

import logging
from functools import lru_cache
from typing import Dict, Optional

import httpx
from jose import jwt, JWTError
from keycloak import KeycloakOpenID

from .config import get_keycloak_settings

logger = logging.getLogger(__name__)


class KeycloakTokenValidator:
    """Handles Keycloak token validation and user info extraction."""
    
    def __init__(self):
        self.settings = get_keycloak_settings()
        self._public_key: Optional[str] = None
        self._keycloak_openid: Optional[KeycloakOpenID] = None
        
    @property
    def keycloak_openid(self) -> KeycloakOpenID:
        """Get or create KeycloakOpenID instance."""
        if not self._keycloak_openid:
            self._keycloak_openid = KeycloakOpenID(
                server_url=self.settings.keycloak_url,
                client_id=self.settings.client_id,
                realm_name=self.settings.realm_name,
                client_secret_key=self.settings.client_secret,
                verify=self.settings.ssl_verify
            )
        return self._keycloak_openid
    
    @lru_cache(maxsize=1)
    def get_public_key(self) -> str:
        """Fetch and cache Keycloak's public key for JWT validation."""
        if not self._public_key:
            try:
                self._public_key = (
                    "-----BEGIN PUBLIC KEY-----\n"
                    + self.keycloak_openid.public_key()
                    + "\n-----END PUBLIC KEY-----"
                )
                logger.info("Successfully fetched Keycloak public key")
            except Exception as e:
                logger.error(f"Failed to fetch Keycloak public key: {e}")
                raise
        return self._public_key
    
    async def validate_token(self, token: str) -> Dict:
        """
        Validate JWT token using Keycloak's public key.
        
        This is faster than introspection but doesn't check revocation.
        Use for most endpoints.
        
        Args:
            token: JWT access token
            
        Returns:
            Decoded token payload with user info
            
        Raises:
            JWTError: If token is invalid or expired
        """
        try:
            # Decode and validate token
            options = {
                "verify_signature": True,
                "verify_aud": False,  # Keycloak doesn't always include aud
                "verify_exp": True,
            }
            
            payload = jwt.decode(
                token,
                self.get_public_key(),
                algorithms=["RS256"],
                options=options
            )
            
            logger.debug(f"Token validated for user: {payload.get('preferred_username')}")
            return payload
            
        except JWTError as e:
            logger.warning(f"Token validation failed: {e}")
            raise
    
    async def introspect_token(self, token: str) -> Dict:
        """
        Introspect token using Keycloak API (checks revocation).
        
        This is more secure but slower than JWT validation.
        Use for sensitive endpoints.
        
        Args:
            token: JWT access token
            
        Returns:
            Token introspection result
            
        Raises:
            Exception: If token is not active or introspection fails
        """
        try:
            token_info = self.keycloak_openid.introspect(token)
            
            if not token_info.get("active"):
                raise Exception("Token is not active")
            
            logger.debug(f"Token introspected for user: {token_info.get('username')}")
            return token_info
            
        except Exception as e:
            logger.warning(f"Token introspection failed: {e}")
            raise
    
    async def get_userinfo(self, token: str) -> Dict:
        """
        Get detailed user information from Keycloak using token.
        
        Args:
            token: Valid JWT access token
            
        Returns:
            User information from Keycloak
        """
        try:
            async with httpx.AsyncClient(verify=self.settings.ssl_verify) as client:
                response = await client.get(
                    self.settings.userinfo_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get user info: {e}")
            raise


@lru_cache()
def get_token_validator() -> KeycloakTokenValidator:
    """Get cached token validator instance."""
    return KeycloakTokenValidator()
