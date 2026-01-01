#!/usr/bin/env python3
"""
Run script for Enterprise MCP server.
"""
import sys
import os
import asyncio
import logging
from pathlib import Path

# Add the parent directory to sys.path if running as a script
parent_dir = str(Path(__file__).parent.parent.absolute())
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("run-enterprise-mcp")


# The main function to run the server
def main():
    from dotenv import load_dotenv

    load_dotenv()

    # Get the MCP instance
    from src.server import mcp, register_builtin_tools

    # Print fastmcp version
    import fastmcp

    print(f"Using FastMCP version: {fastmcp.__version__}")

    # Determine transport settings
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8033))
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    transport_type = os.getenv("MCP_TRANSPORT", "http").lower()

    print(f"Starting FastMCP server with transport type: {transport_type}")

    # Enterprise Gateway Server - No Tool Initialization
    async def init_gateway():
        logger.info("Initializing Enterprise MCP Gateway Server...")
        # No tools are registered in this gateway server version
        tools = await mcp.get_tools()
        logger.info(f"Gateway initialized with {len(tools)} tools (should be 0)")

    # Run the async init in the event loop
    try:
        asyncio.run(init_gateway())
        logger.info("Gateway initialization completed")
    except Exception as e:
        logger.error(f"Error during gateway initialization: {e}", exc_info=True)
        logger.warning("Continuing with server startup despite initialization error")

    if transport_type == "http":
        # Run with Streamable HTTP transport
        print(f"Running with Streamable HTTP transport on {host}:{port}")
        mcp.run(
            transport="streamable-http",
            host=host,
            port=port,
            log_level=log_level,
        )
    elif transport_type == "stdio":
        # Run with stdio transport for Cursor Desktop
        print("Running with stdio transport")
        mcp.run(transport="stdio")
    else:
        print(f"Error: Unsupported MCP_TRANSPORT: {transport_type}")
        print("Supported types: 'http', 'stdio'")
        sys.exit(1)


if __name__ == "__main__":
    main()
