"""Regression test: OAuth client registration must check the redirect URI's parsed HOST.

`register_client` in `src/api.py` once accepted any URI that merely started with the string
`http://localhost`, so `http://localhost.evil.example/cb` -- a non-loopback host over plain
HTTP -- was registered. Plain-HTTP redirect URIs are allowed only when the parsed hostname is
a loopback name; everything else must be HTTPS.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from src.api import ClientRegistration, register_client


class _FakeDB:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def save_oauth_client(self, client: dict[str, Any]) -> None:
        self.saved.append(client)


def _register(uri: str) -> tuple[_FakeDB, dict[str, Any]]:
    db = _FakeDB()
    result = asyncio.run(
        register_client(
            ClientRegistration(client_name="t", redirect_uris=[uri]),
            current_user={"id": 1},
            db=db,
        )
    )
    return db, result


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost.evil.example/cb",
        "http://localhostx.evil.example/cb",
        "http://localhost@evil.example/cb",
        "http://evil.example/cb",
    ],
)
def test_non_loopback_http_redirect_is_rejected(uri: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _register(uri)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "uri",
    [
        "https://app.example/cb",
        "http://localhost/cb",
        "http://localhost:8080/cb",
        "http://127.0.0.1:9000/cb",
        "http://[::1]:9000/cb",
    ],
)
def test_https_and_loopback_redirects_are_accepted(uri: str) -> None:
    db, result = _register(uri)
    assert result["redirect_uris"] == [uri]
    assert len(db.saved) == 1
