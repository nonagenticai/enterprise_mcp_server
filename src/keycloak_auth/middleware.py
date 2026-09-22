"""Keycloak Authentication Middleware for Requirements API."""

import logging
from collections.abc import Callable

from fastapi import HTTPException, Request, Response, status
from jwt import PyJWTError
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_keycloak_settings
from .models import KeycloakUser
from .validator import get_token_validator

logger = logging.getLogger(__name__)

# Public endpoints that don't require authentication
PUBLIC_ENDPOINTS = [
    "/health",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
]


class KeycloakAuthMiddleware(BaseHTTPMiddleware):
    """Keycloak-based authentication middleware.

    Validates JWT tokens from Keycloak and extracts user information.
    Supports both service-to-service (client_credentials) and user authentication.
    """

    def __init__(self, app, excluded_paths: list[str] | None = None):
        super().__init__(app)
        self.settings = get_keycloak_settings()
        self.validator = get_token_validator()
        self.excluded_paths = excluded_paths or PUBLIC_ENDPOINTS

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process authentication for each request."""

        # Skip authentication for excluded paths
        if self._is_excluded_path(request.url.path):
            return await call_next(request)

        # Skip auth if disabled (for testing/development)
        if not self.settings.auth_enabled:
            logger.debug("Authentication disabled - allowing request")
            # Add mock user for testing
            request.state.user = self._create_mock_user()
            return await call_next(request)

        try:
            # Extract token from Authorization header
            token = self._extract_token(request)
            if not token:
                return self._unauthorized_response("Missing authentication token")

            # Validate token with Keycloak
            try:
                payload = await self.validator.validate_token(token)
            except PyJWTError as e:
                logger.warning(f"Token validation failed: {e}")
                return self._unauthorized_response(f"Invalid token: {e!s}")
            except Exception as e:
                logger.error(f"Unexpected error validating token: {e}")
                return self._unauthorized_response("Token validation failed")

            # Create user object from token payload
            try:
                user = KeycloakUser(**payload)
                request.state.user = user
                logger.debug(f"Authenticated user: {user.preferred_username}")
            except Exception as e:
                logger.error(f"Failed to create user object: {e}")
                return self._unauthorized_response("Invalid token payload")

            # Proceed with request
            return await call_next(request)

        except HTTPException:
            raise
        except Exception:
            logger.exception("Authentication middleware error")
            return self._internal_error_response("Authentication service error")

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path is excluded from authentication."""
        clean_path = path.rstrip("/")
        if not clean_path:
            clean_path = "/"

        # Check exact matches
        if clean_path in self.excluded_paths:
            return True

        # Check path prefixes on a segment boundary: the path must equal the prefix
        # or continue with a '/' separator. A raw startswith would let /docsabc, /static-x,
        # /redocxyz, /openapi.json.bak bypass authentication.
        excluded_prefixes = ["/docs", "/redoc", "/static", "/openapi.json"]
        return any(
            clean_path == prefix or clean_path.startswith(prefix + "/")
            for prefix in excluded_prefixes
        )

    def _extract_token(self, request: Request) -> str | None:
        """Extract JWT token from Authorization header."""
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None

    def _create_mock_user(self) -> KeycloakUser:
        """Create mock user for testing when auth is disabled."""
        return KeycloakUser(
            sub="test-user-id",
            preferred_username="test-user",
            email="test@example.com",
            name="Test User",
            realm_access={"roles": ["admin", "user"]},
            resource_access={"mcp": {"roles": ["admin"]}},
        )

    def _unauthorized_response(self, detail: str) -> Response:
        """Return 401 Unauthorized response."""
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": detail,
                    "status": 401,
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _internal_error_response(self, detail: str) -> Response:
        """Return 500 Internal Server Error response."""
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "AUTHENTICATION_SERVICE_ERROR",
                    "message": detail,
                    "status": 500,
                }
            },
        )
