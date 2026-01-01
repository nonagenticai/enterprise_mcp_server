"""
HTTP utilities for the Enterprise MCP Server.

This module provides utilities for Streamable HTTP transport functionality.
"""

import logging

from fastmcp import FastMCP
from starlette.applications import Starlette

logger = logging.getLogger(__name__)


def create_mcp_http_app(mcp_instance: FastMCP, path: str = "/mcp") -> Starlette:
    """
    Creates and configures a Streamable HTTP application for MCP.

    Args:
        mcp_instance: The FastMCP instance to use for HTTP functionality
        path: The path to mount the MCP endpoint at (default: /mcp)

    Returns:
        A configured Starlette application for Streamable HTTP transport
    """
    logger.info(f"Creating MCP Streamable HTTP app at path: {path}")

    # CRITICAL: Must specify transport="streamable-http"
    # FastMCP's http_app() defaults to SSE, not Streamable HTTP
    # Modern Claude Code (2026+) requires Streamable HTTP transport
    http_app = mcp_instance.http_app(path=path, transport="streamable-http")

    return http_app
