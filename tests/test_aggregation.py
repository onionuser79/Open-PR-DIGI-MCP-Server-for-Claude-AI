"""Aggregation tool tests — the per-node run helpers are monkeypatched, so no
network is touched; only the collect/search + parse + merge logic is exercised."""

from __future__ import annotations

from typing import Any

import pytest

import pr_digi_mcp.server as server
from pr_digi_mcp.config import NodeConfig

XNET_L = """
Link to       dst  Q/T
 8:IQ2LB        1 I   1
 1:IW2OHX-12    4 F   1
"""

BPQ_ROUTES = """BOLHF:BP-1} Routes
> 3 IQ2LB     161 0
> 4 IW2OHX-14 161 41!
"""

BPQ_NODES = """BOLHF:BP-1} Nodes
BOLNET:IW2OHX-14   OHXGW:IW2OHX-1
"""


def _cfg(call: str, typ: str) -> NodeConfig:
    return NodeConfig(
        callsign=call, type=typ, sys_required=True, ssh_host="",
        telnet_host="h", telnet_port=23, user="u",
    )


@pytest.fixture
def fake_net(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_NODES", {"XN-1": _cfg("XN-1", "xnet"),
                                           "BP-1": _cfg("BP-1", "linbpq")})

    async def fake_user(cfg: NodeConfig, command: str, **kw: Any) -> str:
        return XNET_L if command == "L" else ""

    async def fake_sys(cfg: NodeConfig, command: str, **kw: Any) -> str:
        return {"ROUTES": BPQ_ROUTES, "NODES": BPQ_NODES}.get(command, "")

    monkeypatch.setattr(server, "_run_user", fake_user)
    monkeypatch.setattr(server, "_run_sys", fake_sys)


async def test_network_topology(fake_net: None) -> None:
    result = await server._collect_topology()
    nodes = result["nodes"]
    assert set(nodes) == {"XN-1", "BP-1"}
    assert nodes["XN-1"]["type"] == "xnet"
    assert any(nb["callsign"] == "IQ2LB" for nb in nodes["XN-1"]["neighbours"])
    assert any(nb["callsign"] == "DK0WUE-7" or nb["callsign"] == "IW2OHX-14"
               for nb in nodes["BP-1"]["neighbours"])


async def test_find_callsign(fake_net: None) -> None:
    result = await server._search_callsign("IQ2LB")
    assert result["callsign"] == "IQ2LB"
    # IQ2LB shows up in XN-1's link table AND BP-1's routes.
    assert set(result["found_on"]) == {"XN-1", "BP-1"}
    assert any(m["where"] == "link" for m in result["detail"]["XN-1"]["matches"])
    assert any(m["where"] == "route" for m in result["detail"]["BP-1"]["matches"])


async def test_aggregation_isolates_node_errors(
    fake_net: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(cfg: NodeConfig, command: str, **kw: Any) -> str:
        raise RuntimeError("node down")

    monkeypatch.setattr(server, "_run_sys", boom)  # BP-1 now fails
    result = await server._search_callsign("IQ2LB")
    assert "error" in result["detail"]["BP-1"]          # captured, not raised
    assert result["found_on"] == ["XN-1"]               # XN-1 still searched
