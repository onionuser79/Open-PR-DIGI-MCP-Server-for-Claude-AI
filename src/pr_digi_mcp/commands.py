"""Pure command-string builders and validators for (X)Net SYS operations.

Kept separate from the IO layer (``transports/``) and the tool layer
(``server.py``) so the wire-format of each privileged command can be
unit-tested without a live node. Every builder returns a single-line command
string ready to hand to ``XnetTransport.run_command``.

Builders validate their inputs and raise ``ValueError`` on anything malformed.
Critically, :func:`validate_token` rejects embedded CR/LF — the telnet line
terminator — which would otherwise let a caller smuggle a second command into
a single argument (e.g. an "alias" of ``foo\\rRESET``).

Syntax captured live from (X)Net V1.39 on IW2OHX-14 (2026-06-09):
    Router bc add <port>
    Router flexnet add <port> <call> [<viacall>]
    Router local add <PORT> <CALL> {<VIACALL>} [-] (n|d|nd)[p] [<ALIAS>]
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Callsign: 3-6 alphanumerics, optional -SSID (0-15). Upper-cased on validate.
_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{3,6}(?:-(?:1[0-5]|[0-9]))?$")
# Node alias: 1-6 alphanumerics.
_ALIAS_RE = re.compile(r"^[A-Z0-9]{1,6}$")
# Any C0 control char or DEL — includes \r (0x0D) and \n (0x0A).
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

ROUTER_KINDS = ("bc", "flexnet", "local")
# Local-route distribution flags: n=node, d=destination, nd=both, optional p suffix.
_DIST_FLAGS = ("n", "d", "nd", "np", "dp", "ndp")


def validate_token(value: str, *, field: str) -> str:
    """Return ``value`` unchanged, or raise if it contains a control char.

    Guards against CR/LF command injection through any free-text argument.
    """
    if _CONTROL_RE.search(value):
        raise ValueError(f"{field} contains a control character: {value!r}")
    return value


def validate_callsign(call: str) -> str:
    """Normalise and validate an AX.25 callsign (e.g. ``IW2OHX-14``)."""
    normalised = call.strip().upper()
    if not _CALLSIGN_RE.match(normalised):
        raise ValueError(
            f"invalid callsign {call!r} (expected e.g. 'IW2OHX-14', SSID 0-15)"
        )
    return normalised


def validate_alias(alias: str) -> str:
    """Normalise and validate a node alias (1-6 alphanumerics)."""
    normalised = alias.strip().upper()
    if not _ALIAS_RE.match(normalised):
        raise ValueError(f"invalid alias {alias!r} (1-6 alphanumerics)")
    return normalised


def validate_port(port: int) -> int:
    """Validate a port number (0-255) — shared by (X)Net and BPQ."""
    if not 0 <= port <= 255:
        raise ValueError(f"invalid port {port!r} (expected 0-255)")
    return port


def validate_quality(qual: int) -> int:
    """Validate a NetROM route quality (0-255)."""
    if not 0 <= qual <= 255:
        raise ValueError(f"invalid quality {qual!r} (expected 0-255)")
    return qual


def _check_kind(kind: str) -> str:
    if kind not in ROUTER_KINDS:
        raise ValueError(f"invalid router kind {kind!r}; one of {ROUTER_KINDS}")
    return kind


def build_router_add(
    kind: str,
    *,
    port: int,
    call: str | None = None,
    via: str | None = None,
    dist: str | None = None,
    alias: str | None = None,
) -> str:
    """Build a ``ROUTER <kind> ADD ...`` command.

    - ``bc``      : ``ROUTER BC ADD <port>`` (enable NODES broadcasts on a port)
    - ``flexnet`` : ``ROUTER FLEXNET ADD <port> <call> [<via>]``
    - ``local``   : ``ROUTER LOCAL ADD <port> <call> [<via>] [<dist>] [<alias>]``
    """
    _check_kind(kind)
    validate_port(port)
    parts: list[str] = ["ROUTER", kind.upper(), "ADD", str(port)]

    if kind == "bc":
        if any(x is not None for x in (call, via, dist, alias)):
            raise ValueError("router kind 'bc' takes only a port")
        return " ".join(parts)

    if call is None:
        raise ValueError(f"router kind {kind!r} requires a callsign")
    parts.append(validate_callsign(call))
    if via is not None:
        parts.append(validate_callsign(via))

    if kind == "local":
        if dist is not None:
            flag = dist.strip().lower()
            if flag not in _DIST_FLAGS:
                raise ValueError(f"invalid dist flag {dist!r}; one of {_DIST_FLAGS}")
            parts.append(flag)
        if alias is not None:
            parts.append(validate_token(alias.strip(), field="alias"))
    elif dist is not None or alias is not None:
        raise ValueError("dist/alias are only valid for router kind 'local'")

    return " ".join(parts)


def build_router_del(kind: str, *, port: int, call: str | None = None) -> str:
    """Build a ``ROUTER <kind> DEL ...`` command (``bc`` takes port only)."""
    _check_kind(kind)
    validate_port(port)
    parts: list[str] = ["ROUTER", kind.upper(), "DEL", str(port)]
    if kind != "bc":
        if call is None:
            raise ValueError(f"router kind {kind!r} DEL requires a callsign")
        parts.append(validate_callsign(call))
    elif call is not None:
        raise ValueError("router kind 'bc' DEL takes only a port")
    return " ".join(parts)


def build_iproute_add(*, net: str, iface: str, gw: str) -> str:
    """Build ``IPRoute ADD <net/mask> <iface> <gateway>``."""
    return " ".join(
        [
            "IPRoute",
            "ADD",
            validate_token(net.strip(), field="net"),
            validate_token(iface.strip(), field="iface"),
            validate_token(gw.strip(), field="gw"),
        ]
    )


def build_iproute_del(*, net: str) -> str:
    """Build ``IPRoute DEL <net/mask>``."""
    return f"IPRoute DEL {validate_token(net.strip(), field='net')}"


def build_arp_add(*, ip: str, iface: str, hw: str) -> str:
    """Build ``ARp ADD <ip> <iface> <hw|call>``."""
    return " ".join(
        [
            "ARp",
            "ADD",
            validate_token(ip.strip(), field="ip"),
            validate_token(iface.strip(), field="iface"),
            validate_token(hw.strip(), field="hw"),
        ]
    )


def build_arp_del(*, ip: str) -> str:
    """Build ``ARp DEL <ip>``."""
    return f"ARp DEL {validate_token(ip.strip(), field='ip')}"


# ── monitor port selection ──────────────────────────────────────────────────

# Highest (X)Net port index (ports 0..23, per the `MOnitor` legend).
MAX_XNET_PORT = 23

_MONITOR_ALL = frozenset({"*", "ALL", ""})


class MonitorSelection(NamedTuple):
    """How to drive `MOnitor` for a requested set of ports.

    (X)Net V1.39's `MOnitor` selects exactly ONE port or `*` (all) — the last
    token wins, there is no multi-port mask. So:

    * ``arg`` is what we actually send (``"*"`` or a single port number).
    * ``filter_ports`` is set only for the multi-port case: we monitor ``*``
      and filter the captured frames to these ports client-side. ``None`` means
      no filtering (the node already scoped it).
    """

    arg: str
    filter_ports: frozenset[int] | None


def parse_monitor_selection(spec: str) -> MonitorSelection:
    """Resolve a monitor port spec into a `MonitorSelection`.

    Accepts ``"*"``/``"all"``/empty (all ports), a single port (``"8"``), or
    several ports as a comma/space list (``"7 8"``, ``"7,8"``). A single port is
    selected natively; multiple ports monitor ``*`` and filter client-side.

    Raises:
        ValueError: on a non-numeric token or an out-of-range port.
    """
    normalised = spec.strip()
    if normalised.upper() in _MONITOR_ALL:
        return MonitorSelection("*", None)

    ports: list[int] = []
    for token in re.split(r"[,\s]+", normalised):
        if not token.isdigit():
            raise ValueError(
                f"invalid monitor port {token!r}: use '*' or port numbers "
                f"0-{MAX_XNET_PORT}"
            )
        value = int(token)
        if not 0 <= value <= MAX_XNET_PORT:
            raise ValueError(f"port {value} out of range 0-{MAX_XNET_PORT}")
        ports.append(value)

    unique = sorted(set(ports))
    if len(unique) == 1:
        return MonitorSelection(str(unique[0]), None)
    return MonitorSelection("*", frozenset(unique))


def filter_monitor_text(text: str, ports: frozenset[int]) -> str:
    """Keep only the monitor frame blocks whose leading ``<port>:`` is in ``ports``.

    A frame is a header line matching ``^<port>:`` followed by its continuation
    (hex-dump / blank) lines, up to the next header. Preamble lines before the
    first header (e.g. the ``Monitoring * [...]`` echo) are kept for context.
    """
    wanted = {str(p) for p in ports}
    header = re.compile(r"^(\d+):")
    kept: list[str] = []
    keep_current = True  # keep preamble until the first frame header
    for line in text.split("\n"):
        match = header.match(line)
        if match:
            keep_current = match.group(1) in wanted
        if keep_current:
            kept.append(line)
    return "\n".join(kept)


# ── BPQ32 / LinBPQ ──────────────────────────────────────────────────────────

# Per-port parameters (syntax `NAME [port] [value]`).
BPQ_PORT_PARAMS: frozenset[str] = frozenset(
    {
        "TXDELAY",
        "MAXFRAME",
        "FRACK",
        "RESPTIME",
        "PPACLEN",
        "RETRIES",
        "QUALITY",
        "PERSIST",
        "TXTAIL",
        "XMITOFF",
        "DIGIFLAG",
        "DIGIPORT",
        "MAXUSERS",
        "VALIDCALL",
        "L3ONLY",
        "BBSALIAS",
        "FULLDUP",
        "SOFTDCD",
    }
)

# System-wide parameters (syntax `NAME [value]`, no port).
BPQ_SYSTEM_PARAMS: frozenset[str] = frozenset(
    {
        "REMDUMP",
        "OBSINIT",
        "OBSMIN",
        "NODESINT",
        "L3TTL",
        "L4RETRIES",
        "L4TIMEOUT",
        "T3",
        "NODEIDLETIME",
        "LINKEDFLAG",
        "IDINTERVAL",
        "MINQUAL",
        "FULLCTEXT",
        "HIDENODES",
        "L4DELAY",
        "L4WINDOW",
        "BTINTERVAL",
    }
)


def build_bpq_node_add(*, alias: str, call: str, qual: int, neighbour: str) -> str:
    """Build ``NODE ADD <alias>:<call> <qual> <neighbour>``."""
    return (
        f"NODE ADD {validate_alias(alias)}:{validate_callsign(call)} "
        f"{validate_quality(qual)} {validate_callsign(neighbour)}"
    )


def build_bpq_node_del(*, call: str) -> str:
    """Build ``NODE DEL <call>``."""
    return f"NODE DEL {validate_callsign(call)}"


def build_bpq_route_set(*, call: str, port: int, qual: int, lock: bool = False) -> str:
    """Build ``ROUTES <call> <port> <qual> [!]`` (set quality / lock a neighbour)."""
    parts = [
        "ROUTES",
        validate_callsign(call),
        str(validate_port(port)),
        str(validate_quality(qual)),
    ]
    if lock:
        parts.append("!")
    return " ".join(parts)


def build_bpq_param(name: str, *, value: str | None = None, port: int | None = None) -> str:
    """Build a BPQ parameter get/set command.

    The name MUST be a known port or system parameter — this allowlist is a
    security control: it stops a free-text ``name`` from smuggling an arbitrary
    (possibly dangerous) console command past the approval gate.
    """
    pname = name.strip().upper()
    is_port = pname in BPQ_PORT_PARAMS
    if not is_port and pname not in BPQ_SYSTEM_PARAMS:
        raise ValueError(f"unknown BPQ parameter {name!r}")
    parts = [pname]
    if port is not None:
        if not is_port:
            raise ValueError(f"{pname} is a system parameter; no port applies")
        parts.append(str(validate_port(port)))
    if value is not None:
        parts.append(validate_token(value.strip(), field="value"))
    return " ".join(parts)
