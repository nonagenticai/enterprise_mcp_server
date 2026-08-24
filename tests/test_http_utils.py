"""Contract tests for `src.http_utils.create_mcp_http_app`.

WHY THIS FILE EXISTS. This repository declared `pytest` as a dependency and shipped **zero**
tests, so `pytest -q` exited 5 ("no tests ran") on every run. That is not a cosmetic gap: this
repo is the proving ground for an automated dependency-upgrade pipeline whose verification step
runs the repo's own suite in a container against the upgraded dependencies. With no tests to
collect, that gate tolerated exit 5 and reported success — a dependency bump was declared
"verified" having executed nothing.

WHAT THESE TESTS ARE FOR. They exercise the one place this codebase touches `fastmcp`'s public
surface without needing a database, a network, or Keycloak: `create_mcp_http_app`, which calls
`FastMCP.http_app(path=..., transport="streamable-http")`. A fastmcp upgrade that renamed
`http_app`, dropped the `transport` keyword, removed the `streamable-http` literal, changed the
return type, or changed how the endpoint is routed would fail here. That is precisely the class
of breakage a dependency-upgrade PR needs to be caught by.

Measured against fastmcp 3.4.2, which this repo pins:
    http_app(path, middleware, json_response, stateless_http, transport, event_store,
             retry_interval) -> StarletteWithLifespan
    transport: Literal['http', 'streamable-http', 'sse'] = 'http'
"""

import pytest
from starlette.applications import Starlette

from fastmcp import FastMCP

from src.http_utils import create_mcp_http_app


@pytest.fixture
def mcp() -> FastMCP:
    return FastMCP("test-server")


def test_returns_a_starlette_application(mcp: FastMCP) -> None:
    """The ASGI adapter mounts this return value, so it must be a Starlette app."""
    app = create_mcp_http_app(mcp)
    assert isinstance(app, Starlette)


def test_mounts_at_the_default_mcp_path(mcp: FastMCP) -> None:
    """Clients are configured against /mcp; the default must not drift silently."""
    paths = {getattr(route, "path", None) for route in create_mcp_http_app(mcp).routes}
    assert "/mcp" in paths


def test_honours_a_custom_path(mcp: FastMCP) -> None:
    """The `path` argument must actually reach fastmcp rather than being ignored."""
    paths = {getattr(route, "path", None) for route in create_mcp_http_app(mcp, path="/custom").routes}
    assert "/custom" in paths
    assert "/mcp" not in paths


def test_uses_streamable_http_transport_and_not_sse(mcp: FastMCP) -> None:
    """The load-bearing contract: Streamable HTTP, not SSE.

    This is asserted through an OBSERVABLE difference rather than by inspecting the call
    arguments, which would only restate the implementation. Measured on fastmcp 3.4.2:
    the SSE transport registers a second route, `/messages`, for the client's POST channel;
    Streamable HTTP carries both directions over the single endpoint and registers no such
    route.

    The second assertion is the POSITIVE CONTROL and is the reason this test is worth having:
    it proves `/messages` genuinely appears when the transport IS SSE. Without it, the first
    assertion would also pass if fastmcp stopped registering `/messages` for every transport,
    i.e. the test could go vacuously green while verifying nothing.
    """
    streamable_paths = {getattr(r, "path", None) for r in create_mcp_http_app(mcp).routes}
    sse_paths = {getattr(r, "path", None) for r in mcp.http_app(path="/mcp", transport="sse").routes}

    assert "/messages" not in streamable_paths, (
        "create_mcp_http_app produced an SSE-shaped app; the transport argument regressed"
    )
    assert "/messages" in sse_paths, (
        "positive control failed: SSE no longer registers /messages on this fastmcp version, "
        "so the assertion above no longer discriminates and this test must be re-grounded"
    )
