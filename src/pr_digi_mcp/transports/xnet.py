"""(X)Net transport: telnet to a node, optionally tunnelled over an SSH jump host.

Flow (ssh_host set):
    client → ssh <jump host> → open-tcp-channel(telnet_host, port) → telnet stream
Flow (ssh_host empty — direct):
    client → TCP connect telnet_host:port → telnet stream
    → login(user, user_pwd) → optional `SYS` + sys_pwd elevation → run commands

Connection lifecycle is `async with XnetTransport(cfg) as xn`. Login happens
in `__aenter__`; `BYE` + close happens in `__aexit__`.

`run_command()` returns raw text. Higher-level parsers live in `parsers/`
(future work — for v0.1 the LLM consumes the raw text directly).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Final

import asyncssh

from ..config import NodeConfig
from ..credentials import get_password
from .family import detect_family

logger = logging.getLogger(__name__)

# Prompt patterns are case-insensitive. The trailing punctuation must be
# permissive — xnet's user prompt is typically the node alias + "}" or ">",
# its SYS prompt is "=>", and login prompts vary.
LOGIN_PROMPTS: Final = re.compile(
    rb"(?i)\b(login|user(name)?|name|callsign)\s*[:>]\s*$"
)
PASSWORD_PROMPTS: Final = re.compile(rb"(?i)password\s*[:>]\s*$")
LOGIN_FAILED: Final = re.compile(
    rb"(?i)(login\s+(incorrect|failed)|invalid|denied|bad\s+password)"
)

# xnet/PCF SYS challenge: after typing `SYS`, the server prints a line like
#   "IW2OHX>  10 6 4 3 1"  (node name + space-separated 1-indexed positions
#   into the SYS password). The client must reply with the corresponding
#   characters concatenated, no spaces.
SYS_CHALLENGE: Final = re.compile(
    rb"^\s*\S+>\s+(\d+(?:\s+\d+){2,})\s*$", re.MULTILINE
)

# After a wrong SYS reply, xnet typically just returns to the user prompt
# without an explicit error. Detect post-SYS by attempting a SYS-only call.
SYS_REJECTED_MARKERS: Final = re.compile(rb"(?i)(no\s+sysop|denied|invalid)")


class XnetError(Exception):
    """Raised for protocol/transport failures on an xnet session."""


class XnetTransport:
    """Async SSH-tunnelled telnet session to an (X)Net node."""

    # Subclasses (e.g. BPQ, chained) override this to accept their own
    # node types. The base class accepts only direct xnet.
    _ACCEPTED_TYPES: frozenset[str] = frozenset({"xnet"})

    def __init__(self, config: NodeConfig) -> None:
        if config.type not in self._ACCEPTED_TYPES:
            raise ValueError(
                f"{type(self).__name__} requires type in "
                f"{sorted(self._ACCEPTED_TYPES)}, got '{config.type}' "
                f"for {config.callsign!r}"
            )
        self.config = config
        self._ssh: asyncssh.SSHClientConnection | None = None
        # asyncssh.open_connection returns SSH stream objects (not asyncio's),
        # but the subset we use (read/write/drain/close/is_closing) is shared.
        self._reader: asyncssh.SSHReader[bytes] | asyncio.StreamReader | None = None
        self._writer: asyncssh.SSHWriter[bytes] | asyncio.StreamWriter | None = None
        self._sys_active: bool = False
        self._lock = asyncio.Lock()  # serialises send/receive on this session
        # Connect banner / MOTD captured on connect, for family recognition.
        self.motd: str = ""
        self.family: str | None = None

    async def __aenter__(self) -> XnetTransport:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Open SSH, tunnel a TCP channel to the telnet port, then log in."""
        if self.config.ssh_host:
            logger.info(
                "xnet connect: %s via ssh %s → telnet %s:%d",
                self.config.callsign,
                self.config.ssh_host,
                self.config.telnet_host,
                self.config.telnet_port,
            )
            self._ssh = await asyncssh.connect(
                self.config.ssh_host,
                known_hosts=None,  # rely on user's ~/.ssh/known_hosts via asyncssh
            )
            self._reader, self._writer = await self._ssh.open_connection(
                self.config.telnet_host, self.config.telnet_port
            )
        else:
            logger.info(
                "xnet connect: %s → direct telnet %s:%d (no ssh jump)",
                self.config.callsign,
                self.config.telnet_host,
                self.config.telnet_port,
            )
            self._reader, self._writer = await asyncio.open_connection(
                self.config.telnet_host, self.config.telnet_port
            )
        await self._login()

    async def probe_family(self) -> str:
        """Recognise the node family from the MOTD, falling back to the `V` command.

        Returns one of "xnet" | "bpq" | "pcf" | "unknown" and caches it on
        `self.family`. Best-effort: a failed `V` probe yields "unknown" rather
        than raising, so a caller can still run generic single-letter commands.
        """
        fam = detect_family(self.motd)
        if fam is None:
            try:
                ver = await self.run_command("V", idle_ms=600, max_wait_s=8.0)
                fam = detect_family(ver)
            except (XnetError, ConnectionError, OSError, asyncio.TimeoutError) as e:
                logger.debug("%s: V family-probe failed: %s", self.config.callsign, e)
        self.family = fam or "unknown"
        logger.info("%s: family detected as %s", self.config.callsign, self.family)
        return self.family

    async def disconnect(self) -> None:
        """Send `BYE` and tear down the SSH + telnet channels."""
        try:
            if self._writer is not None and not self._writer.is_closing():
                try:
                    await asyncio.wait_for(self._send_line("BYE"), timeout=2.0)
                    await asyncio.sleep(0.2)  # let the server process BYE
                except (asyncio.TimeoutError, ConnectionError, OSError):
                    pass
                self._writer.close()
        finally:
            self._reader = None
            self._writer = None
            self._sys_active = False
            if self._ssh is not None:
                self._ssh.close()
                try:
                    await self._ssh.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
                self._ssh = None

    async def elevate_sys(self) -> None:
        """Issue the `SYS` command and answer the positional challenge.

        xnet V1.39 and PC/Flexnet 3.3g both use a challenge-response scheme:
            send  : `SYS\\r`
            recv  : `<NODENAME>>  p1 p2 p3 p4 p5\\r\\n`  (1-indexed positions)
            send  : <sys_pwd[p1-1]><sys_pwd[p2-1]>...   (no spaces)

        The pattern is `_resolve_sys_challenge`. After sending the reply we
        can't easily detect success/failure from the user prompt alone —
        xnet rejects wrong responses silently. Callers that need certainty
        should issue a SYS-only command and parse the result.

        Idempotent — calling twice is a no-op after the first success.

        Raises:
            XnetError: if no SYS challenge appears, the challenge can't be
                parsed, or one of the requested positions is out of range
                for the configured password.
            LookupError: if no sys password is available in keychain/yaml.
        """
        if self._sys_active:
            return
        if not self.config.sys_required:
            logger.warning(
                "%s has sys_required=false but elevate_sys() called — proceeding",
                self.config.callsign,
            )
        async with self._lock:
            await self._send_line(self.config.sys_command)
            challenge_buf = await self._read_until_idle(
                idle_ms=500, max_wait_s=5.0
            )
            response = self._resolve_sys_challenge(
                challenge_buf.encode("latin-1", errors="ignore")
            )
            await self._send_line(response)
            tail = await self._read_until_idle(idle_ms=500, max_wait_s=5.0)
            if SYS_REJECTED_MARKERS.search(tail.encode("latin-1", errors="ignore")):
                raise XnetError(
                    f"{self.config.callsign}: SYS authentication rejected"
                )
            self._sys_active = True
            logger.info(
                "%s: SYS challenge answered (%d positions)",
                self.config.callsign,
                len(response),
            )

    def _resolve_sys_challenge(self, buf: bytes) -> str:
        """Parse the SYS challenge line and assemble the per-position reply."""
        match = SYS_CHALLENGE.search(buf)
        if not match:
            preview = buf[-200:].decode("latin-1", errors="replace")
            raise XnetError(
                f"{self.config.callsign}: no SYS challenge in response "
                f"(last bytes: {preview!r})"
            )
        positions = [int(p) for p in match.group(1).split()]
        sys_pwd = get_password(self.config.callsign, "sys")
        try:
            return "".join(sys_pwd[p - 1] for p in positions)
        except IndexError as e:
            raise XnetError(
                f"{self.config.callsign}: SYS challenge positions {positions} "
                f"exceed configured password length ({len(sys_pwd)})"
            ) from e

    async def run_command(
        self,
        command: str,
        idle_ms: int = 400,
        max_wait_s: float = 15.0,
    ) -> str:
        """Send a command, return the response collected until the link goes idle.

        The "idle" heuristic: once no bytes have been received for `idle_ms`
        milliseconds, the command is considered complete. Trade-off: bursty
        servers may produce a final chunk after the idle window — bump
        `idle_ms` for those.

        Returns:
            Raw decoded text including the echoed command and final prompt.
        """
        if self._reader is None or self._writer is None:
            raise XnetError(f"{self.config.callsign}: not connected")
        async with self._lock:
            await self._send_line(command)
            return await self._read_until_idle(idle_ms=idle_ms, max_wait_s=max_wait_s)

    async def capture(
        self,
        command: str,
        duration_s: float,
        max_duration_s: float = 120.0,
    ) -> str:
        """Send a streaming command (MOnitor, IPDump) and capture a fixed window.

        Unlike :meth:`run_command`, this does NOT stop at the first idle gap —
        it keeps reading for the full `duration_s` (clamped to `max_duration_s`)
        so intermittent frames are not truncated. The command typically leaves
        a mode (e.g. monitor) enabled; the session is closed on disconnect,
        which clears it.

        Returns:
            Raw decoded text captured during the window.
        """
        if self._reader is None or self._writer is None:
            raise XnetError(f"{self.config.callsign}: not connected")
        window = max(0.0, min(duration_s, max_duration_s))
        async with self._lock:
            await self._send_line(command)
            deadline = time.monotonic() + window
            buf = bytearray()
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                chunk = await self._read_chunk(timeout=min(0.5, remaining))
                if chunk:
                    buf += self._strip_iac(chunk)
            return buf.decode("latin-1", errors="replace")

    # ── internals ─────────────────────────────────────────────────────────

    async def _login(self) -> None:
        if not self.config.login_required:
            # Open node: no login prompt — just drain any banner and proceed.
            await self._read_until_idle(idle_ms=500, max_wait_s=10.0)
            logger.info("%s: no login required (open node)", self.config.callsign)
            return
        try:
            await self._read_until(LOGIN_PROMPTS, timeout=10.0)
        except TimeoutError as e:
            raise XnetError(
                f"{self.config.callsign}: no login prompt after SSH+telnet"
            ) from e
        await self._send_line(self.config.user)

        try:
            await self._read_until(PASSWORD_PROMPTS, timeout=5.0)
        except TimeoutError as e:
            raise XnetError(
                f"{self.config.callsign}: no password prompt after username"
            ) from e
        user_pwd = get_password(self.config.callsign, "user")
        await self._send_line(user_pwd)

        # Drain banner / motd until idle
        tail = await self._read_until_idle(idle_ms=500, max_wait_s=10.0)
        if LOGIN_FAILED.search(tail.encode("latin-1", errors="ignore")):
            raise XnetError(
                f"{self.config.callsign}: login rejected — check credentials"
            )
        logger.info("%s: login complete", self.config.callsign)

    async def _send_line(self, text: str) -> None:
        if self._writer is None:
            raise XnetError(f"{self.config.callsign}: writer closed")
        self._writer.write(text.encode("latin-1") + b"\r")
        await self._writer.drain()

    async def _read_chunk(self, max_bytes: int = 4096, timeout: float = 0.3) -> bytes:
        if self._reader is None:
            raise XnetError(f"{self.config.callsign}: reader closed")
        try:
            return await asyncio.wait_for(
                self._reader.read(max_bytes), timeout=timeout
            )
        except asyncio.TimeoutError:
            return b""

    async def _read_until(
        self, pattern: re.Pattern[bytes], timeout: float
    ) -> bytes:
        """Read chunks until `pattern.search(buf)` matches or `timeout` expires."""
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            chunk = await self._read_chunk(timeout=min(0.3, remaining))
            if chunk:
                buf += self._strip_iac(chunk)
                if pattern.search(buf):
                    return bytes(buf)
        raise TimeoutError(
            f"No match for pattern within {timeout}s; got {len(buf)} bytes"
        )

    async def _read_until_idle(self, idle_ms: int, max_wait_s: float) -> str:
        """Read until the stream has been silent for `idle_ms` after the first byte.

        Semantic: "idle" means "no bytes for `idle_ms`, having received at
        least one chunk". This prevents premature return when the first
        chunk is delayed (notably on the chained AX.25 path, where the
        round-trip through -14 → -12 can exceed 600 ms).

        If no byte arrives within `max_wait_s`, return whatever's buffered
        (empty string) — caller decides whether that's an error.
        """
        deadline = time.monotonic() + max_wait_s
        buf = bytearray()
        last_data_at: float | None = None
        idle_s = idle_ms / 1000.0
        while time.monotonic() < deadline:
            chunk = await self._read_chunk(timeout=idle_s)
            now = time.monotonic()
            if chunk:
                buf += self._strip_iac(chunk)
                last_data_at = now
            elif last_data_at is not None and now - last_data_at >= idle_s:
                return buf.decode("latin-1", errors="replace")
        return buf.decode("latin-1", errors="replace")

    @staticmethod
    def _strip_iac(data: bytes) -> bytes:
        """Strip telnet IAC negotiation sequences (we accept zero options).

        Handles WILL/WONT/DO/DONT (3-byte) and most 2-byte commands; preserves
        escaped 0xFF data bytes (IAC IAC → 0xFF).
        """
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0xFF and i + 1 < n:
                cmd = data[i + 1]
                # WILL=0xFB WONT=0xFC DO=0xFD DONT=0xFE — all 3-byte
                if cmd in (0xFB, 0xFC, 0xFD, 0xFE):
                    if i + 2 < n:
                        i += 3
                        continue
                    return bytes(out)  # truncated, leave for next chunk
                if cmd == 0xFF:  # escaped 0xFF data byte
                    out.append(0xFF)
                    i += 2
                    continue
                # Other IAC commands (SB/SE/IP/...) — 2-byte; skip
                i += 2
                continue
            out.append(b)
            i += 1
        return bytes(out)
