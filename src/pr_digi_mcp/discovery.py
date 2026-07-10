"""On-demand route discovery to an arbitrary callsign.

Given a target that is NOT configured in ``nodes.yaml``, find which configured
node can reach it by reading that node's routing tables — the FlexNet
destination table (``D``, cost) and the NetROM route detail (``N <call>``,
quality + hops). Nothing is scanned in advance and nothing is persisted: every
call queries the live tables.

Only two table families are consulted (per Marco's directive):
  * FlexNet Destinations — ``D <call>`` (nodes running (X)Net or linbpq-flexnet)
  * NetROM Destinations  — ``N <call>`` (all console nodes)

Link tables (``L``) are deliberately NOT used for discovery.

Candidates are ranked into ONE ordered list; the caller connects to the best and
falls back to the next on failure. See ``_rank_key`` for the (single, tunable)
ranking rule.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .config import NodeConfig
from .parsers import netrom_best_route, parse_bpq_flexnet_destinations, parse_bpq_nodes

logger = logging.getLogger(__name__)

# Node types with a telnet console we can query for routing info and connect
# outward from. Chained (PC/Flexnet) nodes are discovery TARGETS, not oracles.
_SOURCE_TYPES = frozenset({"xnet", "bpq", "linbpq"})
# Node types that expose a FlexNet destination table via `D`.
_FLEXNET_TYPES = frozenset({"xnet", "linbpq"})

# A callsign carrying an explicit SSID (e.g. "IR1UAW-10") is unambiguous; a bare
# token ("UAWNOD", "IR1UAW") might be an alias, so we try to resolve it first.
_HAS_SSID = re.compile(r"^[A-Z0-9]{3,7}-\d{1,2}$")

# NetROM quality is 0..255 (higher = better). Fold it onto the same lower-is-
# better axis as FlexNet cost so both can share one ranked list.
_MAX_NETROM_QUALITY = 256


@dataclass(frozen=True)
class RouteCandidate:
    """One way to reach ``target``: connect to ``via_node`` and issue the chain."""

    target: str
    via_node: str
    source: str  # "flexnet" | "netrom"
    hops: int
    connect_chain: list[str]
    flexnet_cost: int | None = None
    netrom_quality: int | None = None
    detail: dict[str, str] = field(default_factory=dict)

    def sort_metric(self) -> int:
        """Within-source, lower-is-better metric (for display / tie context).

        FlexNet cost is used directly; NetROM quality is inverted onto a
        lower-is-better axis. Cross-family ordering is decided by ``_rank_key``,
        not by this value (FlexNet routes always rank ahead of NetROM ones).
        """
        if self.source == "flexnet":
            return self.flexnet_cost if self.flexnet_cost is not None else 60000
        q = self.netrom_quality if self.netrom_quality is not None else 0
        return max(0, _MAX_NETROM_QUALITY - q)

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "via_node": self.via_node,
            "source": self.source,
            "hops": self.hops,
            "flexnet_cost": self.flexnet_cost,
            "netrom_quality": self.netrom_quality,
            "connect_chain": list(self.connect_chain),
            "rank_metric": self.sort_metric(),
        }


def _rank_key(c: RouteCandidate) -> tuple[int, int, int]:
    """Ranking rule: FlexNet routes first (by cost), then NetROM (by hops, quality).

    FlexNet cost is the network's authoritative routing metric, so a FlexNet
    destination always outranks a NetROM one; NetROM is the fallback, ordered by
    fewest hops then best quality (higher = better). This is the single place the
    ranking policy lives — change here to reweight.
    """
    if c.source == "flexnet":
        cost = c.flexnet_cost if c.flexnet_cost is not None else 60000
        return (0, cost, c.hops)
    quality = c.netrom_quality if c.netrom_quality is not None else 0
    return (1, c.hops, _MAX_NETROM_QUALITY - quality)


# Signature: run one user-level command on a node and return the raw text.
RunUser = Callable[[NodeConfig, str], Awaitable[str]]


def _split_call(callsign: str) -> tuple[str, int | None]:
    base, _, ssid = callsign.partition("-")
    return base, (int(ssid) if ssid.isdigit() else None)


def _ssid_in_range(ssid: int | None, ssid_range: str) -> bool:
    """True if ``ssid`` falls in a FlexNet ``N-M`` range (any ssid if None)."""
    lo, _, hi = ssid_range.partition("-")
    if not (lo.isdigit() and hi.isdigit()):
        return True
    if ssid is None:
        return True
    return int(lo) <= ssid <= int(hi)


async def _resolve_alias(
    alias: str, source_nodes: list[NodeConfig], run_user: RunUser
) -> str | None:
    """Map a NODES alias (e.g. UAWNOD) to a callsign via bare ``N`` output."""

    async def one(cfg: NodeConfig) -> str | None:
        try:
            text = await run_user(cfg, "N")
        except Exception as e:  # unreachable node etc. — skip, best-effort
            logger.debug("alias resolve: %s failed: %s", cfg.callsign, e)
            return None
        for node in parse_bpq_nodes(text):
            if node.alias.upper() == alias:
                return node.callsign
        return None

    for result in await asyncio.gather(*(one(c) for c in source_nodes)):
        if result:
            return result
    return None


async def _probe_node(
    cfg: NodeConfig, base: str, ssid: int | None, callsign: str, run_user: RunUser
) -> RouteCandidate | None:
    """Query one source node's D + N tables; return its best candidate (or None)."""
    best: RouteCandidate | None = None

    def consider(cand: RouteCandidate) -> None:
        nonlocal best
        if best is None or _rank_key(cand) < _rank_key(best):
            best = cand

    chain = [f"C {callsign}"]

    if cfg.type in _FLEXNET_TYPES:
        try:
            text = await run_user(cfg, f"D {base}")
            for d in parse_bpq_flexnet_destinations(text):
                if d.callsign == base and _ssid_in_range(ssid, d.ssid_range):
                    consider(
                        RouteCandidate(
                            target=callsign,
                            via_node=cfg.callsign,
                            source="flexnet",
                            hops=1,
                            connect_chain=chain,
                            flexnet_cost=d.cost,
                            detail={"ssid_range": d.ssid_range},
                        )
                    )
        except Exception as e:  # noqa: BLE001 — best-effort per-node
            logger.debug("flexnet probe %s failed: %s", cfg.callsign, e)

    try:
        text = await run_user(cfg, f"N {callsign}")
        route = netrom_best_route(text)
        if route is not None:
            consider(
                RouteCandidate(
                    target=callsign,
                    via_node=cfg.callsign,
                    source="netrom",
                    hops=route.hops,
                    connect_chain=chain,
                    netrom_quality=route.quality,
                    detail={"via": route.via, "obs": str(route.obs)},
                )
            )
    except Exception as e:  # noqa: BLE001 — best-effort per-node
        logger.debug("netrom probe %s failed: %s", cfg.callsign, e)

    return best


async def discover_routes(
    target: str, all_nodes: dict[str, NodeConfig], run_user: RunUser
) -> list[RouteCandidate]:
    """Discover ranked routes to ``target`` across all configured console nodes.

    Returns the candidates ordered best-first (``_rank_key``). Empty if no
    configured node can reach the target. Per-node query failures are swallowed.
    """
    target = target.strip().upper()
    source_nodes = [c for c in all_nodes.values() if c.type in _SOURCE_TYPES]
    if not source_nodes:
        return []

    callsign = target
    if not _HAS_SSID.match(target):
        # Bare token: may be an alias — try to resolve, else treat as a callsign.
        resolved = await _resolve_alias(target, source_nodes, run_user)
        if resolved:
            logger.info("discovery: alias %s -> %s", target, resolved)
            callsign = resolved

    base, ssid = _split_call(callsign)

    probed = await asyncio.gather(
        *(_probe_node(c, base, ssid, callsign, run_user) for c in source_nodes)
    )
    candidates = [c for c in probed if c is not None]
    candidates.sort(key=_rank_key)
    return candidates
