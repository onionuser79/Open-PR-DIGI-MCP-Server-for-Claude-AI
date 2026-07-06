"""Chained AX.25 transport — outer xnet node → `C <inner>` → inner node.

Used for IW2OHX-12 (PC/Flexnet, packet-radio only), reachable only by
issuing `C IW2OHX-12` from IW2OHX-14's user prompt. The AX.25 SABM
carries the outer's user identity (iw7eas-1) through to the inner,
so the inner has no separate user-login step — only an optional SYS
elevation for write tools.

See DESIGN.md §6 for the full lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..config import NodeConfig
from ..credentials import get_password
from .xnet import SYS_REJECTED_MARKERS, XnetError, XnetTransport

logger = logging.getLogger(__name__)

# Patterns indicating the AX.25 connect was successful. xnet/PCF print
# "*** CONNECTED to <CALL>" on completion. Tolerate variants.
CONNECTED_BANNER = re.compile(rb"(?i)(\*\*\*\s*)?connected\s+to\s+", re.MULTILINE)
CONNECT_FAILED = re.compile(
    rb"(?i)(failure|failed|busy|no\s+route|unknown\s+node|"
    rb"link\s+failure|disconnected|retried\s+out)"
)


class Ax25ChainedTransport(XnetTransport):
    """Two-layer telnet+AX.25 session: SSH→telnet(outer)→`C inner`→inner.

    Subclasses `XnetTransport` so the tool surface (`run_command`,
    `elevate_sys`) is uniform. The base class handles SSH+telnet IO; this
    subclass adds the AX.25-chain step on connect, retargets SYS auth at
    the inner node's credentials, and tears down with a leading BYE so
    the inner session closes before the outer's BYE drops the AX.25 link.
    """

    def __init__(self, inner_config: NodeConfig, outer_config: NodeConfig) -> None:
        if inner_config.type != "xnet_chained":
            raise ValueError(
                f"Ax25ChainedTransport requires inner type='xnet_chained', got "
                f"{inner_config.type!r} for {inner_config.callsign!r}"
            )
        if outer_config.type == "xnet_chained":
            raise ValueError(
                f"outer node {outer_config.callsign!r} is itself chained — "
                f"multi-hop chains not supported"
            )
        # Initialise the base class with the OUTER's config so SSH+telnet
        # connect to the right host with the right credentials. The base
        # type check is satisfied because outer is always direct xnet.
        super().__init__(outer_config)
        self.inner_config = inner_config
        self.outer_config = outer_config

    async def connect(self) -> None:
        """Open the outer xnet session, then chain to the inner via `C`."""
        # 1. SSH + telnet + login to the outer.
        await super().connect()
        # 2. From the outer's user prompt (NO SYS on outer needed for transit),
        #    issue the chain command and wait for the connect banner.
        cmd = self.inner_config.connect_command
        logger.info(
            "chained connect: %s via %s (cmd=%r)",
            self.inner_config.callsign,
            self.outer_config.callsign,
            cmd,
        )
        async with self._lock:
            await self._send_line(cmd)
            buf: bytes = b""
            deadline_s = 30.0
            try:
                buf = await self._read_until(CONNECTED_BANNER, timeout=deadline_s)
            except TimeoutError as e:
                raise XnetError(
                    f"{self.inner_config.callsign}: no connect banner from "
                    f"{self.outer_config.callsign} within {deadline_s}s; "
                    f"link to inner may be down"
                ) from e
            if CONNECT_FAILED.search(buf):
                raise XnetError(
                    f"{self.inner_config.callsign}: outer reported connect "
                    f"failure: {buf!r}"
                )
            # Drain any motd / banner from the inner before returning.
            await self._read_until_idle(idle_ms=600, max_wait_s=10.0)
        logger.info(
            "%s reachable via %s",
            self.inner_config.callsign,
            self.outer_config.callsign,
        )

    async def elevate_sys(self) -> None:
        """SYS elevation on the INNER node — positional challenge against inner's pwd.

        Same challenge-response shape as direct xnet (see XnetTransport
        docstring), but the looked-up password is the inner node's, not
        the outer's. Identity attribution is taken care of by the SSH and
        AX.25 layers below; we just resolve the right positions here.
        """
        if self._sys_active:
            return
        async with self._lock:
            await self._send_line("SYS")
            challenge_buf = await self._read_until_idle(
                idle_ms=600, max_wait_s=10.0
            )
            sys_pwd = get_password(self.inner_config.callsign, "sys")
            response = self._resolve_chained_sys_challenge(
                challenge_buf.encode("latin-1", errors="ignore"), sys_pwd
            )
            await self._send_line(response)
            tail = await self._read_until_idle(idle_ms=600, max_wait_s=10.0)
            if SYS_REJECTED_MARKERS.search(tail.encode("latin-1", errors="ignore")):
                raise XnetError(
                    f"{self.inner_config.callsign}: SYS auth rejected on inner"
                )
            self._sys_active = True
            logger.info("%s: SYS elevated (chained)", self.inner_config.callsign)

    def _resolve_chained_sys_challenge(self, buf: bytes, sys_pwd: str) -> str:
        """Parse the inner node's SYS challenge and assemble the reply.

        Same shape as XnetTransport._resolve_sys_challenge but uses the
        explicitly-passed `sys_pwd` (the INNER's, not the OUTER's).
        """
        # Defer to the base class's pattern by importing it locally.
        from .xnet import SYS_CHALLENGE

        match = SYS_CHALLENGE.search(buf)
        if not match:
            preview = buf[-200:].decode("latin-1", errors="replace")
            raise XnetError(
                f"{self.inner_config.callsign}: no SYS challenge in response "
                f"(last bytes: {preview!r})"
            )
        positions = [int(p) for p in match.group(1).split()]
        try:
            return "".join(sys_pwd[p - 1] for p in positions)
        except IndexError as e:
            raise XnetError(
                f"{self.inner_config.callsign}: SYS challenge positions "
                f"{positions} exceed configured password length ({len(sys_pwd)})"
            ) from e

    async def disconnect(self) -> None:
        """BYE on inner first, then let the base class BYE the outer."""
        if self._writer is not None and not self._writer.is_closing():
            try:
                async with self._lock:
                    # Drop the chained inner; we should land back at the outer's prompt.
                    await self._send_line("BYE")
                    # Let the AX.25 disconnect propagate before BYEing the outer.
                    await asyncio.sleep(0.5)
            except (XnetError, ConnectionError, OSError, asyncio.TimeoutError):
                pass  # best-effort; super().disconnect() still closes the channels
        self._sys_active = False
        await super().disconnect()
