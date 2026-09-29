"""Regression test: auth-exempt path prefixes must match on a path-segment boundary.

`KeycloakAuthMiddleware._is_excluded_path` once used a raw `startswith`, so any path that
merely began with an exempt prefix (`/docsabc`, `/static-x`, `/openapi.json.bak`) skipped
authentication. A prefix now exempts only the prefix itself or paths below it (`prefix/...`).
The test drives the real middleware: an exempt path reaches the app, a non-exempt path
without a token gets 401.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.keycloak_auth import middleware as mw


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Force authentication ON regardless of the environment, and keep the validator offline:
    # no request in this file carries a token, so it is never called.
    monkeypatch.setattr(
        mw, "get_keycloak_settings", lambda: SimpleNamespace(auth_enabled=True)
    )
    monkeypatch.setattr(mw, "get_token_validator", lambda: SimpleNamespace())
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.api_route("/{path:path}", methods=["GET"])
    async def _echo(path: str) -> dict[str, str]:
        return {"reached": path}

    app.add_middleware(mw.KeycloakAuthMiddleware)
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/docsabc",
        "/docs-internal",
        "/redocxyz",
        "/static-x",
        "/staticfiles/a",
        "/openapi.json.bak",
    ],
)
def test_lookalike_prefix_requires_auth(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/docs",
        "/docs/",
        "/docs/x",
        "/redoc",
        "/static/app.js",
        "/openapi.json",
        "/health",
    ],
)
def test_exempt_paths_skip_auth(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
