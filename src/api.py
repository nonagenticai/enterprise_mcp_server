#!/usr/bin/env python3
"""
API server for Enterprise MCP with authentication, client registration, and administrative functions.
This provides a REST API for managing the Enterprise MCP server.
"""
import os
import sys
import json
from uuid_v7.base import uuid7
import logging
import secrets
from typing import Dict, List, Optional, Any, Union, Annotated
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to sys.path if running as a script
if __name__ == "__main__":
    parent_dir = str(Path(__file__).parent.parent.absolute())
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

# FastAPI imports
from fastapi import FastAPI, HTTPException, Depends, Request, status, Query, Form, Body
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

# Local imports
from .mcp_postgres_db import MCPPostgresDB
from .auth import (
    AuthService,
    get_current_user,
    requires_permission,
    get_auth_service_direct,
)
from .audit import AuditLogService

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Configuration ---
HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", 8030))
CORS_ALLOWED_ORIGINS_STR = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "https://app.cursor.sh,https://cursor.sh,http://localhost:*,http://127.0.0.1:*",
)
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in CORS_ALLOWED_ORIGINS_STR.split(",")
]

# --- FastAPI App ---
app = FastAPI(
    title="Enterprise MCP API Server",
    description="API for managing Enterprise MCP server",
    version="1.0.0",
)

# --- Add CORS middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Global variables for service instances ---
_db_instance: Optional[MCPPostgresDB] = None
_auth_service: Optional[AuthService] = None
_audit_service: Optional[AuditLogService] = None


# --- Models ---
class UserCreate(BaseModel):
    username: str
    password: str
    roles: List[str] = []


class UserResponse(BaseModel):
    id: int
    username: str
    roles: List[str] = []
    is_active: bool = True


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class ClientRegistration(BaseModel):
    client_name: str
    redirect_uris: List[str]
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    scope: Optional[str] = None
    contacts: Optional[List[str]] = None


class ClientResponse(BaseModel):
    client_id: str
    client_secret: str
    client_name: str
    redirect_uris: List[str]
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    scope: Optional[str] = None
    contacts: Optional[List[str]] = None
    client_id_issued_at: int
    client_secret_expires_at: int


# --- Dependencies ---
async def get_db() -> MCPPostgresDB:
    """Get database instance."""
    global _db_instance
    if _db_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not available",
        )
    return _db_instance


async def get_auth_service() -> AuthService:
    """Get authentication service instance."""
    global _auth_service
    if _auth_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not available",
        )
    return _auth_service


async def get_audit_service() -> AuditLogService:
    """Get audit service instance."""
    global _audit_service
    if _audit_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit service not available",
        )
    return _audit_service


# --- API Root ---
@app.get("/")
async def root():
    """Get API server information."""
    return {
        "name": "Enterprise MCP API Server",
        "version": "1.0.0",
        "documentation": "/docs",
        "status": "healthy",
    }


# --- Test Token Endpoint ---
@app.get("/test-token")
async def test_token(auth_service: Annotated[AuthService, Depends(get_auth_service)]):
    """Generate a test token for SSE connection. For testing purposes only."""
    # Create a basic test token with admin permissions
    token_data = {"sub": "test", "id": 1, "scopes": ["*:*"]}
    access_token = await auth_service.create_access_token(data=token_data)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "message": "Use this token for testing SSE connections. Add it as a Bearer token in the Authorization header.",
    }


# --- Authentication endpoints ---
@app.post("/auth/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """Get an access token."""
    user = await auth_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    expires_delta = timedelta(minutes=120)  # 2 hours
    expires_in = 60 * 120  # 2 hours in seconds

    token_data = {"sub": user["username"], "id": user["id"]}
    access_token = await auth_service.create_access_token(data=token_data)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@app.get("/auth/me", response_model=dict)
async def read_users_me(
    current_user: Annotated[Dict[str, Any], Depends(get_current_user)],
):
    """Get current user information."""
    return current_user


# --- User Management ---
@app.post("/users", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    current_user: Annotated[
        Dict[str, Any], Depends(requires_permission("user:create"))
    ],
):
    """Create a new user."""
    # Check if username already exists
    existing_user = await db.get_user_by_username(user.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with username '{user.username}' already exists",
        )

    # Hash the password
    password_hash = auth_service.hash_password(user.password)

    # Create the user
    user_id = await db.create_user(user.username, password_hash)

    # Assign roles if provided
    if user.roles:
        for role_name in user.roles:
            # Get role ID by name
            async with db.pool.acquire() as conn:
                role_id = await conn.fetchval(
                    "SELECT id FROM roles WHERE name = $1", role_name
                )
                if role_id:
                    await db.assign_role_to_user(user_id, role_id)

    # Get the created user with roles
    roles = await db.get_user_roles(user_id)
    role_names = [role["name"] for role in roles]

    return {
        "id": user_id,
        "username": user.username,
        "roles": role_names,
        "is_active": True,
    }


@app.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: Annotated[Dict[str, Any], Depends(requires_permission("user:read"))],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
):
    """List all users."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users")
        users = []

        for row in rows:
            user_dict = dict(row)
            user_id = user_dict["id"]

            # Get roles for each user
            roles = await db.get_user_roles(user_id)
            role_names = [role["name"] for role in roles]

            users.append(
                {
                    "id": user_id,
                    "username": user_dict["username"],
                    "roles": role_names,
                    "is_active": user_dict.get("is_active", True),
                }
            )

        return users


# --- Client Registration for OAuth ---
@app.post(
    "/register", response_model=ClientResponse, status_code=status.HTTP_201_CREATED
)
async def register_client(
    client_data: ClientRegistration,
    current_user: Annotated[
        Dict[str, Any], Depends(requires_permission("oauth:register"))
    ],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
):
    """Register a new OAuth client."""
    # Validate redirect URIs
    for uri in client_data.redirect_uris:
        if not uri.startswith(("https://", "http://localhost")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Redirect URIs must use HTTPS except for localhost",
            )

    # Generate client ID and secret
    client_id = str(uuid7())
    client_secret = secrets.token_urlsafe(32)

    # Prepare client data
    client = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": client_data.client_name,
        "redirect_uris": client_data.redirect_uris,
        "client_uri": client_data.client_uri,
        "logo_uri": client_data.logo_uri,
        "scope": client_data.scope,
        "contacts": client_data.contacts,
        "client_id_issued_at": int(datetime.now().timestamp()),
        "client_secret_expires_at": 0,  # Does not expire
    }

    # Save to database
    try:
        await db.save_oauth_client(client)
    except Exception as e:
        logger.error(f"Error saving OAuth client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error registering client: {str(e)}",
        )

    return client


@app.get("/clients", response_model=List[dict])
async def list_clients(
    current_user: Annotated[Dict[str, Any], Depends(requires_permission("oauth:read"))],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
):
    """List all OAuth clients."""
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM oauth_clients")
            clients = []

            for row in rows:
                client = dict(row)
                # Convert JSONB to Python objects
                client["redirect_uris"] = client.get("redirect_uris", [])
                client["contacts"] = client.get("contacts", [])

                # Remove sensitive data
                if "client_secret" in client:
                    client["client_secret"] = "***"

                clients.append(client)

            return clients
    except Exception as e:
        logger.error(f"Error listing OAuth clients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing clients: {str(e)}",
        )


# --- Current Server Status ---
@app.get("/status")
async def server_status(db: Annotated[MCPPostgresDB, Depends(get_db)]):
    """Get current server status."""

    # Get counts of various entities
    async with db.pool.acquire() as conn:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        client_count = await conn.fetchval("SELECT COUNT(*) FROM oauth_clients")
        tool_count = await conn.fetchval("SELECT COUNT(*) FROM mcp_tools")
        session_count = 0  # This would need to be tracked elsewhere

        return {
            "status": "healthy",
            "database": "connected",
            "counts": {
                "users": user_count,
                "oauth_clients": client_count,
                "tools": tool_count,
                "active_sessions": session_count,
            },
            "version": "1.0.0",
            "uptime": "unknown",  # Would need to track server start time
        }


# --- OAuth Authorization Server Metadata ---
@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata():
    """Get OAuth server metadata."""
    base_url = os.getenv("PUBLIC_URL", f"http://{HOST}:{PORT}")

    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "scopes_supported": ["tools:read", "tools:write", "profile"],
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "authorization_code",
            "refresh_token",
            "client_credentials",
        ],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        "code_challenge_methods_supported": ["S256"],
        "service_documentation": "https://github.com/modelcontextprotocol/modelcontextprotocol",
        "mcp_protocol_version": "2024-11-05",
        "revocation_endpoint": f"{base_url}/revoke",
        "revocation_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
    }


# --- OAuth Authorization Endpoint ---
@app.get("/authorize")
async def authorize(
    client_id: str = Query(..., description="OAuth client ID"),
    redirect_uri: str = Query(
        ..., description="URI to redirect to after authorization"
    ),
    code_challenge: str = Query(..., description="PKCE code challenge"),
    response_type: str = Query(
        "code", description="OAuth response type, must be 'code'"
    ),
    state: Optional[str] = Query(
        None, description="State parameter for CSRF protection"
    ),
    scope: Optional[str] = Query(
        None, description="Space-separated list of requested scopes"
    ),
    code_challenge_method: str = Query(
        "S256", description="PKCE code challenge method"
    ),
):
    """OAuth 2.0 authorization endpoint."""
    # Get database instance via dependency
    db = await get_db()

    # Validate the client_id and redirect_uri
    client = await db.get_oauth_client(client_id)
    if not client:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_client",
                "error_description": "Client not found",
            },
        )

    # Validate redirect_uri against registered URIs
    registered_uris = client.get("redirect_uris", [])
    if redirect_uri not in registered_uris:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": "Redirect URI mismatch",
            },
        )

    # Create a simple login form
    html_content = f"""
    <html>
        <head><title>MCP Authorization</title></head>
        <body>
            <h1>Authorize Client</h1>
            <p>The client '{client.get("client_name", client_id)}' is requesting access with scopes: {scope or "default"}</p>
            <form action="/authorize/confirm" method="post">
                <input type="hidden" name="client_id" value="{client_id}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri}">
                <input type="hidden" name="state" value="{state or ''}">
                <input type="hidden" name="scope" value="{scope or ''}">
                <input type="hidden" name="code_challenge" value="{code_challenge}">
                <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
                
                <label for="username">Username:</label>
                <input type="text" id="username" name="username"><br><br>
                
                <label for="password">Password:</label>
                <input type="password" id="password" name="password"><br><br>
                
                <input type="submit" value="Authorize">
            </form>
        </body>
    </html>
    """

    return HTMLResponse(content=html_content)


@app.post("/authorize/confirm")
async def authorize_confirm(
    username: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    state: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
):
    """Confirm OAuth 2.0 authorization."""
    # Get dependencies
    db = await get_db()
    auth_service = await get_auth_service()

    # Authenticate the user
    user = await auth_service.authenticate_user(username, password)

    if not user:
        # Show error message
        error_html = f"""
        <html>
            <head><title>Authentication Failed</title></head>
            <body>
                <h1>Authentication Failed</h1>
                <p>Invalid username or password. <a href="/authorize?client_id={client_id}&redirect_uri={redirect_uri}&state={state or ''}&scope={scope or ''}&code_challenge={code_challenge}&code_challenge_method={code_challenge_method}">Try again</a></p>
            </body>
        </html>
        """
        return HTMLResponse(content=error_html)

    # Generate an authorization code
    auth_code = await db.create_auth_code(
        client_id=client_id,
        user_id=user["id"],
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        redirect_uri=redirect_uri,
    )

    # Redirect back to the client
    params = {"code": auth_code}
    if state:
        params["state"] = state

    from urllib.parse import urlencode

    redirect_url = f"{redirect_uri}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url, status_code=303)


# --- OAuth Token Endpoint ---
@app.post("/token")
async def token(request: Request, db: Annotated[MCPPostgresDB, Depends(get_db)]):
    """OAuth 2.0 token endpoint."""
    try:
        # Parse the request based on content type
        if request.headers.get("content-type") == "application/x-www-form-urlencoded":
            form_data = await request.form()
            data = dict(form_data)
        else:
            data = await request.json()

        # Check client credentials in Authorization header
        client_id = None
        client_secret = None
        auth_header = request.headers.get("authorization", "")

        if auth_header.startswith("Basic "):
            import base64

            try:
                encoded_credentials = auth_header[6:]
                decoded_credentials = base64.b64decode(encoded_credentials).decode(
                    "utf-8"
                )
                client_id, client_secret = decoded_credentials.split(":", 1)
            except Exception as e:
                logger.error(f"Failed to parse Basic Auth header: {e}")

        # Get grant type
        grant_type = data.get("grant_type")
        if not grant_type:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "grant_type is required",
                },
            )

        # Handle different grant types
        if grant_type == "authorization_code":
            # Exchange authorization code for token
            code = data.get("code")
            redirect_uri = data.get("redirect_uri")
            client_id = data.get("client_id", client_id)
            code_verifier = data.get("code_verifier")

            if not all([code, redirect_uri, client_id, code_verifier]):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_request",
                        "error_description": "Missing required parameters",
                    },
                )

            # Validate authorization code
            auth_code_data = await db.get_auth_code(code)
            if not auth_code_data:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_grant",
                        "error_description": "Invalid authorization code",
                    },
                )

            # Check expiration
            if auth_code_data.get("expires_at") < datetime.now():
                await db.delete_auth_code(code)
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_grant",
                        "error_description": "Authorization code expired",
                    },
                )

            # Verify client_id
            if auth_code_data.get("client_id") != client_id:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_grant",
                        "error_description": "client_id mismatch",
                    },
                )

            # Verify redirect_uri
            if auth_code_data.get("redirect_uri") != redirect_uri:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_grant",
                        "error_description": "redirect_uri mismatch",
                    },
                )

            # Verify PKCE
            import hashlib
            import base64

            stored_challenge = auth_code_data.get("code_challenge")
            stored_method = auth_code_data.get("code_challenge_method")

            if stored_method == "S256":
                verifier_bytes = code_verifier.encode("ascii")
                challenge = hashlib.sha256(verifier_bytes).digest()
                challenge = base64.urlsafe_b64encode(challenge).decode("ascii")
                challenge = challenge.rstrip("=")

                if challenge != stored_challenge:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "invalid_grant",
                            "error_description": "code_verifier is invalid",
                        },
                    )

            # Generate tokens
            user_id = auth_code_data.get("user_id")
            scope = auth_code_data.get("scope")

            tokens = await db.create_tokens(client_id, user_id, scope)

            # Delete the used code
            await db.delete_auth_code(code)

            # Return the tokens
            return {
                "access_token": tokens["access_token"],
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": tokens["refresh_token"],
                "scope": scope,
            }

        elif grant_type == "refresh_token":
            # Refresh an access token
            refresh_token = data.get("refresh_token")
            client_id = data.get("client_id", client_id)

            if not all([refresh_token, client_id]):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_request",
                        "error_description": "Missing required parameters",
                    },
                )

            # Validate refresh token
            refresh_data = await db.validate_refresh_token(refresh_token, client_id)
            if not refresh_data:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_grant",
                        "error_description": "Invalid refresh token",
                    },
                )

            # Generate new tokens
            tokens = await db.refresh_tokens(refresh_token, client_id)

            # Return the new tokens
            return {
                "access_token": tokens["access_token"],
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": tokens["refresh_token"],
                "scope": refresh_data.get("scope"),
            }

        elif grant_type == "client_credentials":
            # Client credentials grant
            if not client_id:
                client_id = data.get("client_id")
            if not client_secret:
                client_secret = data.get("client_secret")

            scope = data.get("scope")

            if not all([client_id, client_secret]):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_request",
                        "error_description": "Missing client credentials",
                    },
                )

            # Validate client credentials
            client = await db.validate_client_credentials(client_id, client_secret)
            if not client:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "invalid_client",
                        "error_description": "Invalid client credentials",
                    },
                )

            # If no scope, use client's registered scope
            if not scope and client.get("scope"):
                scope = client.get("scope")

            # Generate tokens
            token_result = await db.create_client_credentials_token(client_id, scope)

            # Return the token
            return {
                "access_token": token_result["access_token"],
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": scope,
            }

        else:
            # Unsupported grant type
            return JSONResponse(
                status_code=400,
                content={
                    "error": "unsupported_grant_type",
                    "error_description": "Unsupported grant type",
                },
            )

    except Exception as e:
        logger.error(f"Error processing token request: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "server_error",
                "error_description": "An error occurred processing the request",
            },
        )


# --- OAuth Token Revocation ---
@app.post("/revoke")
async def revoke_token(request: Request, db: Annotated[MCPPostgresDB, Depends(get_db)]):
    """OAuth 2.0 token revocation endpoint."""
    try:
        # Parse the request
        if request.headers.get("content-type") == "application/x-www-form-urlencoded":
            form_data = await request.form()
            data = dict(form_data)
        else:
            data = await request.json()

        # Extract token and hint
        token = data.get("token")
        token_type_hint = data.get("token_type_hint")

        if not token:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "token parameter is required",
                },
            )

        # Check client authentication
        client_id = None
        if "client_id" in data:
            client_id = data.get("client_id")
            client_secret = data.get("client_secret")

            if client_secret and not await db.validate_client_credentials(
                client_id, client_secret
            ):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "invalid_client",
                        "error_description": "Invalid client credentials",
                    },
                )

        # Try to revoke the token
        revoked = False

        if not token_type_hint or token_type_hint == "access_token":
            revoked = await db.revoke_access_token(token, client_id)

        if (not revoked and not token_type_hint) or token_type_hint == "refresh_token":
            revoked = await db.revoke_refresh_token(token, client_id)

        # Return 200 OK regardless (prevent token enumeration)
        return JSONResponse(status_code=200, content={})

    except Exception as e:
        logger.error(f"Error revoking token: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "server_error",
                "error_description": "An error occurred processing the request",
            },
        )


# --- Initialize API Server ---
def initialize(
    db_instance: MCPPostgresDB,
    auth_service: AuthService,
    audit_service: AuditLogService,
):
    """Initialize the API server with service instances."""
    global _db_instance, _auth_service, _audit_service

    _db_instance = db_instance
    _auth_service = auth_service
    _audit_service = audit_service

    logger.info("API server initialized successfully")


# --- Server Entry Point ---
if __name__ == "__main__":
    import uvicorn

    # Note: When run directly, this will try to connect to the database
    # and initialize services. In actual use, the main server should
    # initialize this API server with existing service instances.

    logger.warning("Running API server standalone - this is not recommended")
    logger.warning("In production, initialize this from the main server")

    uvicorn.run("src.api:app", host=HOST, port=PORT, log_level="info")
