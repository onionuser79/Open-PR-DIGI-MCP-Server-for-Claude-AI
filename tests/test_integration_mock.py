"""End-to-end integration tests against an in-process mock node server.

No real hardware, no SSH: a real asyncio TCP server speaks a minimal
(X)Net / BPQ-style protocol (login prompt → user → password → banner →
prompt; `SYS` positional challenge; BPQ `PASSWORD` 5-number challenge;
canned command output; `BYE`). The transports connect to it via the new
**direct** path (`ssh_host` unset), exercising connect → login → SYS
elevation → command → disconnect for real.

This is the substitute for validating against a second physical station.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

import pr_digi_mcp.transports.bpq as bpq_mod
import pr_digi_mcp.transports.chained as chained_mod
import pr_digi_mcp.transports.xnet as xnet_mod
from pr_digi_mcp.config import NodeConfig
from pr_digi_mcp.transports.bpq import BpqTransport
from pr_digi_mcp.transports.chained import Ax25ChainedTransport
from pr_digi_mcp.transports.xnet import XnetTransport

USER_PWD = "userpass"
SYS_PWD = "SECRETSYSPWD012345"  # length 18 — long enough for all challenge positions
PROMPT = b"MOCK>\r\n"

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


async def _read_cr(reader: asyncio.StreamReader) -> bytes | None:
    """Read one carriage-return-terminated line (LF ignored). None on EOF."""
    buf = bytearray()
    while True:
        ch = await reader.read(1)
        if not ch:
            return None
        if ch == b"\r":
            return bytes(buf)
        if ch == b"\n":
            continue
        buf += ch


def _make_handler(mode: str, login: bool = True) -> Handler:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def send(data: bytes) -> None:
            writer.write(data)
            await writer.drain()

        try:
            if login:
                await send(b"login: ")
                await _read_cr(reader)  # username (not validated by the mock)
                await send(b"password: ")
                await _read_cr(reader)  # password (not validated by the mock)
            await send(b"*** Welcome to MOCK node\r\n" + PROMPT)

            while True:
                line = await _read_cr(reader)
                if line is None:
                    break
                cmd = line.strip().decode("latin-1", "ignore").upper()
                if cmd == "BYE":
                    await send(b"73\r\n")
                    break
                elif cmd == "SYS":  # (X)Net-style positional challenge
                    await send(b"MOCK>  2 4 1 3 5\r\n")
                    resp = await _read_cr(reader) or b""
                    want = "".join(SYS_PWD[i - 1] for i in (2, 4, 1, 3, 5)).encode()
                    ok = resp.strip() == want
                    await send((b"SYS active\r\n" if ok else b"invalid\r\n") + PROMPT)
                elif cmd == "PASSWORD":  # BPQ-style 5-number challenge
                    await send(b"05 10 03 07 04\r\n")
                    resp = await _read_cr(reader) or b""
                    want = "".join(SYS_PWD[i - 1] for i in (5, 10, 3, 7, 4)).encode()
                    ok = resp.strip() == want
                    await send((b"Ok\r\n" if ok else b"Sorry\r\n") + PROMPT)
                elif cmd.startswith("C "):  # AX.25 chain hop
                    await send(b"*** CONNECTED to NODE\r\n" + PROMPT)
                elif cmd == "L":
                    await send(b"Link table\r\nAAA-1  BBB-2\r\n" + PROMPT)
                else:
                    await send(b"?\r\n" + PROMPT)
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    return handler


@contextlib.asynccontextmanager
async def _serve(mode: str, login: bool = True) -> AsyncIterator[int]:
    server = await asyncio.start_server(_make_handler(mode, login), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        await server.start_serving()
        yield port


def _direct_cfg(node_type: str, port: int) -> NodeConfig:
    """A direct-access node config (no ssh_host) pointing at the mock."""
    return NodeConfig(
        callsign="TEST-1",
        type=node_type,
        sys_required=True,
        ssh_host="",  # <- direct path: no SSH jump
        telnet_host="127.0.0.1",
        telnet_port=port,
        user="tester",
    )


def _patch_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_password(callsign: str, which: str) -> str:
        return USER_PWD if which == "user" else SYS_PWD

    monkeypatch.setattr(xnet_mod, "get_password", fake_get_password)
    monkeypatch.setattr(bpq_mod, "get_password", fake_get_password)
    monkeypatch.setattr(chained_mod, "get_password", fake_get_password)


async def test_xnet_direct_login_and_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_creds(monkeypatch)
    async with _serve("xnet") as port:
        async with XnetTransport(_direct_cfg("xnet", port)) as xn:
            out = await xn.run_command("L", idle_ms=200, max_wait_s=5.0)
    assert "Link table" in out
    assert "BBB-2" in out


async def test_xnet_direct_sys_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_creds(monkeypatch)
    async with _serve("xnet") as port:
        async with XnetTransport(_direct_cfg("xnet", port)) as xn:
            await xn.elevate_sys()
            assert xn._sys_active is True
            # idempotent
            await xn.elevate_sys()


async def test_xnet_sys_wrong_password_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_pwd(callsign: str, which: str) -> str:
        return USER_PWD if which == "user" else "WRONGWRONGWRONG000"

    monkeypatch.setattr(xnet_mod, "get_password", bad_pwd)
    async with _serve("xnet") as port:
        async with XnetTransport(_direct_cfg("xnet", port)) as xn:
            with pytest.raises(xnet_mod.XnetError):
                await xn.elevate_sys()


async def test_bpq_direct_password_elevation(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_creds(monkeypatch)
    async with _serve("bpq") as port:
        async with BpqTransport(_direct_cfg("linbpq", port)) as bp:
            await bp.elevate_sys()
            assert bp._sys_active is True
            out = await bp.run_command("L", idle_ms=200, max_wait_s=5.0)
    assert "Link table" in out


async def test_open_node_no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """login_required=False: connect + command with no login exchange."""
    _patch_creds(monkeypatch)
    async with _serve("xnet", login=False) as port:
        cfg = NodeConfig(
            callsign="OPEN-1",
            type="xnet",
            sys_required=False,
            ssh_host="",
            telnet_host="127.0.0.1",
            telnet_port=port,
            user="",
            login_required=False,
        )
        async with XnetTransport(cfg) as xn:
            out = await xn.run_command("L", idle_ms=200, max_wait_s=5.0)
    assert "Link table" in out


async def test_chained_multi_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-hop chain: base → C MID → C FAR → run a command on the target."""
    _patch_creds(monkeypatch)
    async with _serve("xnet") as port:
        base = _direct_cfg("xnet", port)  # base direct node (logs in)
        target = NodeConfig(
            callsign="FAR",
            type="xnet_chained",
            sys_required=True,
            transit_via="MID",
            connect_command="C FAR",
        )
        async with Ax25ChainedTransport(target, base, ["C MID", "C FAR"]) as ch:
            out = await ch.run_command("L", idle_ms=200, max_wait_s=5.0)
    assert "Link table" in out
