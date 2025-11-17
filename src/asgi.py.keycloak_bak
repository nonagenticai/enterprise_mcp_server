#!/usr/bin/env python3
"""
ASGI adapter for using the Enterprise MCP server with Uvicorn.
This creates a FastAPI app that integrates the Enterprise MCP SSE functionality.
"""
import sys
import os
from pathlib import Path

# Add the parent directory to sys.path
parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import logging
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import secrets
import time
from uuid_v7.base import uuid7
import httpx
from starlette.routing import Mount
from starlette.responses import Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, List, Optional, Any
import inspect
import traceback

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("fastmcp-asgi")


# Logging filter to exclude health check endpoints from uvicorn access logs
class HealthCheckLoggingFilter(logging.Filter):
    """Filter to exclude health check endpoints from logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Check if the log message contains health check endpoints
        message = record.getMessage()
        return not any(
            health_path in message for health_path in ["/api/health", "/api/mcp-health"]
        )


# Apply the filter to uvicorn access logger
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.addFilter(HealthCheckLoggingFilter())


# Middleware to filter health check logging
class HealthCheckFilter(BaseHTTPMiddleware):
    """Middleware to prevent logging of health check endpoints."""

    HEALTH_ENDPOINTS = {"/api/health", "/api/mcp-health"}

    async def dispatch(self, request: Request, call_next):
        # Check if this is a health check endpoint
        if request.url.path in self.HEALTH_ENDPOINTS:
            # Disable uvicorn access logging for this request
            # by setting a flag that uvicorn's logger can check
            request.state.skip_logging = True

        response = await call_next(request)
        return response


# Import the MCP instance and necessary components from the server module
# Using relative import for server_fastmcp
from .server import (
    mcp as global_mcp_instance,
    lifespan_manager,  # Import lifespan manager for context
)

# Import routers
# Using relative imports for local API modules
from .auth_api import router as auth_router
from .audit_api import router as audit_router
from .tool_management_api import router as tool_management_router
from .tool_versions_api import router as tool_versions_router

# Import dependency getters
# Using relative import for dependencies
from .dependencies import get_db, get_auth_service, get_audit_service, get_tool_registry

# Create a FastAPI app - Apply lifespan manager here
app = FastAPI(
    title="Enterprise MCP Server",
    description="Enterprise MCP Server with ASGI adapter for Uvicorn",
    version="1.2.0",  # Updated for latest package versions and deprecation fixes
    lifespan=lifespan_manager,  # Use the lifespan manager from server_fastmcp
)

# --- Include Routers (Temporarily Commented Out for Debugging) ---
# logger.info("Temporarily disabling API routers for import testing...")
app.include_router(
    auth_router,
    prefix="/auth",
    tags=["authentication"],
    responses={401: {"description": "Unauthorized"}},
)
app.include_router(
    audit_router,
    prefix="/audit",
    tags=["audit"],
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
app.include_router(
    tool_management_router,
    prefix="/tools",
    tags=["tools"],
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
app.include_router(
    tool_versions_router,
    prefix="/tool-versions",
    tags=["tool-versions"],
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
logger.info("Included auth, audit, tool management, and tool versions routers.")

# Add health check filter middleware (add before CORS to ensure it runs first)
app.add_middleware(HealthCheckFilter)
logger.info("Added health check filter middleware to suppress health endpoint logging.")

# Add CORS middleware
CORS_ALLOWED_ORIGINS_STR = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "https://app.cursor.sh,https://cursor.sh,http://localhost:*,http://127.0.0.1:*",
)
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in CORS_ALLOWED_ORIGINS_STR.split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Authentication models
class TokenRequest(BaseModel):
    grant_type: str
    client_id: str
    client_secret: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


# Simple in-memory token store
VALID_CLIENTS = {"cursor_client": "cursor_secret"}
active_tokens = {}


@app.post("/token", response_model=Token)
async def get_token(request: TokenRequest):
    """
    Authenticate client and generate access token.
    This endpoint supports the client_credentials grant type.
    """
    # Validate client credentials
    if request.grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="Unsupported grant type")

    if (
        request.client_id not in VALID_CLIENTS
        or VALID_CLIENTS[request.client_id] != request.client_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    # Generate a new token
    token = secrets.token_hex(32)
    expiry = time.time() + 3600  # 1 hour from now

    # Store the token
    active_tokens[token] = {"client_id": request.client_id, "expires_at": expiry}

    return Token(access_token=token, expires_in=3600)


@app.get("/")
async def root_info():
    """
    Get basic information about the FastMCP server endpoints.
    """
    return {
        "name": "Enterprise MCP Server ASGI Adapter",
        "description": "FastAPI adapter for Enterprise MCP",
        "status": "running",
        "endpoints": {
            "info": "/api/info",
            "health": "/api/health",
            "mcp_health": "/api/mcp-health",
            "sse_connection": "/sse",
            "sse_messages": "/messages/",
            "docs": "/docs",
            "openapi_schema": "/openapi.json",
            "token": "/token",
        },
        "usage": "To connect to the SSE endpoint, use '/sse'. For posting messages to SSE sessions, use '/messages/{session_id}'.",
    }


@app.get("/api/info")
async def root():
    """Get basic server info."""
    return {
        "name": "FastMCP Server ASGI Adapter",
        "description": "FastAPI adapter for FastMCP",
        "status": "running",
    }


@app.get("/api/health")
async def health_check() -> Dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "healthy", "version": "1.2.0"}


@app.get("/api/mcp-health")
async def mcp_health():
    """Check if the Enterprise MCP server is running correctly."""
    try:
        # Check if the Enterprise MCP server instance is available and configured
        if not hasattr(global_mcp_instance, "_mcp_server") or not hasattr(
            global_mcp_instance, "_allow_anonymous"
        ):
            # Try to initialize config manually if needed (for testing)
            if not hasattr(global_mcp_instance, "_allow_anonymous"):
                global_mcp_instance._allow_anonymous = True
                global_mcp_instance._server_name = (
                    "Enterprise MCP ASGI Server (Initialized)"
                )
                logger.warning(
                    "Manually initialized Enterprise MCP config for health check"
                )
            else:
                return {
                    "status": "unhealthy",
                    "error": "Enterprise MCP server not initialized",
                }

        # Check if we can access the tools (this might need lifespan context)
        try:
            tools = await global_mcp_instance.get_tools()
            tools_count = len(tools)
            tool_names = list(tools.keys())
        except Exception as tool_err:
            logger.warning(f"Could not list tools for health check: {tool_err}")
            tools_count = -1  # Indicate error
            tool_names = []

        return {
            "status": "healthy",
            "mcp_server_name": getattr(global_mcp_instance, "_server_name", "Unknown"),
            "allow_anonymous": getattr(
                global_mcp_instance, "_allow_anonymous", "Unknown"
            ),
            "tools_count": tools_count,
            "tool_names": tool_names,
        }
    except Exception as e:
        logger.error(f"Error checking Enterprise MCP health: {e}", exc_info=True)
        return {"status": "unhealthy", "error": str(e)}


@app.post("/api/tools/{tool_name}")
async def call_tool(tool_name: str, request: Request):
    """
    Call an Enterprise MCP tool by name.

    In the Enterprise Gateway Server, this endpoint exists to maintain API compatibility
    but returns a 404 error since no tools are available on this server instance.
    """
    # Enterprise Gateway Server: Return appropriate error response
    return JSONResponse(
        status_code=404,
        content={
            "detail": f"Tool '{tool_name}' not found on this gateway instance.",
            "message": "This server instance is a gateway and has no local operational tools.",
        },
    )


# --- Make Tool Registry Available to All Endpoints ---
@app.get("/api/available-tools")
async def list_available_tools() -> Dict[str, Any]:
    """List all available tools and their descriptions."""
    try:
        # Enterprise Gateway Server: Return empty list of tools
        return {
            "tools": [],
            "message": "This server instance is a gateway and has no local operational tools.",
        }
    except Exception as e:
        logger.error(f"Error listing available tools: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to list available tools")


# --- Mount FastMCP SSE App ---
# Get the Starlette app from FastMCP using the http_utils module
from .http_utils import create_sse_app

sse_app = create_sse_app(global_mcp_instance)

# Mount the Enterprise MCP SSE app at the root.
# FastAPI routes defined above will take precedence for their specific paths.
# The mounted app will handle remaining paths like /sse and /messages/.
app.mount("/", sse_app)
logger.info("Mounted Enterprise MCP SSE app at root path to handle /sse and /messages/")

# --- Startup logic is handled by lifespan_manager in server.py ---
# The deprecated @app.on_event("startup") has been removed in favor of
# the lifespan context manager which properly handles startup/shutdown


# Error handlers
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8033))

    # Run the FastAPI app with Uvicorn
    uvicorn.run("src.asgi:app", host=host, port=port, log_level="info", reload=True)
