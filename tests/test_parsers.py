"""Parser tests — sample text is real output captured from live nodes."""

from __future__ import annotations

from pr_digi_mcp.parsers import (
    netrom_best_route,
    parse_bpq_flexnet_destinations,
    parse_bpq_flexnet_links,
    parse_bpq_links,
    parse_bpq_nodes,
    parse_bpq_routes,
    parse_heard,
    parse_netrom_route_detail,
    parse_xnet_links,
    to_dicts,
)

ROUTES = """BOLHF:IW2OHX-15} Routes
> 3 DK0WUE-7  161 29
> 7 IQ2LB     160 0
> 4 IW2OHX-14 161 41!
  2 K5DAT-7   161 0!
"""

NODES = """BOLHF:IW2OHX-15} Nodes
BOLNET:IW2OHX-14    OHXGW:IW2OHX-1      BBSMI:IW2OHX-8
DK0WUE-7 is not a pair here
UAWNET:IR1UAW-10
"""

LINKS = """BOLHF:IW2OHX-15} Links
N3HYM-5   IW2OHX-15  S=5 P=3 T=3 V=2.2 Q=0
IW2OHX-14 IW2OHX-15  S=5 P=4 T=3 V=2 Q=0
"""

FL = """BPQBOL:IW2OHX-13} FlexNet Links:
Link         Port  Status     LT     KA     Uptime      Routes
------------ ----  ---------  ------ -----  ----------  ------
IW2OHX-14    3     CONNECTED  60s    389    20:24:20    116
IW2OHX-4     3     CONNECTED  60s    355    18:40:06    2
"""

FLEXDEST = """BPQBOL:IW2OHX-13} FlexNet Destinations:
IW2OHX 14-14     1      IK1NHL 4-15     10!     IK6IHL 6-6      33!
IQ2LB  6-6       7!
"""

XNET_L = """
Link to       dst  Q/T    rtt    tx connect
11:IR3UHU-2   138 I   0   0/0     0  2h 13m
 6:IW2OHX-1     1 Q 161   -/-     0 20h 23m
 1:IW2OHX-12    4 F   1   0/1     0  9h 07m
 7:IQ2LB          F   -   -/-     -  - - -
"""


def test_parse_bpq_routes() -> None:
    routes = parse_bpq_routes(ROUTES)
    assert len(routes) == 4
    by_call = {r.callsign: r for r in routes}
    assert by_call["DK0WUE-7"].port == 3
    assert by_call["DK0WUE-7"].quality == 161
    assert by_call["DK0WUE-7"].count == 29
    assert by_call["DK0WUE-7"].active is True
    assert by_call["DK0WUE-7"].locked is False
    assert by_call["IW2OHX-14"].locked is True and by_call["IW2OHX-14"].count == 41
    assert by_call["K5DAT-7"].active is False and by_call["K5DAT-7"].locked is True


def test_parse_bpq_nodes() -> None:
    nodes = parse_bpq_nodes(NODES)
    pairs = {(n.alias, n.callsign) for n in nodes}
    assert ("BOLNET", "IW2OHX-14") in pairs
    assert ("OHXGW", "IW2OHX-1") in pairs
    assert ("BBSMI", "IW2OHX-8") in pairs
    assert ("UAWNET", "IR1UAW-10") in pairs
    # header line "BOLHF:IW2OHX-15} Nodes" is skipped
    assert not any(n.alias == "BOLHF" for n in nodes)


def test_parse_bpq_links() -> None:
    links = parse_bpq_links(LINKS)
    assert len(links) == 2
    assert links[0].far == "N3HYM-5" and links[0].local == "IW2OHX-15"
    assert links[0].state == 5 and links[0].port == 3 and links[0].version == "2.2"
    assert links[1].far == "IW2OHX-14" and links[1].port == 4 and links[1].version == "2"


def test_parse_bpq_flexnet_links() -> None:
    fl = parse_bpq_flexnet_links(FL)
    assert len(fl) == 2
    assert fl[0].callsign == "IW2OHX-14" and fl[0].port == 3
    assert fl[0].status == "CONNECTED" and fl[0].routes == 116
    assert fl[0].keepalives == 389 and fl[0].uptime == "20:24:20"


def test_parse_bpq_flexnet_destinations() -> None:
    dests = parse_bpq_flexnet_destinations(FLEXDEST)
    by = {d.callsign: d for d in dests}
    assert by["IW2OHX"].ssid_range == "14-14" and by["IW2OHX"].cost == 1
    assert by["IW2OHX"].cached is False
    assert by["IK1NHL"].cost == 10 and by["IK1NHL"].cached is True
    assert by["IQ2LB"].cost == 7 and by["IQ2LB"].cached is True


def test_parse_xnet_links() -> None:
    links = parse_xnet_links(XNET_L)
    by = {ln.callsign: ln for ln in links}
    assert by["IR3UHU-2"].port == 11 and by["IR3UHU-2"].dest_type == "INP3"
    assert by["IW2OHX-1"].dest_type == "NETROM"
    assert by["IW2OHX-12"].dest_type == "FLEXNET"
    # the "7:IQ2LB ... F" row (no dst count) still parses
    assert by["IQ2LB"].dest_type == "FLEXNET" and by["IQ2LB"].port == 7


# Real (X)Net `D` output (FlexNet destinations, no cached markers, 4 per line).
XNET_D = """
DB0GW   0-9     13  DB0RES  0-9     13  DK0WUE  0-13   301  HB9ON  15-15   300
IR2UFV  0-8      4  IR1UAW  8-8    324  IR1UAW 10-10     3  IW2OHX 13-13     1
=>"""

# Real (X)Net `N <call>` route detail.
NETROM_DETAIL = """
routing UAWNET:IR1UAW-10 v IR3UHU-2

  IR1UAW-10 IR1UAW-10 254/6   0.51s  2 hops
> IR1UAW-10 IR3UHU-2  254/6   0.50s  3 hops

=>"""

# Real (X)Net `MH` heard list.
XNET_MH = """
 p:call      - date     time         rxbytes
 9:DK0WUE      10.07.26 13:00:49    14358654
13:IR1UAW-10   10.07.26 13:00:49    21716362
 3:IGATE       10.07.26 13:00:46     1424066
"""


def test_parse_xnet_d_via_flexnet_parser() -> None:
    # The (X)Net `D` format is the same CALL N-M COST[!] shape as BPQ FlexNet `D`.
    dests = parse_bpq_flexnet_destinations(XNET_D)
    by = {(d.callsign, d.ssid_range): d for d in dests}
    assert by[("IR1UAW", "10-10")].cost == 3
    assert by[("IR1UAW", "8-8")].cost == 324
    assert by[("IW2OHX", "13-13")].cost == 1
    assert by[("DK0WUE", "0-13")].cost == 301


def test_parse_netrom_route_detail() -> None:
    routes = parse_netrom_route_detail(NETROM_DETAIL)
    assert len(routes) == 2
    assert routes[0].via == "IR1UAW-10" and routes[0].hops == 2
    assert routes[0].quality == 254 and routes[0].obs == 6
    assert routes[0].selected is False
    assert routes[1].via == "IR3UHU-2" and routes[1].hops == 3
    assert routes[1].selected is True
    best = netrom_best_route(NETROM_DETAIL)
    assert best is not None and best.via == "IR3UHU-2" and best.selected is True


def test_parse_heard() -> None:
    heard = parse_heard(XNET_MH)
    by = {h.callsign: h for h in heard}
    assert by["DK0WUE"].port == 9 and by["DK0WUE"].rxbytes == 14358654
    assert by["IR1UAW-10"].port == 13 and by["IR1UAW-10"].time == "13:00:49"
    # header line is skipped
    assert not any(h.callsign == "call" for h in heard)


def test_parse_heard_tolerant_of_other_families() -> None:
    # Non-(X)Net heard output degrades to empty, never raises.
    assert parse_heard("BPQBOL:IW2OHX-13} Nothing heard here\r\n") == []


def test_to_dicts() -> None:
    routes = parse_bpq_routes(ROUTES)
    d = to_dicts(routes)
    assert isinstance(d, list) and isinstance(d[0], dict)
    assert d[0]["callsign"] == "DK0WUE-7"
