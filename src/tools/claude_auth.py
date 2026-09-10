from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from aiohttp import web
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel

load_dotenv()

# Create FastMCP instance for authentication tools
claude_auth_mcp = FastMCP(name="Claude Auth Server")

# Constants
CLAUDE_CONFIG_PATH = Path.home() / ".claude"
CLAUDE_CONFIG_FILE = CLAUDE_CONFIG_PATH / "config.json"
AUTH_CALLBACK_PORT = 8765  # Local port for OAuth callback


class AuthStatus(BaseModel):
    """Authentication status response"""

    is_authenticated: bool
    config_exists: bool
    cli_installed: bool
    details: dict[str, Any] | None = None
    error: str | None = None


def find_free_port() -> int:
    """Find a free port for the OAuth callback server"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


async def start_oauth_callback_server(port: int) -> dict[str, Any]:
    """
    Start a temporary HTTP server to receive OAuth callback
    Returns the received authentication data
    """
    auth_data = {}

    async def handle_callback(request):
        """Handle OAuth callback from browser"""
        nonlocal auth_data

        # Extract auth data from query parameters or POST body
        if request.method == "GET":
            auth_data = dict(request.query)
        elif request.method == "POST":
            auth_data = await request.json()

        # Return success page to browser
        html = """
        <html>
        <head><title>Claude Authentication</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>✓ Authentication Successful!</h1>
            <p>You can close this window and return to your terminal.</p>
            <script>window.setTimeout(function(){window.close()}, 3000);</script>
        </body>
        </html>
        """
        return web.Response(text=html, content_type="text/html")

    # Create and configure the app
    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    app.router.add_post("/callback", handle_callback)
    app.router.add_get("/auth", handle_callback)

    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    print(f"OAuth callback server started on http://localhost:{port}")

    # Wait for authentication (timeout after 5 minutes)
    timeout = 300  # 5 minutes
    check_interval = 1
    elapsed = 0

    while not auth_data and elapsed < timeout:
        await asyncio.sleep(check_interval)
        elapsed += check_interval

    # Clean up
    await runner.cleanup()

    if not auth_data:
        raise TimeoutError("Authentication timeout - no callback received")

    return auth_data


@claude_auth_mcp.tool()
async def claude_auth_status() -> str:
    """
    Check Claude Code CLI authentication status.
    Returns detailed information about the current auth state.
    """
    status = AuthStatus(
        is_authenticated=False, config_exists=False, cli_installed=False
    )

    try:
        # Check if Claude CLI is installed
        result = subprocess.run(
            ["which", "claude"], capture_output=True, text=True, timeout=5, check=False
        )
        status.cli_installed = result.returncode == 0

        if not status.cli_installed:
            status.error = "Claude CLI not installed. Install with: npm install -g @anthropic-ai/claude-code"
            return json.dumps(status.model_dump(), indent=2)

        # Check if config file exists
        status.config_exists = CLAUDE_CONFIG_FILE.exists()

        if status.config_exists:
            try:
                # Read and validate config
                with open(CLAUDE_CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    status.details = {
                        "config_path": str(CLAUDE_CONFIG_FILE),
                        "has_token": bool(config.get("token") or config.get("api_key")),
                        "profile": config.get("profile", "default"),
                    }
                    status.is_authenticated = status.details["has_token"]
            except Exception as e:
                status.error = f"Error reading config: {e!s}"
        else:
            status.error = (
                "No authentication config found. Run claude_auth_login to authenticate."
            )

    except subprocess.TimeoutExpired:
        status.error = "Timeout checking Claude CLI status"
    except Exception as e:
        status.error = f"Unexpected error: {e!s}"

    return json.dumps(status.model_dump(), indent=2)


@claude_auth_mcp.tool()
async def claude_auth_login(
    browser_auth: bool = True, api_key: str | None = None
) -> str:
    """
    Perform Claude Code CLI authentication.

    Args:
        browser_auth: Use browser-based authentication (default: True)
        api_key: Optional API key for direct authentication

    Returns:
        Authentication result message
    """
    try:
        # Ensure config directory exists
        CLAUDE_CONFIG_PATH.mkdir(parents=True, exist_ok=True)

        if api_key:
            # Direct API key authentication
            config = {
                "api_key": api_key,
                "auth_method": "api_key",
                "profile": "default",
            }

            with open(CLAUDE_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)

            return "✓ Authentication configured with API key"

        elif browser_auth:
            # Browser-based OAuth authentication

            # Check if running in a container/headless environment
            is_headless = not os.environ.get("DISPLAY") and os.environ.get(
                "RUNNING_IN_DOCKER"
            )

            if is_headless:
                # Start callback server for headless environments
                port = find_free_port()
                callback_url = f"http://localhost:{port}/callback"

                print(f"Starting OAuth callback server on port {port}...")

                # Start callback server in background
                auth_task = asyncio.create_task(start_oauth_callback_server(port))

                # Generate auth URL (this would need to be implemented based on Claude's OAuth flow)
                auth_url = f"https://claude.ai/auth?callback={callback_url}"

                print("\nPlease open this URL in your browser to authenticate:")
                print(auth_url)
                print("\nWaiting for authentication...")

                # Wait for auth data
                auth_data = await auth_task

                # Save authentication data
                config = {
                    "token": auth_data.get("token") or auth_data.get("access_token"),
                    "refresh_token": auth_data.get("refresh_token"),
                    "auth_method": "oauth",
                    "profile": "default",
                }

                with open(CLAUDE_CONFIG_FILE, "w") as f:
                    json.dump(config, f, indent=2)

                return "✓ Browser authentication successful"
            else:
                # Use the standard claude login command
                result = subprocess.run(
                    ["claude", "login"],
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                    check=False,
                )

                if result.returncode == 0:
                    return "✓ Authentication successful via Claude CLI"
                else:
                    error_msg = result.stderr or result.stdout
                    return f"✗ Authentication failed: {error_msg}"

        else:
            return "✗ No authentication method specified"

    except TimeoutError:
        return "✗ Authentication timeout - no response received"
    except Exception as e:
        return f"✗ Authentication error: {e!s}"


@claude_auth_mcp.tool()
async def claude_auth_logout() -> str:
    """
    Logout from Claude Code CLI by removing stored credentials.
    """
    try:
        if CLAUDE_CONFIG_FILE.exists():
            # Backup the config before deleting (just in case)
            backup_file = CLAUDE_CONFIG_FILE.with_suffix(".json.backup")
            import shutil

            shutil.copy2(CLAUDE_CONFIG_FILE, backup_file)

            # Remove the config file
            CLAUDE_CONFIG_FILE.unlink()

            return f"✓ Logged out successfully. Config backed up to {backup_file}"
        else:
            return "ℹ Already logged out (no config file found)"
    except Exception as e:
        return f"✗ Error during logout: {e!s}"


@claude_auth_mcp.tool()
async def claude_auth_test() -> str:
    """
    Test Claude Code CLI authentication by making a simple query.
    """
    try:
        # First check auth status
        status_json = await claude_auth_status()
        status = json.loads(status_json)

        if not status["is_authenticated"]:
            return "✗ Not authenticated. Please run claude_auth_login first."

        # Try a simple Claude query
        from claude_code_sdk import (
            AssistantMessage,
            ClaudeCodeOptions,
            TextBlock,
            query,
        )

        test_prompt = "Say 'Authentication test successful!' if you can read this."
        options = ClaudeCodeOptions(
            max_turns=1, system_prompt="You are a test bot.", allowed_tools=[]
        )

        response_text = ""
        async for message in query(prompt=test_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text

        if "successful" in response_text.lower():
            return f"✓ Authentication test passed! Response: {response_text}"
        else:
            return f"⚠ Got response but unexpected content: {response_text}"

    except Exception as e:
        return f"✗ Authentication test failed: {e!s}"


# Export the MCP instance
if __name__ == "__main__":
    import anyio

    anyio.run(claude_auth_mcp.run)
