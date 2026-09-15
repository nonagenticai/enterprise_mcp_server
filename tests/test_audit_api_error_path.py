"""Behavioural barrier for `get_audit_logs`'s except-handler in `src/audit_api.py`.

WHY THIS FILE EXISTS. The handler ended with

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, ...)

in a module that never imported `fastapi.status`, inside a function that declares a query
parameter literally named `status`. So the name resolved to the PARAMETER -- `None` on any
request that omits the filter -- and every failure of `audit_service.get_logs()` raised
`AttributeError: 'NoneType' object has no attribute 'HTTP_500_INTERNAL_SERVER_ERROR'`
instead of the 500 the code was written to return. The operator-facing `detail` was
destroyed and the traceback named the wrong fault.

`checks/http_status_binding.py` catches the binding statically. This file catches the
BEHAVIOUR, which is a different claim: a static walker is satisfied by any name that
resolves, including one that resolves to the wrong thing, and would be satisfied by a bare
literal `500` that silently dropped the detail. The assertion here is that a failing
service produces an HTTP 500 response carrying the detail -- not an unhandled exception.

HOW TO CONFIRM IT CAN FAIL: revert the fix (re-point :145 at the shadowed `status`) and
`test_failure_path_returns_a_clean_500` errors with the AttributeError above, because
`TestClient` re-raises an unhandled server exception rather than turning it into a 500.
`test_success_path_returns_200` is the paired control: it proves a 500 in that test came
from the error path under test and not from a mis-wired app or a broken dependency
override, which would red both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.audit_api import router as audit_router

BOOM = "simulated audit store failure"

_ONE_LOG: dict[str, Any] = {
    "id": 1,
    "timestamp": datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC),
    "actor_id": 7,
    "actor_type": "human",
    "action_type": "read",
    "resource_type": "audit_logs",
    "resource_id": None,
    "status": "success",
    "details": None,
    "request_id": None,
    "ip_address": None,
}


class _FakeAuditService:
    """Stands in for AuditLogService. Only the two methods the route calls."""

    def __init__(self, *, get_logs_error: Exception | None = None) -> None:
        self._get_logs_error = get_logs_error
        self.events: list[dict[str, Any]] = []

    async def get_logs(self, **kwargs: Any) -> list[dict[str, Any]]:
        if self._get_logs_error is not None:
            raise self._get_logs_error
        return [_ONE_LOG]

    async def log_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _logs_route(app: FastAPI) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/audit/logs":
            return route
    raise AssertionError("GET /audit/logs is not mounted; the router shape changed")


def _permission_dependency(route: APIRoute):
    """The `requires_permission('log:read')` closure, fetched from the live route.

    It is created at import time by a factory, so calling the factory again would produce a
    DIFFERENT object and `dependency_overrides` -- which keys on identity -- would miss it
    and the real auth chain would run. Taking it off the route is the only sound key.
    """
    for dep in route.dependant.dependencies:
        if getattr(dep.call, "__name__", "") == "permission_dependency":
            return dep.call
    raise AssertionError(
        "no requires_permission(...) dependency on GET /audit/logs; auth wiring changed"
    )


def _client(service: _FakeAuditService) -> TestClient:
    app = FastAPI()
    app.include_router(audit_router, prefix="/audit")
    # `get_audit_service` is NOT overridden: it is exercised for real, reading
    # `request.app.state.audit_service` exactly as `src/asgi.py` populates it.
    app.state.audit_service = service
    app.dependency_overrides[_permission_dependency(_logs_route(app))] = lambda: {
        "id": 7,
        "type": "user",
    }
    return TestClient(app)


def test_success_path_returns_200() -> None:
    """Control: without it, a red failure-path test could just mean a broken app."""
    service = _FakeAuditService()
    resp = _client(service).get("/audit/logs")
    assert resp.status_code == 200, resp.text
    assert [row["id"] for row in resp.json()] == [1]
    # the route meta-logs its own read, so the success branch really executed
    assert [e["status"] for e in service.events] == ["success"]


def test_failure_path_returns_a_clean_500() -> None:
    """The mutant this file kills: `status.HTTP_500_...` bound to the query parameter."""
    service = _FakeAuditService(get_logs_error=RuntimeError(BOOM))
    resp = _client(service).get("/audit/logs")
    assert resp.status_code == 500, resp.text
    # the detail is the thing the AttributeError destroyed, so assert it survived
    assert BOOM in resp.json()["detail"]
    assert [e["status"] for e in service.events] == ["failure"]


@pytest.mark.parametrize("query", [{}, {"status": "failure"}])
def test_failure_path_is_500_whether_or_not_the_status_filter_is_sent(
    query: dict[str, str],
) -> None:
    """The shadowed name was `None` only when the filter was omitted.

    With `?status=failure` the shadowed attribute lookup would have been `str.HTTP_500_...`
    -- still an AttributeError, but a DIFFERENT one. Both spellings are pinned so a partial
    fix cannot pass on one of them.
    """
    service = _FakeAuditService(get_logs_error=RuntimeError(BOOM))
    resp = _client(service).get("/audit/logs", params=query)
    assert resp.status_code == 500, resp.text
    assert BOOM in resp.json()["detail"]


def test_the_public_query_parameter_is_still_named_status() -> None:
    """Guards the constraint the fix had to respect.

    Renaming the Python parameter would also have removed the shadowing, and would also
    have satisfied the static check -- while breaking every external caller. This pins the
    WIRE name, so that remedy cannot be reintroduced silently.
    """
    app = FastAPI()
    app.include_router(audit_router, prefix="/audit")
    params = app.openapi()["paths"]["/audit/logs"]["get"]["parameters"]
    assert "status" in {p["name"] for p in params}
