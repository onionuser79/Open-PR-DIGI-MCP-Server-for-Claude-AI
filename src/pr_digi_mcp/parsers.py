"""Structured parsers for raw node command output.

Each parser turns the raw text a node returns (as produced by `run_command`)
into typed records, so tools can emit JSON and aggregation can reason over the
data. Parsing is **tolerant**: unrecognised lines are skipped, never raised on —
node builds vary, and a partial parse beats a crash. Callers that need the exact
bytes still have the raw text.

Covered (stable, widely-used formats):
  - BPQ32/LinBPQ: `ROUTES`, `NODES`, `LINKS`, FlexNet `FL` links, FlexNet `D`
  - (X)Net: `L` / `L *` link rows (best-effort: port, callsign, dest-type flag),
    `N <call>` NetROM route detail (quality/obs/hops), `MH` heard list
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

# ── BPQ ROUTES ────────────────────────────────────────────────────────────────
# e.g.  "> 3 DK0WUE-7  161 29 "   or   "  2 K5DAT-7   161 0!"
_BPQ_ROUTE = re.compile(
    r"^\s*(?P<active>>)?\s*(?P<port>\d+)\s+(?P<call>[A-Z0-9]+(?:-\d+)?)\s+"
    r"(?P<quality>\d+)\s+(?P<count>\d+)(?P<locked>!)?\s*$"
)


@dataclass(frozen=True)
class BpqRoute:
    port: int
    callsign: str
    quality: int
    count: int
    active: bool
    locked: bool


def parse_bpq_routes(text: str) -> list[BpqRoute]:
    out: list[BpqRoute] = []
    for line in text.splitlines():
        m = _BPQ_ROUTE.match(line)
        if not m:
            continue
        out.append(
            BpqRoute(
                port=int(m["port"]),
                callsign=m["call"],
                quality=int(m["quality"]),
                count=int(m["count"]),
                active=m["active"] is not None,
                locked=m["locked"] is not None,
            )
        )
    return out


# ── BPQ NODES ───────────────────────────────────────────────────────────────
# grid of "ALIAS:CALL" tokens, e.g. "BOLNET:IW2OHX-14   OHXGW:IW2OHX-1 ..."
_BPQ_NODE = re.compile(r"\b([A-Za-z0-9#]+):([A-Z0-9]+(?:-\d+)?)\b")


@dataclass(frozen=True)
class BpqNode:
    alias: str
    callsign: str


def parse_bpq_nodes(text: str) -> list[BpqNode]:
    out: list[BpqNode] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        # Skip the header line ("...} Nodes")
        if "}" in line and ":" not in line.split("}", 1)[1]:
            continue
        for alias, call in _BPQ_NODE.findall(line):
            key = (alias, call)
            if key not in seen:
                seen.add(key)
                out.append(BpqNode(alias=alias, callsign=call))
    return out


# ── BPQ LINKS ─────────────────────────────────────────────────────────────────
# e.g. "IW2OHX-14 IW2OHX-15  S=5 P=4 T=3 V=2 Q=0"
_BPQ_LINK = re.compile(
    r"^\s*(?P<far>[A-Z0-9]+(?:-\d+)?)\s+(?P<local>[A-Z0-9]+(?:-\d+)?)\s+"
    r"S=(?P<state>\d+)\s+P=(?P<port>\d+)\s+T=(?P<t>\d+)\s+V=(?P<ver>[0-9.]+)\s+Q=(?P<q>\d+)"
)


@dataclass(frozen=True)
class BpqLink:
    far: str
    local: str
    state: int
    port: int
    version: str
    quality: int


def parse_bpq_links(text: str) -> list[BpqLink]:
    out: list[BpqLink] = []
    for line in text.splitlines():
        m = _BPQ_LINK.match(line)
        if not m:
            continue
        out.append(
            BpqLink(
                far=m["far"],
                local=m["local"],
                state=int(m["state"]),
                port=int(m["port"]),
                version=m["ver"],
                quality=int(m["q"]),
            )
        )
    return out


# ── BPQ FlexNet FL links ────────────────────────────────────────────────────
# e.g. "IW2OHX-14    3     CONNECTED  60s    389    20:24:20    116"
_BPQ_FL = re.compile(
    r"^\s*(?P<call>[A-Z0-9]+(?:-\d+)?)\s+(?P<port>\d+)\s+(?P<status>[A-Z]+)\s+"
    r"(?P<lt>\S+)\s+(?P<ka>\d+)\s+(?P<uptime>[\d:]+)\s+(?P<routes>\d+)\s*$"
)


@dataclass(frozen=True)
class FlexnetLink:
    callsign: str
    port: int
    status: str
    link_time: str
    keepalives: int
    uptime: str
    routes: int


def parse_bpq_flexnet_links(text: str) -> list[FlexnetLink]:
    out: list[FlexnetLink] = []
    for line in text.splitlines():
        m = _BPQ_FL.match(line)
        if not m:
            continue
        out.append(
            FlexnetLink(
                callsign=m["call"],
                port=int(m["port"]),
                status=m["status"],
                link_time=m["lt"],
                keepalives=int(m["ka"]),
                uptime=m["uptime"],
                routes=int(m["routes"]),
            )
        )
    return out


# ── BPQ FlexNet destinations (D) ──────────────────────────────────────────────
# space-separated triples "CALL  N-M  COST[!]", many per line
_BPQ_FLEXDEST = re.compile(
    r"\b([A-Z0-9]+)\s+(\d+-\d+)\s+(\d+)(!)?"
)


@dataclass(frozen=True)
class FlexnetDest:
    callsign: str
    ssid_range: str
    cost: int
    cached: bool


def parse_bpq_flexnet_destinations(text: str) -> list[FlexnetDest]:
    out: list[FlexnetDest] = []
    for call, rng, cost, cached in _BPQ_FLEXDEST.findall(text):
        out.append(
            FlexnetDest(
                callsign=call, ssid_range=rng, cost=int(cost), cached=cached == "!"
            )
        )
    return out


# ── (X)Net L / L* link rows (best-effort) ─────────────────────────────────────
# e.g. "11:IR3UHU-2   138 I   0   0/0     0  2h 13m ..."
# Leading "port:callsign", a destination count, then a 1-char dest-type flag
# (Q=NETROM, I=INP3, F=FLEXNET).
_XNET_LINK = re.compile(
    r"^\s*(?P<port>\d+):(?P<call>[A-Z0-9]+(?:-\d+)?)\s+(?P<dst>\d+)?\s*"
    r"(?P<flag>[QIF])\b"
)
_XNET_FLAG_NAMES = {"Q": "NETROM", "I": "INP3", "F": "FLEXNET"}


@dataclass(frozen=True)
class XnetLink:
    port: int
    callsign: str
    dest_type: str  # NETROM | INP3 | FLEXNET
    flag: str


def parse_xnet_links(text: str) -> list[XnetLink]:
    out: list[XnetLink] = []
    for line in text.splitlines():
        m = _XNET_LINK.match(line)
        if not m:
            continue
        out.append(
            XnetLink(
                port=int(m["port"]),
                callsign=m["call"],
                dest_type=_XNET_FLAG_NAMES[m["flag"]],
                flag=m["flag"],
            )
        )
    return out


# ── (X)Net NetROM route detail (`N <call>`) ──────────────────────────────────
# Header:  "routing UAWNET:IR1UAW-10 v IR3UHU-2"
# Rows:    "  IR1UAW-10 IR1UAW-10 254/6   0.51s  2 hops"
#          "> IR1UAW-10 IR3UHU-2  254/6   0.50s  3 hops"   (> marks the picked route)
# Fields per row: [selected] dest via quality/obscount rtt-seconds hop-count.
_NETROM_ROUTE = re.compile(
    r"^\s*(?P<sel>>)?\s*(?P<dest>[A-Z0-9]+(?:-\d+)?)\s+(?P<via>[A-Z0-9]+(?:-\d+)?)\s+"
    r"(?P<qual>\d+)/(?P<obs>\d+)\s+(?P<rtt>[\d.]+)s\s+(?P<hops>\d+)\s+hops?\b"
)
_NETROM_HEADER = re.compile(
    r"^\s*routing\s+(?P<alias>[A-Za-z0-9#]+):(?P<call>[A-Z0-9]+(?:-\d+)?)\b"
)


@dataclass(frozen=True)
class NetromRoute:
    dest: str
    via: str
    quality: int
    obs: int
    rtt_s: float
    hops: int
    selected: bool


def parse_netrom_route_detail(text: str) -> list[NetromRoute]:
    """Parse `N <call>` route detail into per-neighbour routes (NetROM quality/hops).

    NetROM quality is higher-is-better; `hops` is the path length reported by the
    node. The `selected` flag marks the route the node itself prefers (leading `>`).
    """
    out: list[NetromRoute] = []
    for line in text.splitlines():
        m = _NETROM_ROUTE.match(line)
        if not m:
            continue
        out.append(
            NetromRoute(
                dest=m["dest"],
                via=m["via"],
                quality=int(m["qual"]),
                obs=int(m["obs"]),
                rtt_s=float(m["rtt"]),
                hops=int(m["hops"]),
                selected=m["sel"] is not None,
            )
        )
    return out


def netrom_best_route(text: str) -> NetromRoute | None:
    """Return the node's preferred NetROM route (the `>` row, else fewest hops)."""
    routes = parse_netrom_route_detail(text)
    if not routes:
        return None
    selected = [r for r in routes if r.selected]
    if selected:
        return selected[0]
    return min(routes, key=lambda r: (r.hops, -r.quality))


# ── (X)Net heard list (`MH`) ─────────────────────────────────────────────────
# Header:  " p:call      - date     time         rxbytes"
# Rows:    " 9:DK0WUE      10.07.26 13:00:49    14358654"
_XNET_HEARD = re.compile(
    r"^\s*(?P<port>\d+):(?P<call>[A-Z0-9]+(?:-\d+)?)\s+"
    r"(?P<date>\d{2}\.\d{2}\.\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<rxbytes>\d+)"
)


@dataclass(frozen=True)
class HeardStation:
    port: int
    callsign: str
    date: str
    time: str
    rxbytes: int


def parse_heard(text: str) -> list[HeardStation]:
    """Parse an (X)Net `MH` heard list into structured records (tolerant).

    Rows that don't match the (X)Net `port:call date time rxbytes` shape are
    skipped, so other families' heard output degrades to an empty list rather
    than a crash; callers keep the raw text either way.
    """
    out: list[HeardStation] = []
    for line in text.splitlines():
        m = _XNET_HEARD.match(line)
        if not m:
            continue
        out.append(
            HeardStation(
                port=int(m["port"]),
                callsign=m["call"],
                date=m["date"],
                time=m["time"],
                rxbytes=int(m["rxbytes"]),
            )
        )
    return out


def to_dicts(records: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of parser dataclass records to plain dicts (for JSON)."""
    return [asdict(r) for r in records]
