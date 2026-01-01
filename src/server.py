#!/usr/bin/env python3
# Standard Library Imports
import os
import json
import base64
import binascii
import logging
import time
import hashlib
import inspect
import asyncio
import ast
import traceback
import sys
from typing import (
    Dict,
    List,
    Optional,
    Union,
    Any,
    get_type_hints,
    Annotated,
    Set,
    Callable,
    Coroutine,
    TypeVar,
    Literal,
)
from datetime import datetime, timedelta
from pathlib import Path
from io import StringIO
from collections import defaultdict
from functools import wraps
import tempfile
import subprocess
import importlib
from contextlib import asynccontextmanager
from uuid_v7.base import uuid7

# Add parent directory to path if running as main module
if __name__ == "__main__":
    parent_dir = str(Path(__file__).parent.parent.absolute())
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

# Third-party Imports
from dotenv import load_dotenv
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from RestrictedPython import (
    compile_restricted_exec,
    safe_builtins,
    limited_builtins,
    utility_builtins,
)
from fastapi import FastAPI

# Local/Application Imports (Using only relative imports now)
from .mcp_postgres_db import MCPPostgresDB
from .auth import AuthService
from .audit import AuditLogService
from .dependencies import get_db, get_auth_service, get_audit_service, get_tool_registry
from .tools.tool import tool_mcp  # Import the tool server
from .tools.claude import claude_mcp  # Import Claude Code tools
from .tools.claude_auth import claude_auth_mcp  # Import Claude authentication tools

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants
MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "Enterprise MCP Gateway Server")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8033))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# --- Single FastMCP Instance ---
# Create a single FastMCP instance that will be used throughout the application
mcp = FastMCP(name=MCP_SERVER_NAME)


# --- Tool Loading ---
async def initialize_db_and_load_tools(mcp_instance: FastMCP):
    """
    Initializes the database connection and loads tools from the database.
    Also registers built-in tools.
    Returns the initialized DB, AuthService, and AuditLogService instances.
    """
    logger.info("Initializing database connection and services...")
    try:
        db = await MCPPostgresDB.connect()
        auth_service = AuthService(db)
        audit_service = AuditLogService(db)
        logger.info("Database connection and services initialized successfully.")

        # Initialize default roles and permissions if needed
        await auth_service.initialize_roles_and_permissions()
        logger.info("Checked and initialized default roles/permissions.")

        # Mount the tool servers to the main MCP instance
        # Updated syntax for FastMCP v2.11.3 - mount prefix is now optional
        mcp_instance.mount(tool_mcp, prefix="tools")
        logger.info("Mounted tools server to main MCP instance.")

        mcp_instance.mount(claude_mcp, prefix="claude")
        logger.info("Mounted Claude Code tools to main MCP instance.")

        mcp_instance.mount(claude_auth_mcp, prefix="claude_auth")
        logger.info("Mounted Claude authentication tools to main MCP instance.")

        return db, auth_service, audit_service

    except Exception as e:
        logger.critical(
            f"CRITICAL: Failed to initialize database or services: {e}", exc_info=True
        )
        raise RuntimeError(f"Failed to initialize core services: {e}") from e


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan_manager(app: FastAPI):
    """
    Async context manager for FastAPI lifespan events.
    Initializes DB connection, services, loads tools on startup.
    Closes DB connection on shutdown.
    Stores instances in app.state for dependency injection.
    """
    logger.info("FastAPI Lifespan: Startup sequence starting...")

    try:
        # Initialize DB and services first
        logger.info("Initializing database connection and services...")
        db, auth_service, audit_service = await initialize_db_and_load_tools(mcp)
        logger.info("DB and services initialized.")

        # Store instances in app.state for dependency injection
        app.state.db = db
        app.state.auth_service = auth_service
        app.state.audit_service = audit_service
        app.state.mcp_instance = mcp
        logger.info("Services attached to app.state.")

        # Check mounted tools
        tools = await mcp.get_tools()
        tool_count = len(tools)
        logger.info(f"Enterprise Gateway Server: Found {tool_count} tools.")

        logger.info("FastAPI Lifespan: Startup complete.")
        yield

        # Cleanup on shutdown
        if hasattr(db, "close") and callable(db.close):
            await db.close()
        logger.info("FastAPI Lifespan: Shutdown complete.")

    except Exception as startup_err:
        logger.critical(
            f"CRITICAL: FastAPI startup failed: {startup_err}", exc_info=True
        )
        raise RuntimeError(f"Server startup failed: {startup_err}") from startup_err


# --- Background Tasks ---
async def audit_log_retention_task(audit_service: AuditLogService):
    """Independent task for audit log cleanup, managed by AuditLogService itself."""
    # The AuditLogService now manages its own cleanup task internally.
    logger.info("Audit log retention task started (managed by AuditLogService).")
    pass  # Let AuditLogService handle it.


# --- Enterprise Gateway Server: No Built-in Tools ---


async def register_builtin_tools(mcp_instance):
    """
    This function exists to maintain API compatibility but does not register any tools
    since this is a gateway server with no operational tools.

    Returns an empty list to indicate no tools were registered.
    """
    logger.info(
        "Enterprise Gateway Server: No direct tools will be registered, using mounted tools instead"
    )
    return []


# --- Helper Types/Constants for Security Analysis (Not tools themselves) ---
class CodeAnalysisResult(BaseModel):
    is_safe: bool
    risk_level: Literal["none", "low", "medium", "high"]
    detected_issues: List[str] = Field(default_factory=list)
    imports: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


# Global set to store allowed import names for sandboxed execution
allowed_imports: Set[str] = {
    "math",
    "random",
    "datetime",
    "time",
    "json",
    "re",
    "collections",
    "functools",
    "itertools",
    "base64",
    "hashlib",
    "hmac",
    "uuid",
    "io",
    "decimal",
    *safe_builtins.keys(),
    *limited_builtins.keys(),
    *utility_builtins.keys(),
}
allowed_imports_lock = asyncio.Lock()

# Sandboxing configuration
SKIP_SANDBOX = os.getenv("SKIP_SANDBOX", "False").lower() in ("true", "1", "t")
if SKIP_SANDBOX:
    logger.warning("!!! SANDBOX DISABLED via SKIP_SANDBOX environment variable !!!")

# --- Enterprise Gateway Server: Helper function stubs for API compatibility ---


def _compile_and_exec_tool_code(
    code: str, tool_name_hint: str = "dynamic_tool"
) -> Callable:
    """
    Enterprise Gateway Server: Stub function that raises an exception.
    Tool compilation and execution is not supported in gateway mode.
    """
    logger.warning(
        f"Enterprise Gateway Server: Tool compilation attempted but not supported: {tool_name_hint}"
    )
    raise ValueError(
        "Enterprise Gateway Server does not support tool compilation or execution"
    )


def _create_openapi_tool_function(
    operation_id: str,
    method: str,
    path: str,
    base_url: str,
    operation_spec: Dict,
    parameters_spec: List[Dict],
    components: Dict,
) -> Callable:
    """
    Enterprise Gateway Server: Stub function that raises an exception.
    OpenAPI tool creation is not supported in gateway mode.
    """
    logger.warning(
        f"Enterprise Gateway Server: OpenAPI tool creation attempted but not supported: {operation_id}"
    )
    raise ValueError("Enterprise Gateway Server does not support OpenAPI tool creation")


# --- Server Execution ---


def run_server():
    """
    Configures and runs the FastMCP server using Uvicorn via the ASGI adapter.
    """
    import uvicorn

    logger.info(
        f"Starting Uvicorn server for Enterprise MCP Gateway Server on {HOST}:{PORT}"
    )
    logger.info(f"Log level set to: {LOG_LEVEL}")

    uvicorn.run(
        "src.asgi:app",  # Point to the ASGI app instance
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False,  # Typically False for production/stable runs
    )


if __name__ == "__main__":
    # Setup for running as main module (e.g., path adjustments)
    parent_dir = str(Path(__file__).parent.parent.absolute())
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        logger.debug(f"Added {parent_dir} to sys.path")

    # Execute the server run function
    run_server()
