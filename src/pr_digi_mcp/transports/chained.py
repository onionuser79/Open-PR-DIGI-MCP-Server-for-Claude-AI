"""Chained AX.25 transport — base node → `C <hop>` … → target node.

For nodes reachable only over RF/AX.25 via one or more transit hops. The
transport logs into a **base direct node**, then issues an ordered list of
`C …` connect commands (one per hop) until the target is reached. The AX.25
SABM carries the base's user identity through, so the target has no separate
user-login step — only an optional SYS elevation for write tools.

Single-hop (`transit_via` → a direct node) and multi-hop (`transit_via` → another
chained node) are both supported; the connect path is resolved by
`config.resolve_chain()`.
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..config import NodeConfig
from ..credentials import get_password
from .xnet import SYS_REJECTED_MARKERS, XnetError, XnetTransport

logger = logging.getLogger(__name__)

# xnet/PCF print "*** CONNECTED to <CALL>" on a successful connect. Tolerate variants.
CONNECTED_BANNER = re.compile(rb"(?i)(\*\*\*\s*)?connected\s+to\s+", re.MULTILINE)
CONNECT_FAILED = re.compile(
    rb"(?i)(failure|failed|busy|no\s+route|unknown\s+node|"
    rb"link\s+failure|disconnected|retried\s+out)"
)


class Ax25ChainedTransport(XnetTransport):
    """Telnet + one-or-more AX.25 hops: base → `C hop1` → … → target.

    Subclasses `XnetTransport` so the tool surface (`run_command`, `elevate_sys`)
    is uniform. The base class handles SSH/telnet IO + base login; this subclass
    walks the connect path on connect, retargets SYS auth at the target node's
    credentials, and tears down with a leading BYE.
    """

    def __init__(
        self,
        target_config: NodeConfig,
        base_config: NodeConfig,
        connect_commands: list[str],
    ) -> None:
        if target_config.type != "xnet_chained":
            raise ValueError(
                f"Ax25ChainedTransport requires target type='xnet_chained', got "
                f"{target_config.type!r} for {target_config.callsign!r}"
            )
        if base_config.type == "xnet_chained":
            raise ValueError(
                f"base node {base_config.callsign!r} is itself chained — the base "
                f"must be a direct node"
            )
        if not connect_commands:
            raise ValueError(
                f"chained node {target_config.callsign!r}: empty connect path"
            )
        # Initialise the base class with the BASE (direct) node's config so
        # SSH+telnet+login use the right host/credentials.
        super().__init__(base_config)
        self.target_config = target_config
        self.base_config = base_config
        self.connect_commands = connect_commands

    async def connect(self) -> None:
        """Open the base session, then walk the AX.25 connect path to the target."""
        await super().connect()  # SSH/telnet + base login
        logger.info(
            "chained connect: %s via %s (%d hop(s))",
            self.target_config.callsign,
            self.base_config.callsign,
            len(self.connect_commands),
        )
        async with self._lock:
            for i, cmd in enumerate(self.connect_commands, start=1):
                await self._send_line(cmd)
                try:
                    buf = await self._read_until(CONNECTED_BANNER, timeout=30.0)
                except TimeoutError as e:
                    raise XnetError(
                        f"{self.target_config.callsign}: no connect banner for "
                        f"hop {i} ({cmd!r}) within 30s; link may be down"
                    ) from e
                if CONNECT_FAILED.search(buf):
                    raise XnetError(
                        f"{self.target_config.callsign}: connect failure on "
                        f"hop {i} ({cmd!r}): {buf!r}"
                    )
                # Drain any motd/banner from this hop before the next command.
                await self._read_until_idle(idle_ms=600, max_wait_s=10.0)
        logger.info(
            "%s reachable via %s",
            self.target_config.callsign,
            self.base_config.callsign,
        )

    async def elevate_sys(self) -> None:
        """SYS elevation on the TARGET node — positional challenge vs target's pwd."""
        if self._sys_active:
            return
        async with self._lock:
            await self._send_line("SYS")
            challenge_buf = await self._read_until_idle(idle_ms=600, max_wait_s=10.0)
            sys_pwd = get_password(self.target_config.callsign, "sys")
            response = self._resolve_chained_sys_challenge(
                challenge_buf.encode("latin-1", errors="ignore"), sys_pwd
            )
            await self._send_line(response)
            tail = await self._read_until_idle(idle_ms=600, max_wait_s=10.0)
            if SYS_REJECTED_MARKERS.search(tail.encode("latin-1", errors="ignore")):
                raise XnetError(
                    f"{self.target_config.callsign}: SYS auth rejected on target"
                )
            self._sys_active = True
            logger.info("%s: SYS elevated (chained)", self.target_config.callsign)

    def _resolve_chained_sys_challenge(self, buf: bytes, sys_pwd: str) -> str:
        """Parse the target node's SYS challenge and assemble the reply."""
        from .xnet import SYS_CHALLENGE

        match = SYS_CHALLENGE.search(buf)
        if not match:
            preview = buf[-200:].decode("latin-1", errors="replace")
            raise XnetError(
                f"{self.target_config.callsign}: no SYS challenge in response "
                f"(last bytes: {preview!r})"
            )
        positions = [int(p) for p in match.group(1).split()]
        try:
            return "".join(sys_pwd[p - 1] for p in positions)
        except IndexError as e:
            raise XnetError(
                f"{self.target_config.callsign}: SYS challenge positions "
                f"{positions} exceed configured password length ({len(sys_pwd)})"
            ) from e

    async def disconnect(self) -> None:
        """BYE the innermost link, then let the base class BYE the base + close.

        A single BYE drops the innermost AX.25 hop; intermediate hops (base→…)
        fall back on their own inactivity timeout once the telnet session closes.
        """
        if self._writer is not None and not self._writer.is_closing():
            try:
                async with self._lock:
                    await self._send_line("BYE")
                    await asyncio.sleep(0.5)  # let the AX.25 disconnect propagate
            except (XnetError, ConnectionError, OSError, asyncio.TimeoutError):
                pass  # best-effort; super().disconnect() still closes the channels
        self._sys_active = False
        await super().disconnect()
