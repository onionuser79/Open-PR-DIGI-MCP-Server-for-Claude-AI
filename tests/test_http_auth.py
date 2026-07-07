"""Bearer-token middleware + HTTP token-loading tests. Pure ASGI, no network."""

from __future__ import annotations

from typing import Any

import pytest

import pr_digi_mcp.credentials as creds
from pr_digi_mcp.http_auth import BearerAuthMiddleware

TOKEN = "s3cret-token"


async def _ok_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _invoke(mw: BearerAuthMiddleware, auth: str | None) -> list[dict[str, Any]]:
    headers = [(b"authorization", auth.encode())] if auth is not None else []
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers}
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    await mw(scope, receive, send)
    return sent


def _status(sent: list[dict[str, Any]]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


async def test_no_auth_header_rejected() -> None:
    assert _status(await _invoke(BearerAuthMiddleware(_ok_app, {TOKEN}), None)) == 401


async def test_wrong_token_rejected() -> None:
    assert _status(await _invoke(BearerAuthMiddleware(_ok_app, {TOKEN}), "Bearer nope")) == 401


async def test_non_bearer_scheme_rejected() -> None:
    assert _status(await _invoke(BearerAuthMiddleware(_ok_app, {TOKEN}), "Basic abc")) == 401


async def test_valid_token_passes() -> None:
    sent = await _invoke(BearerAuthMiddleware(_ok_app, {TOKEN}), f"Bearer {TOKEN}")
    assert _status(sent) == 200
    assert any(m.get("body") == b"ok" for m in sent)


async def test_bearer_scheme_case_insensitive() -> None:
    sent = await _invoke(BearerAuthMiddleware(_ok_app, {TOKEN}), f"bearer {TOKEN}")
    assert _status(sent) == 200


async def test_empty_token_set_rejects_all() -> None:
    assert _status(await _invoke(BearerAuthMiddleware(_ok_app, set()), "Bearer x")) == 401


async def test_non_http_scope_passes_through() -> None:
    seen: dict[str, Any] = {}

    async def spy(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen["type"] = scope["type"]

    async def r() -> dict[str, Any]:
        return {}

    async def s(msg: dict[str, Any]) -> None:
        return None

    await BearerAuthMiddleware(spy, {TOKEN})({"type": "lifespan"}, r, s)
    assert seen["type"] == "lifespan"  # forwarded, never auth-checked


def test_get_http_tokens_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_DIGI_MCP_HTTP_TOKENS", " a , b ,")
    monkeypatch.setattr(creds, "_keyring_get_with_timeout", lambda *a, **k: None)
    assert creds.get_http_tokens() == {"a", "b"}


def test_get_http_tokens_none_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PR_DIGI_MCP_HTTP_TOKENS", raising=False)
    monkeypatch.setattr(creds, "_keyring_get_with_timeout", lambda *a, **k: None)
    with pytest.raises(LookupError):
        creds.get_http_tokens()
