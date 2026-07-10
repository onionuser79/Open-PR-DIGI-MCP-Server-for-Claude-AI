"""Route-discovery tests — a fake run_user returns canned D/N output per node,
so no network is touched; only the query/parse/rank logic is exercised."""

from __future__ import annotations

from pr_digi_mcp.config import NodeConfig
from pr_digi_mcp.discovery import RouteCandidate, discover_routes


def _cfg(call: str, typ: str) -> NodeConfig:
    return NodeConfig(
        callsign=call, type=typ, sys_required=False,
        telnet_host="h", telnet_port=23, user="u",
    )


# IR1UAW-10 is a cheap FlexNet dest on XN-14 (cost 3) and also NetROM-reachable
# (quality 254, 3 hops) via XN-15. UAWNOD is its NODES alias.
_XN14_D = "\nIR1UAW  8-8    324  IR1UAW 10-10     3\n=>"
_XN14_N_DETAIL = (
    "\nrouting UAWNET:IR1UAW-10 v IR3UHU-2\n\n"
    "  IR1UAW-10 IR1UAW-10 254/6   0.51s  2 hops\n"
    "> IR1UAW-10 IR3UHU-2  254/6   0.50s  3 hops\n\n=>"
)
_XN15_N_DETAIL = (
    "\nrouting UAWNET:IR1UAW-10 v IW2OHX-14\n\n"
    "> IR1UAW-10 IW2OHX-14 200/6   0.90s  4 hops\n\n=>"
)
_BARE_N = "\nUAWNET:IR1UAW-10   BOLNET:IW2OHX-14\n=>"


def _make_run_user(table: dict[tuple[str, str], str]):
    async def run_user(cfg: NodeConfig, command: str, **kw: object) -> str:
        return table.get((cfg.callsign, command), "")
    return run_user


async def test_discover_prefers_lowest_cost_flexnet() -> None:
    nodes = {"XN-14": _cfg("XN-14", "xnet"), "XN-15": _cfg("XN-15", "xnet")}
    run_user = _make_run_user({
        ("XN-14", "D IR1UAW"): _XN14_D,
        ("XN-14", "N IR1UAW-10"): _XN14_N_DETAIL,
        ("XN-15", "N IR1UAW-10"): _XN15_N_DETAIL,
        # XN-15 has no matching FlexNet dest
    })
    routes = await discover_routes("IR1UAW-10", nodes, run_user)
    assert routes, "expected at least one candidate"
    best = routes[0]
    # FlexNet cost 3 on XN-14 beats NetROM (inverted quality 256-254=2 -> hmm)
    assert best.via_node == "XN-14"
    assert best.connect_chain == ["C IR1UAW-10"]
    # every candidate targets the same callsign
    assert all(r.target == "IR1UAW-10" for r in routes)


async def test_ranking_and_fallback_order() -> None:
    # Two nodes both reach the target via NetROM with different quality/hops.
    nodes = {"XN-14": _cfg("XN-14", "xnet"), "XN-15": _cfg("XN-15", "xnet")}
    run_user = _make_run_user({
        ("XN-14", "N IR1UAW-10"): _XN14_N_DETAIL,   # q254, 3 hops
        ("XN-15", "N IR1UAW-10"): _XN15_N_DETAIL,   # q200, 4 hops
    })
    routes = await discover_routes("IR1UAW-10", nodes, run_user)
    order = [r.via_node for r in routes]
    # Higher quality (254 -> lower inverted metric) ranks first; XN-15 is the
    # fallback the caller would try next.
    assert order == ["XN-14", "XN-15"]


async def test_alias_resolution() -> None:
    nodes = {"XN-14": _cfg("XN-14", "xnet")}
    run_user = _make_run_user({
        ("XN-14", "N"): _BARE_N,
        ("XN-14", "D IR1UAW"): _XN14_D,
        ("XN-14", "N IR1UAW-10"): _XN14_N_DETAIL,
    })
    routes = await discover_routes("UAWNET", nodes, run_user)
    assert routes and routes[0].target == "IR1UAW-10"
    assert routes[0].via_node == "XN-14"


async def test_ssid_range_match() -> None:
    # Target with an SSID must fall inside the FlexNet range to match.
    nodes = {"XN-14": _cfg("XN-14", "xnet")}
    run_user = _make_run_user({("XN-14", "D IR1UAW"): _XN14_D})
    # IR1UAW-10 matches the 10-10 range (cost 3); IR1UAW-9 matches nothing.
    hit = await discover_routes("IR1UAW-10", nodes, run_user)
    assert hit and hit[0].flexnet_cost == 3
    miss = await discover_routes("IR1UAW-9", nodes, run_user)
    assert miss == []


async def test_no_route_returns_empty() -> None:
    nodes = {"XN-14": _cfg("XN-14", "xnet")}
    run_user = _make_run_user({})  # node knows nothing
    assert await discover_routes("ZZ9ZZ-1", nodes, run_user) == []


async def test_bpq_source_skips_flexnet_query() -> None:
    # A plain BPQ node has no FlexNet table; only its NetROM detail is consulted.
    calls: list[str] = []

    async def run_user(cfg: NodeConfig, command: str, **kw: object) -> str:
        calls.append(command)
        return _XN14_N_DETAIL if command == "N IR1UAW-10" else ""

    nodes = {"BP-15": _cfg("BP-15", "bpq")}
    routes = await discover_routes("IR1UAW-10", nodes, run_user)
    assert routes and routes[0].source == "netrom"
    assert not any(c.startswith("D ") for c in calls)


def test_route_candidate_as_dict() -> None:
    c = RouteCandidate(
        target="IR1UAW-10", via_node="XN-14", source="flexnet", hops=1,
        connect_chain=["C IR1UAW-10"], flexnet_cost=3,
    )
    d = c.as_dict()
    assert d["via_node"] == "XN-14" and d["rank_metric"] == 3
    assert d["connect_chain"] == ["C IR1UAW-10"]
