"""Unit tests for the (X)Net command builders and validators."""

from __future__ import annotations

import pytest

from pr_digi_mcp import commands

# ── validators ─────────────────────────────────────────────────────────────


def test_validate_callsign_normalises_case() -> None:
    assert commands.validate_callsign("iw2ohx-14") == "IW2OHX-14"


def test_validate_callsign_accepts_no_ssid() -> None:
    assert commands.validate_callsign("IR5S") == "IR5S"


@pytest.mark.parametrize("bad", ["", "TOOLONGCALL", "IW2OHX-16", "IW2OHX-99", "x"])
def test_validate_callsign_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError):
        commands.validate_callsign(bad)


def test_validate_token_rejects_cr_lf_injection() -> None:
    with pytest.raises(ValueError):
        commands.validate_token("alias\rRESET", field="alias")
    with pytest.raises(ValueError):
        commands.validate_token("a\nb", field="x")


def test_validate_token_passes_clean() -> None:
    assert commands.validate_token("BOLNET", field="alias") == "BOLNET"


@pytest.mark.parametrize("bad", [-1, 256, 999])
def test_validate_port_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError):
        commands.validate_port(bad)


# ── router add ───────────────────────────────────────────────────────────


def test_router_add_bc_port_only() -> None:
    assert commands.build_router_add("bc", port=14) == "ROUTER BC ADD 14"


def test_router_add_bc_rejects_call() -> None:
    with pytest.raises(ValueError):
        commands.build_router_add("bc", port=14, call="IW2OHX-13")


def test_router_add_flexnet() -> None:
    cmd = commands.build_router_add("flexnet", port=6, call="iq2lb-6")
    assert cmd == "ROUTER FLEXNET ADD 6 IQ2LB-6"


def test_router_add_flexnet_with_via() -> None:
    cmd = commands.build_router_add("flexnet", port=6, call="IQ2LB-6", via="IW2OHX-14")
    assert cmd == "ROUTER FLEXNET ADD 6 IQ2LB-6 IW2OHX-14"


def test_router_add_flexnet_requires_call() -> None:
    with pytest.raises(ValueError):
        commands.build_router_add("flexnet", port=6)


def test_router_add_local_full() -> None:
    cmd = commands.build_router_add(
        "local", port=2, call="IW2OHX-13", dist="nd", alias="BOLNET"
    )
    assert cmd == "ROUTER LOCAL ADD 2 IW2OHX-13 nd BOLNET"


def test_router_add_local_rejects_bad_dist() -> None:
    with pytest.raises(ValueError):
        commands.build_router_add("local", port=2, call="IW2OHX-13", dist="zz")


def test_router_add_dist_only_for_local() -> None:
    with pytest.raises(ValueError):
        commands.build_router_add("flexnet", port=6, call="IQ2LB-6", dist="nd")


def test_router_add_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        commands.build_router_add("bogus", port=1)


# ── router del ───────────────────────────────────────────────────────────


def test_router_del_bc_port_only() -> None:
    assert commands.build_router_del("bc", port=14) == "ROUTER BC DEL 14"


def test_router_del_flexnet_requires_call() -> None:
    with pytest.raises(ValueError):
        commands.build_router_del("flexnet", port=6)


def test_router_del_flexnet() -> None:
    assert (
        commands.build_router_del("flexnet", port=6, call="IQ2LB-6")
        == "ROUTER FLEXNET DEL 6 IQ2LB-6"
    )


# ── ip / arp ───────────────────────────────────────────────────────────────


def test_iproute_add() -> None:
    cmd = commands.build_iproute_add(net="44.134.27.0/24", iface="ETHER", gw="44.134.24.1")
    assert cmd == "IPRoute ADD 44.134.27.0/24 ETHER 44.134.24.1"


def test_iproute_del() -> None:
    assert commands.build_iproute_del(net="44.134.27.0/24") == "IPRoute DEL 44.134.27.0/24"


def test_arp_add() -> None:
    assert (
        commands.build_arp_add(ip="44.134.24.1", iface="ETHER", hw="D8:3A:DD:4E:14:79")
        == "ARp ADD 44.134.24.1 ETHER D8:3A:DD:4E:14:79"
    )


def test_arp_del() -> None:
    assert commands.build_arp_del(ip="44.134.24.1") == "ARp DEL 44.134.24.1"


def test_iproute_add_rejects_injection() -> None:
    with pytest.raises(ValueError):
        commands.build_iproute_add(net="x\rRESET", iface="ETHER", gw="1.2.3.4")


# ── BPQ builders ─────────────────────────────────────────────────────────


def test_validate_alias() -> None:
    assert commands.validate_alias("bolnet") == "BOLNET"
    with pytest.raises(ValueError):
        commands.validate_alias("TOOLONG7")
    with pytest.raises(ValueError):
        commands.validate_alias("has space")


def test_bpq_node_add() -> None:
    cmd = commands.build_bpq_node_add(
        alias="BOLNET", call="IW2OHX-13", qual=200, neighbour="IW2OHX-14"
    )
    assert cmd == "NODE ADD BOLNET:IW2OHX-13 200 IW2OHX-14"


def test_bpq_node_add_rejects_bad_quality() -> None:
    with pytest.raises(ValueError):
        commands.build_bpq_node_add(
            alias="BOLNET", call="IW2OHX-13", qual=999, neighbour="IW2OHX-14"
        )


def test_bpq_node_del() -> None:
    assert commands.build_bpq_node_del(call="IW2OHX-13") == "NODE DEL IW2OHX-13"


def test_bpq_route_set_plain() -> None:
    assert (
        commands.build_bpq_route_set(call="IW2OHX-14", port=2, qual=200)
        == "ROUTES IW2OHX-14 2 200"
    )


def test_bpq_route_set_locked() -> None:
    assert (
        commands.build_bpq_route_set(call="IW2OHX-14", port=2, qual=200, lock=True)
        == "ROUTES IW2OHX-14 2 200 !"
    )


def test_bpq_param_get_port() -> None:
    assert commands.build_bpq_param("TXDELAY", port=2) == "TXDELAY 2"


def test_bpq_param_set_system() -> None:
    assert commands.build_bpq_param("L3TTL", value="25") == "L3TTL 25"


def test_bpq_param_set_port() -> None:
    assert commands.build_bpq_param("MAXFRAME", value="4", port=2) == "MAXFRAME 2 4"


def test_bpq_param_rejects_unknown_name() -> None:
    # Critical: a non-param name must not pass (would smuggle a command).
    with pytest.raises(ValueError):
        commands.build_bpq_param("REBOOT")
    with pytest.raises(ValueError):
        commands.build_bpq_param("NODE", value="DEL IW2OHX-13")


def test_bpq_param_port_on_system_param_rejected() -> None:
    with pytest.raises(ValueError):
        commands.build_bpq_param("L3TTL", value="25", port=2)


# ── monitor port selection ─────────────────────────────────────────────────


@pytest.mark.parametrize("spec", ["*", "", " ", "all", "ALL"])
def test_monitor_selection_all(spec: str) -> None:
    sel = commands.parse_monitor_selection(spec)
    assert sel.arg == "*"
    assert sel.filter_ports is None


def test_monitor_selection_single_port_native() -> None:
    sel = commands.parse_monitor_selection("8")
    assert sel.arg == "8"
    assert sel.filter_ports is None


def test_monitor_selection_single_after_dedup() -> None:
    # Duplicate of one port collapses to a native single-port selection.
    sel = commands.parse_monitor_selection("8 8")
    assert sel == commands.MonitorSelection("8", None)


@pytest.mark.parametrize("spec", ["7 8", "7,8", "8,7", "8 7 8"])
def test_monitor_selection_multi_filters(spec: str) -> None:
    sel = commands.parse_monitor_selection(spec)
    assert sel.arg == "*"
    assert sel.filter_ports == frozenset({7, 8})


@pytest.mark.parametrize("spec", ["x", "7 x", "99", "24", "-1"])
def test_monitor_selection_rejects_bad(spec: str) -> None:
    with pytest.raises(ValueError):
        commands.parse_monitor_selection(spec)


def test_filter_monitor_text_keeps_only_requested_ports() -> None:
    text = (
        "\r\nMonitoring * [ 0 1 ]\r\n\r\n"
        "8:fm IQ2LB to IW2OHX-14 ctl I76 pid CE [3]\n"
        "0000 33 2B 0D                3+.\n"
        "\n"
        "13:fm IR1UAW-10 to IW2OHX-14 ctl RR0+\n"
        "7:fm IQ2LB to IW2OHX-14 ctl RR6v\n"
    )
    out = commands.filter_monitor_text(text, frozenset({7, 8}))
    assert "Monitoring *" in out          # preamble kept
    assert "8:fm IQ2LB" in out            # port 8 kept
    assert "33 2B 0D" in out              # its hex continuation kept
    assert "7:fm IQ2LB" in out            # port 7 kept
    assert "13:fm IR1UAW-10" not in out   # port 13 dropped
