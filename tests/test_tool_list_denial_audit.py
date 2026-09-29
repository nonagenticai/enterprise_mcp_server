"""Regression test: `GET /tools/list` without `tool:read` must answer 403 and audit the denial.

The denial branch of `list_tools` in `src/tool_management_api.py` once called
`audit_service.log_event(...)` without `resource_id`, a required argument of
`AuditLogService.log_event`. The call raised `TypeError`, so a caller lacking permission got
a 500 instead of the intended 403 and the denial was never written to the audit log.

The fake audit service below enforces the REAL `AuditLogService.log_event` signature via
`inspect.signature(...).bind`, so dropping a required argument again fails this test instead
of being absorbed by a permissive `**kwargs` stub.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.audit import AuditLogService
from src.auth import get_current_user
from src.dependencies import get_audit_service, get_auth_service, get_tool_registry
from src.tool_management_api import router as tools_router

_LOG_EVENT_SIGNATURE = inspect.signature(AuditLogService.log_event)


class _SignatureCheckedAuditService:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def log_event(self, *args: Any, **kwargs: Any) -> int:
        # Raises TypeError exactly as the real method would on a missing argument.
        bound = _LOG_EVENT_SIGNATURE.bind(self, *args, **kwargs)
        self.events.append(dict(bound.arguments))
        return len(self.events)


class _AuthService:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed

    async def check_permission(self, user_id: Any, permission: str) -> bool:
        return self._allowed


class _Registry:
    async def get_tools(self) -> dict[str, Any]:
        return {}


def _client(audit: _SignatureCheckedAuditService, *, allowed: bool) -> TestClient:
    app = FastAPI()
    app.include_router(tools_router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 7,
        "actor_type": "human",
    }
    app.dependency_overrides[get_auth_service] = lambda: _AuthService(allowed=allowed)
    app.dependency_overrides[get_audit_service] = lambda: audit
    app.dependency_overrides[get_tool_registry] = lambda: _Registry()
    # Surface an unhandled server error as a 500 response rather than re-raising it,
    # so the assertion reads as the status code a real caller would see.
    return TestClient(app, raise_server_exceptions=False)


def _list_path(app_client: TestClient) -> str:
    for route in app_client.app.routes:
        if (
            getattr(route, "path", "").endswith("/list")
            and getattr(route, "name", "") == "list_tools"
        ):
            return route.path
    raise AssertionError("list_tools route is not mounted; the router shape changed")


def test_list_tools_denied_returns_403_and_audits_the_denial() -> None:
    audit = _SignatureCheckedAuditService()
    client = _client(audit, allowed=False)
    resp = client.get(_list_path(client))
    assert resp.status_code == 403, resp.text
    assert [(e["action_type"], e["status"]) for e in audit.events] == [
        ("list_tools", "denied")
    ]


def test_list_tools_allowed_returns_200() -> None:
    """Control: a 403/500 in the test above is not a mis-wired app."""
    audit = _SignatureCheckedAuditService()
    client = _client(audit, allowed=True)
    resp = client.get(_list_path(client))
    assert resp.status_code == 200, resp.text
    assert [e["status"] for e in audit.events] == ["success"]
