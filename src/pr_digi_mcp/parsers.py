"""Structured parsers for raw node command output.

Each parser turns the raw text a node returns (as produced by `run_command`)
into typed records, so tools can emit JSON and aggregation can reason over the
data. Parsing is **tolerant**: unrecognised lines are skipped, never raised on —
node builds vary, and a partial parse beats a crash. Callers that need the exact
bytes still have the raw text.

Covered (stable, widely-used formats):
  - BPQ32/LinBPQ: `ROUTES`, `NODES`, `LINKS`, FlexNet `FL` links, FlexNet `D`
  - (X)Net: `L` / `L *` link rows (best-effort: port, callsign, dest-type flag)
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


def to_dicts(records: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of parser dataclass records to plain dicts (for JSON)."""
    return [asdict(r) for r in records]
