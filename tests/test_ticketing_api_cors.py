"""Regression barrier for examples/ticketing_api.py's CORS configuration.

WHY THIS FILE EXISTS. The fix it guards replaced `allow_origins=["*"]` (paired with
`allow_credentials=True`) with an env-driven allow-list. That pairing is a real
vulnerability, not a theoretical one: measured on the pinned starlette, a wildcard plus
credentials echoes `Access-Control-Allow-Origin: http://evil.example` together with
`Access-Control-Allow-Credentials: true` for a cookie-bearing request.

⚠️ Before this file, NOTHING in CI could see that. `pyproject.toml` sets
`testpaths = ["tests"]` and `tests/` held a single module exercising `src.http_utils`;
`compile` only parses; `smoke` never installs the project. So all three checks stayed green
whether the wildcard was present or absent — re-inserting it would have been invisible.

The wildcard test below is a POSITIVE CONTROL, and it is the load-bearing half: it proves the
assertion in `test_unlisted_origin_is_not_echoed` can actually fail. Without it, a passing
suite would be indistinguishable from a suite that cannot detect anything.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

EVIL = "http://evil.example"
ALLOWED = "http://allowed.example"


def _reimport_with_env(monkeypatch: pytest.MonkeyPatch, value: str):
    """Import examples.ticketing_api fresh under a given CORS_ALLOWED_ORIGINS."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", value)
    sys.modules.pop("examples.ticketing_api", None)
    return importlib.import_module("examples.ticketing_api")


def _cors_kwargs(app: FastAPI) -> dict:
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return dict(mw.kwargs)
    raise AssertionError("no CORSMiddleware is installed on the app")


def test_origins_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _reimport_with_env(monkeypatch, f"{ALLOWED}, http://second.example ")
    assert mod._cors_allowed_origins == [ALLOWED, "http://second.example"]
    # whitespace is stripped and empties dropped, so a trailing comma cannot widen the list
    assert "" not in mod._cors_allowed_origins


def test_the_wildcard_is_gone_from_the_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutant this file exists to kill: re-inserting allow_origins=["*"]."""
    mod = _reimport_with_env(monkeypatch, ALLOWED)
    kwargs = _cors_kwargs(mod.app)
    assert kwargs["allow_origins"] == [ALLOWED]
    assert "*" not in kwargs["allow_origins"]
    # the credentials flag is what makes a wildcard dangerous; it is still on, by design,
    # which is exactly why the origin list must stay closed.
    assert kwargs["allow_credentials"] is True


def test_unlisted_origin_is_not_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _reimport_with_env(monkeypatch, ALLOWED)
    client = TestClient(mod.app)
    resp = client.get("/health", headers={"Origin": EVIL})
    assert resp.headers.get("access-control-allow-origin") != EVIL


def test_positive_control_a_wildcard_WOULD_echo_an_arbitrary_origin() -> None:
    """If this ever fails, the assertion above has stopped being discriminating."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def _health() -> dict[str, str]:
        return {"status": "ok"}

    resp = TestClient(app).get("/health", headers={"Origin": EVIL})
    assert resp.headers.get("access-control-allow-origin") == EVIL
    assert resp.headers.get("access-control-allow-credentials") == "true"
