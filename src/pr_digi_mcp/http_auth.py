"""Bearer-token ASGI middleware for the authenticated Streamable-HTTP transport.

A **pure-ASGI** wrapper (deliberately *not* Starlette's `BaseHTTPMiddleware`,
which buffers the response body and would break MCP's streaming/SSE responses).
Non-HTTP scopes (`lifespan`, `websocket`) pass straight through so the wrapped
app's session-manager lifespan still runs.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class BearerAuthMiddleware:
    """Reject HTTP requests lacking a valid ``Authorization: Bearer <token>``.

    `tokens` is the set of accepted bearer tokens; any one grants access.
    Comparison is constant-time per token.
    """

    def __init__(self, app: Any, tokens: set[str]) -> None:
        self.app = app
        self._tokens = frozenset(tokens)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)  # lifespan / websocket pass-through
            return
        if self._authorized(dict(scope.get("headers") or [])):
            await self.app(scope, receive, send)
            return
        await self._reject(send)

    def _authorized(self, headers: dict[bytes, bytes]) -> bool:
        raw = headers.get(b"authorization", b"").decode("latin-1")
        prefix = "bearer "
        if raw[: len(prefix)].lower() != prefix:
            return False
        token = raw[len(prefix):].strip()
        # OR over constant-time comparisons; empty token set -> always False.
        return any(secrets.compare_digest(token, valid) for valid in self._tokens)

    async def _reject(self, send: Send) -> None:
        body = b'{"error":"unauthorized"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
        logger.warning("rejected unauthenticated HTTP request")
