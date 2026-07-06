"""BPQ32 / LinBPQ transport — SSH tunnel to a BPQ telnet console.

Mirrors XnetTransport for SSH+telnet IO and login (the regexes match both
``Login:``/``callsign:`` and ``Password:``/``password:``), but the sysop
elevation flow is BPQ-specific:

* Send ``PASSWORD``.
* If the BPQ session is local to its host (e.g. our SSH tunnel terminates
  on the same Pi as linbpq), BPQ replies ``<prompt>} Ok`` and the session
  is already sysop. No further input.
* Otherwise BPQ prints a 5-number challenge such as ``04 10 03 07 04``
  (also seen hyphenated). The client replies with the password
  characters at those positions, concatenated, no spaces.

Reference: https://www.cantab.net/users/john.wiseman/Documents/Node%20SYSOP.html

The user prompt looks like ``<NODENAME>}`` (e.g. ``BPQBOL:IW2OHX-13}``) but
the existing idle-based ``_read_until_idle`` is what reads command output,
so we don't need to match it explicitly.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from ..config import NodeConfig
from ..credentials import get_password
from .xnet import XnetError, XnetTransport

logger = logging.getLogger(__name__)

# Five 1-or-2-digit numbers separated by whitespace or hyphens. Anchored
# loosely — challenges may sit on their own line surrounded by other text.
BPQ_PASSWORD_CHALLENGE: Final = re.compile(
    rb"\b(\d{1,2})[\s\-]+(\d{1,2})[\s\-]+(\d{1,2})[\s\-]+(\d{1,2})[\s\-]+(\d{1,2})\b"
)

# `Ok` reply to PASSWORD when the session was already privileged
# (typical for sessions whose remote IP BPQ considers local, e.g. via
# our SSH tunnel terminating on the same host as the daemon).
BPQ_OK_REPLY: Final = re.compile(rb"(?i)\bok\b")

# Rejection markers shown after a wrong challenge reply.
BPQ_REJECTED: Final = re.compile(
    rb"(?i)(invalid|incorrect|wrong\s+password|bad\s+password|denied|sorry)"
)


class BpqTransport(XnetTransport):
    """SSH-tunnelled BPQ32/LinBPQ telnet session with PASSWORD elevation."""

    _ACCEPTED_TYPES = frozenset({"bpq", "linbpq"})

    def __init__(self, config: NodeConfig) -> None:
        super().__init__(config)

    async def elevate_sys(self) -> None:
        """Issue ``PASSWORD`` and complete the BPQ sysop handshake.

        Idempotent — calling twice after a successful elevation is a no-op.

        Raises:
            XnetError: if BPQ rejects the challenge reply, or the response
                to ``PASSWORD`` is neither ``Ok`` nor a 5-number challenge,
                or one of the requested positions exceeds the configured
                password length.
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
            await self._send_line("PASSWORD")
            buf = await self._read_until_idle(idle_ms=600, max_wait_s=5.0)
            raw = buf.encode("latin-1", errors="ignore")

            challenge = BPQ_PASSWORD_CHALLENGE.search(raw)
            if challenge:
                positions = [int(p) for p in challenge.groups()]
                sys_pwd = get_password(self.config.callsign, "sys")
                try:
                    response = "".join(sys_pwd[p - 1] for p in positions)
                except IndexError as e:
                    raise XnetError(
                        f"{self.config.callsign}: PASSWORD challenge positions "
                        f"{positions} exceed configured password length "
                        f"({len(sys_pwd)})"
                    ) from e
                await self._send_line(response)
                tail = await self._read_until_idle(idle_ms=600, max_wait_s=5.0)
                tail_raw = tail.encode("latin-1", errors="ignore")
                if BPQ_REJECTED.search(tail_raw) or not BPQ_OK_REPLY.search(tail_raw):
                    raise XnetError(
                        f"{self.config.callsign}: PASSWORD reply rejected "
                        f"(positions={positions}); tail={tail[-200:]!r}"
                    )
                self._sys_active = True
                logger.info(
                    "%s: sysop elevated via challenge (%d positions)",
                    self.config.callsign,
                    len(positions),
                )
                return

            if BPQ_OK_REPLY.search(raw):
                # BPQ deemed the session already privileged (local).
                self._sys_active = True
                logger.info("%s: sysop already active (Ok without challenge)", self.config.callsign)
                return

            raise XnetError(
                f"{self.config.callsign}: unexpected PASSWORD reply "
                f"(no challenge digits, no Ok): {buf[-200:]!r}"
            )
