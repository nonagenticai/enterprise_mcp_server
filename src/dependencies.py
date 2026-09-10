# Import AuthService after its complete definition in auth.py
# This import will happen at the end to avoid circular dependency
# We want to keep the type hint but import it for runtime at a later point
from typing import TYPE_CHECKING

from fastapi import Request

# Import the actual service classes and DB type
from .audit import AuditLogService
from .mcp_postgres_db import MCPPostgresDB

if TYPE_CHECKING:
    from .auth import AuthService

# Import FastMCP type for hinting
from fastmcp import FastMCP

# Dependency Functions - Retrieve services from app.state


def get_db(request: Request) -> MCPPostgresDB:
    """Dependency to get the database instance from app state."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise RuntimeError(
            "Database not found in app state. Lifespan might have failed."
        )
    return db


def get_auth_service(request: Request) -> "AuthService":
    """Dependency to get the auth service instance from app state."""
    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is None:
        raise RuntimeError(
            "AuthService not found in app state. Lifespan might have failed."
        )
    return auth_service


def get_audit_service(request: Request) -> AuditLogService:
    """Dependency to get the audit service instance from app state."""
    audit_service = getattr(request.app.state, "audit_service", None)
    if audit_service is None:
        raise RuntimeError(
            "AuditLogService not found in app state. Lifespan might have failed."
        )
    return audit_service


def get_tool_registry(request: Request) -> FastMCP:
    """Dependency to get the FastMCP instance from app state."""
    mcp_instance = getattr(request.app.state, "mcp_instance", None)
    if mcp_instance is None:
        raise RuntimeError(
            "FastMCP instance not found in app state. Lifespan might have failed."
        )
    return mcp_instance


# Import AuthService for runtime - REMOVED - This caused the circular import
# from .auth import AuthService
