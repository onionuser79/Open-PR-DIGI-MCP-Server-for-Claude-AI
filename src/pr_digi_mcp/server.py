"""FastMCP server entry point — v0.2 exposes xnet + chained-AX.25 tools.

Tools surfaced in v0.2:
    list_nodes()                              — enumerate configured nodes
    xnet_run_command(node, command, ...)      — generic command runner (Tier 1: read)
    xnet_links(node)                          — L command (current AX.25 links)
    xnet_destinations(node, filter=None)      — D command (destination/route table)
    xnet_l_star(node)                         — L * (full routing dump)
    xnet_mh(node)                             — MH (heard list)
    xnet_users(node)                          — U command (active users)
    xnet_info(node)                           — INFO / banner

All tools work uniformly on both direct xnet nodes (your (X)Net nodes)
and chained-AX.25 nodes (a chained node via its transit hop). The transport factory
in `pr_digi_mcp.transports` picks the right backend based on node type.

(X)Net write / SYS tools (v0.4) are now wired across all three tiers:
    Tier 1 (routing)      — xnet_router_add, xnet_router_del*, xnet_disconnect*
    Tier 2 (IP / config)  — xnet_iproute_*, xnet_arp_*, xnet_set_nameserver,
                            xnet_set_param, xnet_port_param, xnet_service
    Tier 2 (diagnostics)  — xnet_monitor, xnet_ipdump, xnet_netstat,
                            xnet_processes, xnet_statistics, xnet_log, xnet_ping,
                            xnet_arp_list, xnet_iproute_list, xnet_router_list
    Tier 2 (files)        — xnet_dir, xnet_read_file, xnet_copy_file,
                            xnet_rename_file
    Tier 3 (DANGEROUS*)   — xnet_attach, xnet_detach, xnet_set_identity,
                            xnet_set_ip, xnet_set_subnet, xnet_set_time,
                            xnet_remove_file, xnet_reset, xnet_ipstop,
                            xnet_set_password
    Escape hatch          — xnet_sys_command (verbatim, danger-classified)

BPQ32 / LinBPQ tools (v0.5) mirror this across sections A-F:
    A diagnostics  — bpq_version, bpq_stats, bpq_listen, bpq_validcall,
                     bpq_iproute, bpq_arp, bpq_nat, bpq_ping, bpq_telstatus,
                     bpq_axresolver, bpq_axmheard (LINKS/USERS/MHEARD/INFO use
                     the generic xnet_* tools; PORTS/ROUTES/NODES have wrappers)
    B routing      — bpq_node_add, bpq_node_del*, bpq_route_set
    C port/CMS     — bpq_startport, bpq_stopport*, bpq_startcms, bpq_stopcms*,
                     bpq_kiss*, bpq_telreconfig*
    D persistence  — bpq_savemh, bpq_savenodes, bpq_sendnodes, bpq_getportctext
    E parameters   — bpq_get_param, bpq_set_param (name allowlisted)
    F lifecycle    — bpq_findbuffs, bpq_wl2ksysop(*on SET), bpq_reconfig*,
                     bpq_reboot*
    Escape hatch   — bpq_sysop_command (verbatim, BPQ-dialect danger-classified)
    FlexNet        — bpq_flexnet_links (FL), bpq_flexnet_destinations (D [query])
                     — linbpq-flexnet only (type='linbpq': your LinBPQ nodes)

Tools marked * refuse to run unless called with confirm=True, which the LLM
must set ONLY after the human operator has explicitly approved the exact
command (see safety.py). Structured write tools target type='xnet' V1.39 nodes
(your (X)Net nodes); a chained PC/Flexnet node has a different
command set and is reachable only through the escape hatch.

The server runs on stdio (MCP standard). Register with Claude Code via:
    claude mcp add pr-digi-mcp /path/to/python -m pr_digi_mcp.server
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import commands, parsers, safety
from .config import NodeConfig, load_nodes
from .transports import open_transport

logger = logging.getLogger(__name__)
mcp = FastMCP("pr-digi-mcp")

_NODES: dict[str, NodeConfig] = {}

# Node types whose CLI is xnet/PCF-compatible (single-letter commands:
# L, D, MH, U, INFO). xnet V1.39 + PC/Flexnet 3.3g share this surface.
_XNET_COMPATIBLE_TYPES = frozenset({"xnet", "xnet_chained"})

# Node types whose CLI is BPQ-compatible (BPQ32 / LinBPQ console).
# Most single-letter shortcuts are the same as xnet (L, MH, U, INFO,
# `D` for destinations / routes) but BPQ has a richer command set
# behind the PASSWORD-gated sysop mode (PORTS, ROUTES, NODE ADD/DEL,
# RECONFIG, REBOOT, KISS, etc. — see SYSOP guide).
_BPQ_COMPATIBLE_TYPES = frozenset({"bpq", "linbpq"})

# Read-only commands that share the same letter on both families.
_GENERIC_COMPATIBLE_TYPES = _XNET_COMPATIBLE_TYPES | _BPQ_COMPATIBLE_TYPES


def _get_node(name: str, allowed: frozenset[str] = _GENERIC_COMPATIBLE_TYPES) -> NodeConfig:
    """Look up a node and check its type is in `allowed`."""
    if name not in _NODES:
        known = ", ".join(sorted(_NODES)) or "(none configured)"
        raise ValueError(f"Unknown node {name!r}. Configured: {known}")
    cfg = _NODES[name]
    if cfg.type not in allowed:
        raise ValueError(
            f"Node {name!r} has type {cfg.type!r}; tool requires "
            f"one of {sorted(allowed)}"
        )
    return cfg


def _get_xnet_node(name: str) -> NodeConfig:
    """Compat shim — accept any xnet/PCF/BPQ node for generic read tools."""
    return _get_node(name, _GENERIC_COMPATIBLE_TYPES)


def _get_bpq_node(name: str) -> NodeConfig:
    """Look up a node and require it be a BPQ32 / LinBPQ console."""
    return _get_node(name, _BPQ_COMPATIBLE_TYPES)


def _get_xnet_writable(name: str) -> NodeConfig:
    """Require a direct (X)Net V1.39 node — the target of structured write tools.

    Excludes 'xnet_chained' (PC/Flexnet nodes use a different command set) and
    BPQ. Use the escape hatch / bpq_sysop_command for those.
    """
    return _get_node(name, frozenset({"xnet"}))


def _get_linbpq_node(name: str) -> NodeConfig:
    """Require a LinBPQ node — the only BPQ type running linbpq-flexnet.

    FlexNet commands (FL, D) exist only on the linbpq-flexnet build (IW2OHX-13,
    IR2UFV). The Windows BPQ32 node (type 'bpq') has no FlexNet, so it is
    excluded here.
    """
    return _get_node(name, frozenset({"linbpq"}))


async def _run_sys(
    cfg: NodeConfig, command: str, *, idle_ms: int = 600, max_wait_s: float = 15.0
) -> str:
    """Open the transport, elevate to SYS, run one command, return raw output."""
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.run_command(command, idle_ms=idle_ms, max_wait_s=max_wait_s)


async def _run_user(
    cfg: NodeConfig, command: str, *, idle_ms: int = 600, max_wait_s: float = 15.0
) -> str:
    """Run a non-privileged read command (no SYS elevation needed)."""
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command(command, idle_ms=idle_ms, max_wait_s=max_wait_s)


async def _capture_sys(cfg: NodeConfig, command: str, duration_s: float) -> str:
    """Elevate to SYS and capture a streaming command for a fixed window."""
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.capture(command, duration_s)


@mcp.tool()
def list_nodes() -> list[dict[str, str | bool]]:
    """List all configured digi nodes — callsign, type, access path, SYS-required flag.

    Use this first to discover which nodes the MCP server knows about.
    v0.2 supports types 'xnet' (direct) and 'xnet_chained' (AX.25-via-outer).
    BPQ32 / LinBPQ types appear here but tool calls return an error until
    later phases land.
    """
    out: list[dict[str, str | bool]] = []
    for cfg in _NODES.values():
        if cfg.type == "xnet_chained":
            access = f"via {cfg.transit_via} → {cfg.connect_command!r}"
        else:
            access = f"{cfg.telnet_host}:{cfg.telnet_port}"
        out.append(
            {
                "callsign": cfg.callsign,
                "type": cfg.type,
                "access": access,
                "user": cfg.user,
                "sys_required": cfg.sys_required,
                "description": cfg.description,
            }
        )
    return out


@mcp.tool()
async def xnet_run_command(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
    command: Annotated[
        str,
        Field(description="The literal xnet command to send (e.g. 'L', 'D', 'L *')"),
    ],
    sys_required: Annotated[
        bool,
        Field(
            description=(
                "Elevate to SYS prompt before issuing the command. v0.1 has no "
                "write tools yet — this exists for read-only commands that "
                "still need the SYS context (rare)."
            )
        ),
    ] = False,
    idle_ms: Annotated[
        int,
        Field(
            description=(
                "Milliseconds of stream silence before considering the response "
                "complete. Bump for slow links."
            ),
            ge=100,
            le=5000,
        ),
    ] = 400,
) -> str:
    """Run an arbitrary read-only command on an (X)Net node and return the raw output.

    The command is sent verbatim. Output includes any prompt the node prints
    after the result. Errors raise a clear message — common causes are
    missing credentials in keychain/YAML, SSH connection failures, or the
    target node being unreachable through HAMNET.
    """
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        if sys_required:
            await xn.elevate_sys()
        return await xn.run_command(command, idle_ms=idle_ms)


# ── convenience tools (thin wrappers around run_command) ──────────────────


@mcp.tool()
async def xnet_links(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
) -> str:
    """Return the `L` output — current AX.25 links visible to this node."""
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command("L", idle_ms=600)


@mcp.tool()
async def xnet_l_star(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
) -> str:
    """Return the `L *` output — full routing/destination dump.

    Larger than `L`. Includes destination call, SSID range, port, RTT array.
    """
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command("L *", idle_ms=600, max_wait_s=20)


@mcp.tool()
async def xnet_destinations(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
    filter: Annotated[  # noqa: A002
        str | None,
        Field(description="Optional callsign filter, e.g. a destination callsign"),
    ] = None,
) -> str:
    """Return the `D` output — destination/route table.

    With `filter`, sends `D <filter>` for a focused view of routes to that destination.
    """
    cmd = f"D {filter}" if filter else "D"
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command(cmd)


@mcp.tool()
async def xnet_mh(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
) -> str:
    """Return the `MH` output — heard list (stations heard recently on RF)."""
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command("MH")


@mcp.tool()
async def xnet_users(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
) -> str:
    """Return the `U` output — active user sessions on the node."""
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command("U")


@mcp.tool()
async def xnet_info(
    node: Annotated[str, Field(description="Node callsign as configured in nodes.yaml")],
) -> str:
    """Return the `INFO` (or banner) output — version + identity of the node."""
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        return await xn.run_command("INFO")


# ── BPQ32 / LinBPQ sysop-mode tools ──────────────────────────────────────


@mcp.tool()
async def bpq_sysop_command(
    node: Annotated[
        str, Field(description="BPQ/LinBPQ node callsign as configured in nodes.yaml")
    ],
    command: Annotated[
        str,
        Field(
            description=(
                "BPQ console command to run AFTER `PASSWORD` elevation. "
                "Common sysop commands: PORTS, ROUTES, NODES, USERS, MHEARD, "
                "LISTEN, KISS, SAVEMH, SAVENODES, SENDNODES, RECONFIG, "
                "FINDBUFFS, GETPORTCTEXT, WL2KSYSOP, STOPPORT n, STARTPORT n, "
                "STOPCMS n, STARTCMS n, TELReconfig port ALL|USERS, NODE ADD "
                "ALIAS:CALL QUAL NEIGHBOUR, NODE DEL CALL, ROUTES CALL PORT "
                "QUAL [!]. See SYSOP guide for the full surface. Port/system "
                "parameter getters: TXDELAY, MAXFRAME, FRACK, RESPTIME, "
                "PPACLEN, RETRIES, QUALITY, PERSIST, TXTAIL, XMITOFF, "
                "DIGIFLAG, DIGIPORT, MAXUSERS, VALIDCALL, L3ONLY, BBSALIAS, "
                "FULLDUP, SOFTDCD; system: REMDUMP, OBSINIT, OBSMIN, "
                "NODESINT, L3TTL, L4RETRIES, L4TIMEOUT, T3, NODEIDLETIME, "
                "LINKEDFLAG, IDINTERVAL, MINQUAL, FULLCTEXT, HIDENODES, "
                "L4DELAY, L4WINDOW, BTINTERVAL. Reading parameters: omit the "
                "value. Writing: pass `param value` (or `param port_num value` "
                "for port params)."
            )
        ),
    ],
    idle_ms: Annotated[
        int,
        Field(
            description=(
                "Milliseconds of stream silence before the response is "
                "considered complete. Bump for verbose dumps (NODES, ROUTES)."
            ),
            ge=100,
            le=5000,
        ),
    ] = 600,
    confirm: Annotated[
        bool,
        Field(description="Required when the command is classified DANGEROUS — see docs"),
    ] = False,
) -> str:
    """Run a BPQ32 / LinBPQ console command in SYSOP mode.

    Authenticates with `PASSWORD` first (auto-detects whether the session
    is already privileged — BPQ replies `Ok` for local sessions and a
    5-number positional challenge for remote ones, which is solved against
    the configured SYS password). Then sends `command` verbatim and
    returns the raw response.

    DANGEROUS commands that change persistent or live state — `REBOOT`,
    `RECONFIG`, `STOPPORT`, `STOPCMS`, `KISS`, `TELReconfig`, `WL2KSYSOP`,
    and anything with a `DEL`/`KILL`/`FLUSH` token (e.g. `NODE DEL`) — are
    classified by safety.is_dangerous_command() and REFUSE to run unless
    confirm=True. The LLM may set confirm=True only after the human operator
    has explicitly approved.

    Read-only sysop commands (PORTS, ROUTES, NODES, USERS, MHEARD, LISTEN,
    parameter getters) are safe at any time.

    Reference: https://www.cantab.net/users/john.wiseman/Documents/Node%20SYSOP.html
    """
    cfg = _get_bpq_node(node)
    cmd = command.strip()
    if (
        safety.is_dangerous_command(cmd, dangerous_commands=safety.BPQ_DANGEROUS_COMMANDS)
        and not confirm
    ):
        return safety.approval_required(
            node=node,
            action="Run a privileged BPQ command classified as dangerous",
            command=cmd,
            risk="Verbatim BPQ sysop command flagged as state-changing/destructive.",
        )
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.run_command(cmd, idle_ms=idle_ms)


@mcp.tool()
async def bpq_ports(
    node: Annotated[
        str, Field(description="BPQ/LinBPQ node callsign as configured in nodes.yaml")
    ],
) -> str:
    """List the configured BPQ ports — number, driver, frequency/role description.

    Convenience wrapper around `PORTS` after `PASSWORD` elevation.
    """
    cfg = _get_bpq_node(node)
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.run_command("PORTS", idle_ms=600)


@mcp.tool()
async def bpq_routes(
    node: Annotated[
        str, Field(description="BPQ/LinBPQ node callsign as configured in nodes.yaml")
    ],
) -> str:
    """Show the BPQ route table — neighbours, port, quality, locked flag.

    Convenience wrapper around `ROUTES` after `PASSWORD` elevation.
    Routes are L2/AX.25 neighbour links (distinct from `NODES`, which is the
    L3/NetROM destination table).
    """
    cfg = _get_bpq_node(node)
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.run_command("ROUTES", idle_ms=800, max_wait_s=20)


@mcp.tool()
async def bpq_nodes(
    node: Annotated[
        str, Field(description="BPQ/LinBPQ node callsign as configured in nodes.yaml")
    ],
) -> str:
    """Show the BPQ NetROM nodes table — alias:call + quality per route.

    Convenience wrapper around `NODES`. Doesn't strictly require sysop on
    most BPQ builds, but we elevate to keep the response shape consistent
    across nodes.
    """
    cfg = _get_bpq_node(node)
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.run_command("NODES", idle_ms=800, max_wait_s=20)


# ── LinBPQ FlexNet (linbpq-flexnet) — only on type='linbpq' nodes ──────────


@mcp.tool()
async def bpq_flexnet_links(
    node: Annotated[
        str, Field(description="LinBPQ FlexNet node as configured in nodes.yaml")
    ],
) -> str:
    """Show the FlexNet links — `FL` (linbpq-flexnet).

    Per-neighbour table: Link, Port, Status (CONNECTED/PENDING), LT (link time),
    KA (keepalive count), Uptime, and Routes advertised. Only on linbpq-flexnet
    builds (your LinBPQ nodes).
    """
    return await _run_sys(_get_linbpq_node(node), "FL", idle_ms=800)


@mcp.tool()
async def bpq_flexnet_destinations(
    node: Annotated[
        str, Field(description="LinBPQ FlexNet node as configured in nodes.yaml")
    ],
    query: Annotated[
        str | None,
        Field(
            description=(
                "Omit for the full destination table. Pass a callsign (e.g. "
                "'IQ2LB') to query one destination's cost + route path. Also "
                "accepts linbpq-flexnet filters/sorts: '/COST', '/CALL', "
                "'/AGE', '< <neighbour>', '!', '?'."
            )
        ),
    ] = None,
) -> str:
    """Display or query FlexNet destinations — `D [query]` (linbpq-flexnet).

    With no query, returns the full destination table (call, SSID-range, cost,
    `!`=cached path). With a callsign, returns that destination's cost and the
    resolved route path (`D <call>`). Only on linbpq-flexnet builds.
    """
    cmd = "D"
    if query is not None and query.strip():
        cmd = f"D {commands.validate_token(query.strip(), field='query')}"
    return await _run_sys(_get_linbpq_node(node), cmd, idle_ms=1000, max_wait_s=20)


# ── (X)Net write / SYS tools — Tier 1: routing ────────────────────────────

_NODE_FIELD = Field(description="(X)Net node callsign as configured in nodes.yaml")
_KIND_FIELD = Field(description="Router table: 'bc' (NODES broadcasts), 'flexnet', or 'local'")


@mcp.tool()
async def xnet_router_list(
    node: Annotated[str, _NODE_FIELD],
    kind: Annotated[str, _KIND_FIELD],
) -> str:
    """Show a router table — `ROUTER <kind>` (bc | flexnet | local | param).

    Read-only. Use 'param' to see the router's broadcast/RTT parameters.
    """
    if kind not in (*commands.ROUTER_KINDS, "param"):
        raise ValueError(f"kind must be one of {(*commands.ROUTER_KINDS, 'param')}")
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, f"ROUTER {kind.upper()}")


@mcp.tool()
async def xnet_router_add(
    node: Annotated[str, _NODE_FIELD],
    kind: Annotated[str, _KIND_FIELD],
    port: Annotated[int, Field(description="(X)Net port number 0-255", ge=0, le=255)],
    call: Annotated[
        str | None, Field(description="Neighbour/destination callsign (not for 'bc')")
    ] = None,
    via: Annotated[str | None, Field(description="Optional via/digipeater callsign")] = None,
    dist: Annotated[
        str | None,
        Field(description="local only: distribution flag n|d|nd (optional 'p' suffix)"),
    ] = None,
    alias: Annotated[str | None, Field(description="local only: optional alias")] = None,
) -> str:
    """Add a routing entry (Tier 1, reversible).

    - bc:      `ROUTER BC ADD <port>` — enable NODES broadcasts on a port
    - flexnet: `ROUTER FLEXNET ADD <port> <call> [<via>]`
    - local:   `ROUTER LOCAL ADD <port> <call> [<via>] [<dist>] [<alias>]`
    """
    cmd = commands.build_router_add(
        kind, port=port, call=call, via=via, dist=dist, alias=alias
    )
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_router_del(
    node: Annotated[str, _NODE_FIELD],
    kind: Annotated[str, _KIND_FIELD],
    port: Annotated[int, Field(description="(X)Net port number 0-255", ge=0, le=255)],
    call: Annotated[
        str | None, Field(description="Callsign to remove (required except 'bc')")
    ] = None,
    confirm: Annotated[
        bool, Field(description="Operator-approval gate — see tool docs")
    ] = False,
) -> str:
    """Delete a routing entry. DANGEROUS — requires confirm=True.

    Removing a flexnet neighbour tears down a live FlexNet peering; on -14/-4
    that can disrupt the production mesh. Only set confirm=True after the
    operator has explicitly approved the exact command shown in the approval
    block.
    """
    cmd = commands.build_router_del(kind, port=port, call=call)
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Delete {kind} route on port {port}"
            + (f" to {call}" if call else ""),
            command=cmd,
            risk="Removes a routing entry; a flexnet delete tears down a live "
            "peering and can disrupt mesh routing.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_disconnect(
    node: Annotated[str, _NODE_FIELD],
    channel: Annotated[
        str, Field(description="L2/L4 channel id to drop, as shown by `L` / `U`")
    ],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Disconnect an L2/L4 channel — `DISC <channel>`. DANGEROUS — requires confirm=True.

    Drops a live link or user session. Only set confirm=True after operator
    approval.
    """
    chan = commands.validate_token(channel.strip(), field="channel")
    cmd = f"DISC {chan}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Disconnect channel {chan}",
            command=cmd,
            risk="Drops a live AX.25/NetROM link or user session.",
        )
    return await _run_sys(cfg, cmd)


# ── (X)Net write / SYS tools — Tier 2: IP & ARP ────────────────────────────


@mcp.tool()
async def xnet_iproute_list(node: Annotated[str, _NODE_FIELD]) -> str:
    """Show the IP routing table — `IPRoute` (read-only)."""
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, "IPRoute")


@mcp.tool()
async def xnet_iproute_add(
    node: Annotated[str, _NODE_FIELD],
    net: Annotated[str, Field(description="Destination network, e.g. 44.134.27.0/24")],
    iface: Annotated[str, Field(description="Egress interface, e.g. ETHER")],
    gw: Annotated[str, Field(description="Gateway IP, e.g. 44.134.24.1")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Add an IP route — `IPRoute ADD <net> <iface> <gw>`. DANGEROUS — requires confirm=True."""
    cmd = commands.build_iproute_add(net=net, iface=iface, gw=gw)
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Add IP route {net} via {gw} ({iface})",
            command=cmd,
            risk="Alters the node's IP routing — can blackhole AMPRNet traffic.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_iproute_del(
    node: Annotated[str, _NODE_FIELD],
    net: Annotated[str, Field(description="Destination network to remove, e.g. 44.134.27.0/24")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Delete an IP route — `IPRoute DEL <net>`. DANGEROUS — requires confirm=True."""
    cmd = commands.build_iproute_del(net=net)
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Delete IP route {net}",
            command=cmd,
            risk="Removes an IP route — can blackhole AMPRNet traffic.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_arp_list(node: Annotated[str, _NODE_FIELD]) -> str:
    """Show ARP entries — `ARp` (read-only)."""
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, "ARp")


@mcp.tool()
async def xnet_arp_add(
    node: Annotated[str, _NODE_FIELD],
    ip: Annotated[str, Field(description="IP address to map")],
    iface: Annotated[str, Field(description="Interface, e.g. ETHER")],
    hw: Annotated[str, Field(description="Hardware addr or callsign for the mapping")],
) -> str:
    """Add an ARP entry — `ARp ADD <ip> <iface> <hw>` (Tier 2, reversible)."""
    cmd = commands.build_arp_add(ip=ip, iface=iface, hw=hw)
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_arp_del(
    node: Annotated[str, _NODE_FIELD],
    ip: Annotated[str, Field(description="IP address whose ARP entry to remove")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Delete an ARP entry — `ARp DEL <ip>`. DANGEROUS — requires confirm=True."""
    cmd = commands.build_arp_del(ip=ip)
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Delete ARP entry for {ip}",
            command=cmd,
            risk="Removes an IP↔hardware mapping; affected hosts become unreachable.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_set_nameserver(
    node: Annotated[str, _NODE_FIELD],
    ip: Annotated[str, Field(description="DNS server IP address")],
) -> str:
    """Set the DNS resolver — `NAMESrv <ip>` (Tier 2, reversible)."""
    addr = commands.validate_token(ip.strip(), field="ip")
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, f"NAMESrv {addr}")


# ── (X)Net write / SYS tools — Tier 2: parameters & services ───────────────


@mcp.tool()
async def xnet_set_param(
    node: Annotated[str, _NODE_FIELD],
    name: Annotated[str, Field(description="Parameter name or index (see PAram listing)")],
    value: Annotated[str, Field(description="New value")],
) -> str:
    """Set a node parameter — `PAram <name> <value>` (Tier 2, runtime-only)."""
    pname = commands.validate_token(name.strip(), field="name")
    pval = commands.validate_token(value.strip(), field="value")
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, f"PAram {pname} {pval}")


@mcp.tool()
async def xnet_port_param(
    node: Annotated[str, _NODE_FIELD],
    port: Annotated[int, Field(description="Port number 0-255", ge=0, le=255)],
    name: Annotated[str, Field(description="Port parameter name")],
    value: Annotated[str, Field(description="New value")],
) -> str:
    """Set a port parameter — `Port <port> <name> <value>` (Tier 2, runtime-only)."""
    pname = commands.validate_token(name.strip(), field="name")
    pval = commands.validate_token(value.strip(), field="value")
    cfg = _get_xnet_writable(node)
    return await _run_sys(cfg, f"Port {port} {pname} {pval}")


@mcp.tool()
async def xnet_service(
    node: Annotated[str, _NODE_FIELD],
    action: Annotated[str, Field(description="'start' or 'stop'")],
    name: Annotated[str, Field(description="Daemon name, e.g. HTTPD, FTPD, CROND, ROUTED")],
    confirm: Annotated[
        bool, Field(description="Operator-approval gate (required for 'stop')")
    ] = False,
) -> str:
    """Start or stop a background daemon — `START`/`STOP <name>`.

    'start' is direct (Tier 2). 'stop' is DANGEROUS (takes a service offline) and
    requires confirm=True.
    """
    act = action.strip().lower()
    if act not in ("start", "stop"):
        raise ValueError("action must be 'start' or 'stop'")
    daemon = commands.validate_token(name.strip(), field="name")
    cmd = f"{act.upper()} {daemon}"
    cfg = _get_xnet_writable(node)
    if act == "stop" and not confirm:
        return safety.approval_required(
            node=node,
            action=f"Stop daemon {daemon}",
            command=cmd,
            risk="Takes a running service offline.",
        )
    return await _run_sys(cfg, cmd)


# ── (X)Net write / SYS tools — Tier 2: diagnostics (read) ──────────────────


@mcp.tool()
async def xnet_monitor(
    node: Annotated[str, _NODE_FIELD],
    ports: Annotated[
        str,
        Field(
            description=(
                "'*' (all ports), a single port ('8'), or several ports "
                "('7 8' or '7,8'). (X)Net selects only one port natively, so "
                "multiple ports are captured by monitoring all and filtering."
            )
        ),
    ] = "*",
    seconds: Annotated[
        int, Field(description="Capture window in seconds (1-60)", ge=1, le=60)
    ] = 10,
) -> str:
    """Capture AX.25 monitor output — `MOnitor` — for a fixed window.

    (X)Net V1.39's `MOnitor` selects exactly one port or `*` (all). A single
    requested port is selected on the node; multiple ports are captured by
    monitoring `*` and filtering the result to those ports here. Monitoring is
    left enabled on the session; it clears when the session closes (immediately
    after this call).
    """
    selection = commands.parse_monitor_selection(ports)
    cfg = _get_xnet_writable(node)
    text = await _capture_sys(cfg, f"MOnitor {selection.arg}", float(seconds))
    if selection.filter_ports is not None:
        text = commands.filter_monitor_text(text, selection.filter_ports)
    return text


@mcp.tool()
async def xnet_ipdump(
    node: Annotated[str, _NODE_FIELD],
    seconds: Annotated[
        int, Field(description="Capture window in seconds (1-60)", ge=1, le=60)
    ] = 10,
    args: Annotated[str, Field(description="Optional IPDump filter args")] = "",
) -> str:
    """Capture IP packet dump — `IPDump [args]` — for a fixed window."""
    tail = commands.validate_token(args.strip(), field="args")
    cmd = f"IPDump {tail}".strip()
    cfg = _get_xnet_writable(node)
    return await _capture_sys(cfg, cmd, float(seconds))


@mcp.tool()
async def xnet_netstat(node: Annotated[str, _NODE_FIELD]) -> str:
    """Show TCP network status — `NETStat` (read-only)."""
    return await _run_user(_get_xnet_writable(node), "NETStat")


@mcp.tool()
async def xnet_processes(node: Annotated[str, _NODE_FIELD]) -> str:
    """List running processes — `PS` (read-only)."""
    return await _run_user(_get_xnet_writable(node), "PS")


@mcp.tool()
async def xnet_statistics(node: Annotated[str, _NODE_FIELD]) -> str:
    """Show node statistics — `Stati` (read-only)."""
    return await _run_user(_get_xnet_writable(node), "Stati")


@mcp.tool()
async def xnet_log(node: Annotated[str, _NODE_FIELD]) -> str:
    """Print recent log messages — `LOG` (read-only, SYS)."""
    return await _run_sys(_get_xnet_writable(node), "LOG")


@mcp.tool()
async def xnet_ping(
    node: Annotated[str, _NODE_FIELD],
    target: Annotated[str, Field(description="IP or host to ping")],
) -> str:
    """Send an IP ping — `PING <target>` (read-only)."""
    tgt = commands.validate_token(target.strip(), field="target")
    return await _run_user(_get_xnet_writable(node), f"PING {tgt}", max_wait_s=20.0)


# ── (X)Net write / SYS tools — Tier 2: files ───────────────────────────────


@mcp.tool()
async def xnet_dir(
    node: Annotated[str, _NODE_FIELD],
    path: Annotated[str, Field(description="Optional directory/path")] = "",
) -> str:
    """List a directory — `DIr [path]` (read-only, SYS)."""
    p = commands.validate_token(path.strip(), field="path")
    return await _run_sys(_get_xnet_writable(node), f"DIr {p}".strip())


@mcp.tool()
async def xnet_read_file(
    node: Annotated[str, _NODE_FIELD],
    path: Annotated[str, Field(description="Text file to read")],
) -> str:
    """Read a text file — `READ <path>` (read-only, SYS)."""
    p = commands.validate_token(path.strip(), field="path")
    return await _run_sys(_get_xnet_writable(node), f"READ {p}", max_wait_s=20.0)


@mcp.tool()
async def xnet_copy_file(
    node: Annotated[str, _NODE_FIELD],
    src: Annotated[str, Field(description="Source path")],
    dst: Annotated[str, Field(description="Destination path")],
) -> str:
    """Copy a file — `CP <src> <dst>` (Tier 2; non-destructive copy)."""
    s = commands.validate_token(src.strip(), field="src")
    d = commands.validate_token(dst.strip(), field="dst")
    return await _run_sys(_get_xnet_writable(node), f"CP {s} {d}")


@mcp.tool()
async def xnet_rename_file(
    node: Annotated[str, _NODE_FIELD],
    src: Annotated[str, Field(description="Source path")],
    dst: Annotated[str, Field(description="Destination path")],
) -> str:
    """Rename/move a file — `REName <src> <dst>` (Tier 2)."""
    s = commands.validate_token(src.strip(), field="src")
    d = commands.validate_token(dst.strip(), field="dst")
    return await _run_sys(_get_xnet_writable(node), f"REName {s} {d}")


# ── (X)Net write / SYS tools — Tier 3: DANGEROUS (confirm required) ────────


@mcp.tool()
async def xnet_attach(
    node: Annotated[str, _NODE_FIELD],
    args: Annotated[
        str,
        Field(description="Full ATTACH argument tail, e.g. 'axudp xnet 256 44.134.24.4'"),
    ],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Attach a driver/port — `ATTACH <args>`. DANGEROUS — requires confirm=True.

    Driver/protocol/buffer syntax varies; the full tail is passed verbatim, so
    review the exact command in the approval block before approving.
    """
    tail = commands.validate_token(args.strip(), field="args")
    cmd = f"ATTACH {tail}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action="Attach a driver/port",
            command=cmd,
            risk="Brings up a port; a wrong spec can disrupt existing links.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_detach(
    node: Annotated[str, _NODE_FIELD],
    name: Annotated[str, Field(description="Driver/port name to detach")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Detach a driver/port — `DETACH <name>`. DANGEROUS — requires confirm=True.

    Drops every live link on that port.
    """
    drv = commands.validate_token(name.strip(), field="name")
    cmd = f"DETACH {drv}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Detach port {drv}",
            command=cmd,
            risk="Drops every live link on the port.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_set_identity(
    node: Annotated[str, _NODE_FIELD],
    call: Annotated[str | None, Field(description="New node callsign")] = None,
    alias: Annotated[str | None, Field(description="New node alias")] = None,
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Set node call/alias — `MY CALL <call>` / `MY ALIAS <alias>`. DANGEROUS — confirm=True.

    Changing the node identity affects how every peer routes to it. Provide
    exactly one of call/alias per invocation.
    """
    if (call is None) == (alias is None):
        raise ValueError("provide exactly one of 'call' or 'alias'")
    if call is not None:
        cmd = f"MY CALL {commands.validate_callsign(call)}"
        action = f"Set node callsign to {commands.validate_callsign(call)}"
    else:
        assert alias is not None
        cmd = f"MY ALIAS {commands.validate_token(alias.strip(), field='alias')}"
        action = f"Set node alias to {alias.strip()}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=action,
            command=cmd,
            risk="Changes node identity; every peer's routing to this node is affected.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_set_ip(
    node: Annotated[str, _NODE_FIELD],
    ip: Annotated[str, Field(description="New node IP address")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Set the node IP — `MYIP <ip>`. DANGEROUS — requires confirm=True."""
    addr = commands.validate_token(ip.strip(), field="ip")
    cmd = f"MYIP {addr}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Set node IP to {addr}",
            command=cmd,
            risk="Changes the node's IP; can sever AMPRNet/IP reachability.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_set_subnet(
    node: Annotated[str, _NODE_FIELD],
    subnet: Annotated[str, Field(description="Node subnet, e.g. 44.134.24.0/24")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Set the node subnet — `SUBNEt <subnet>`. DANGEROUS — requires confirm=True."""
    net = commands.validate_token(subnet.strip(), field="subnet")
    cmd = f"SUBNEt {net}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Set node subnet to {net}",
            command=cmd,
            risk="Changes the node's subnet; affects IP routing/reachability.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_set_time(
    node: Annotated[str, _NODE_FIELD],
    datetime_spec: Annotated[str, Field(description="Date/time as the node expects it")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Set the node clock — `TIME <spec>`. DANGEROUS — requires confirm=True."""
    spec = commands.validate_token(datetime_spec.strip(), field="datetime_spec")
    cmd = f"TIME {spec}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Set node clock to {spec}",
            command=cmd,
            risk="Changes the system clock; affects beacons, logs and schedulers.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_remove_file(
    node: Annotated[str, _NODE_FIELD],
    path: Annotated[str, Field(description="File to delete")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Delete a file — `RM <path>`. DANGEROUS — requires confirm=True."""
    p = commands.validate_token(path.strip(), field="path")
    cmd = f"RM {p}"
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Delete file {p}",
            command=cmd,
            risk="Permanently removes a file from the node's filesystem.",
        )
    return await _run_sys(cfg, cmd)


@mcp.tool()
async def xnet_ipstop(
    node: Annotated[str, _NODE_FIELD],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Stop the IP router — `IPStop`. DANGEROUS — requires confirm=True."""
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action="Stop the IP router",
            command="IPStop",
            risk="Halts IP routing on the node.",
        )
    return await _run_sys(cfg, "IPStop")


@mcp.tool()
async def xnet_reset(
    node: Annotated[str, _NODE_FIELD],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Reboot the node — `RESET`. DANGEROUS — requires confirm=True.

    Takes the entire node offline and restarts it. Highest blast radius.
    """
    cfg = _get_xnet_writable(node)
    if not confirm:
        return safety.approval_required(
            node=node,
            action="REBOOT the node",
            command="RESET",
            risk="Restarts the whole node — all links drop until it comes back.",
        )
    # The node reboots; it won't return a clean prompt, so keep the wait short.
    return await _run_sys(cfg, "RESET", max_wait_s=5.0)


# ── (X)Net escape hatch — verbatim command after SYS, danger-classified ────


@mcp.tool()
async def xnet_sys_command(
    node: Annotated[
        str,
        Field(description="(X)Net node from nodes.yaml (chained escape-hatch only)"),
    ],
    command: Annotated[str, Field(description="Literal command to run AFTER SYS elevation")],
    confirm: Annotated[
        bool, Field(description="Required when the command is classified DANGEROUS")
    ] = False,
    idle_ms: Annotated[
        int, Field(description="Idle-ms before response is complete", ge=100, le=5000)
    ] = 600,
) -> str:
    """Run a verbatim command after SYS elevation (covers the full surface).

    The command is classified by safety.is_dangerous_command(). DANGEROUS
    commands (ATTACH/DETACH/RESET/RM/LOAD/MY*/TIME/STOP/… and anything with a
    DEL/KILL/FLUSH token) refuse to run unless confirm=True. The LLM must only
    set confirm=True after the operator has explicitly approved.

    This is the only tool that also targets the chained PC/Flexnet node
    a chained PC/Flexnet node, whose command set differs from (X)Net V1.39.
    """
    cfg = _get_node(node, _XNET_COMPATIBLE_TYPES)
    cmd = command.strip()
    if safety.is_dangerous_command(cmd) and not confirm:
        return safety.approval_required(
            node=node,
            action="Run a privileged command classified as dangerous",
            command=cmd,
            risk="Verbatim SYS command flagged as state-changing/destructive.",
        )
    async with open_transport(cfg, _NODES) as xn:
        await xn.elevate_sys()
        return await xn.run_command(cmd, idle_ms=idle_ms)


# ── BPQ32 / LinBPQ — Section A: diagnostics / reads ───────────────────────
#
# Note: LINKS / USERS / MHEARD / INFO are already exposed via the generic
# xnet_links / xnet_users / xnet_mh / xnet_info tools (the single-letter forms
# work on BPQ too), and PORTS / ROUTES / NODES have dedicated wrappers above.
# The tools below cover the rest of the BPQ surface. All elevate via PASSWORD
# to keep behaviour uniform with the existing bpq_* wrappers.

_BPQ_NODE = Field(description="BPQ/LinBPQ node callsign as configured in nodes.yaml")
_BPQ_PORT = Field(description="BPQ port number 0-255", ge=0, le=255)
_BPQ_OPT_PORT = Field(description="Port number for port params", ge=0, le=255)


@mcp.tool()
async def bpq_version(node: Annotated[str, _BPQ_NODE]) -> str:
    """Show node software version — `VERSION`."""
    return await _run_sys(_get_bpq_node(node), "VERSION")


@mcp.tool()
async def bpq_stats(
    node: Annotated[str, _BPQ_NODE],
    scope: Annotated[str, Field(description="'', 'P' (port) or 'S' (system)")] = "",
    port: Annotated[str, Field(description="Optional port for scope='P'")] = "",
) -> str:
    """Show system / port counters — `STATS [P|S] [port]`."""
    s = scope.strip().upper()
    if s not in ("", "P", "S"):
        raise ValueError("scope must be '', 'P' or 'S'")
    parts = ["STATS"]
    if s:
        parts.append(s)
    if port.strip():
        parts.append(commands.validate_token(port.strip(), field="port"))
    return await _run_sys(_get_bpq_node(node), " ".join(parts), idle_ms=800)


@mcp.tool()
async def bpq_listen(
    node: Annotated[str, _BPQ_NODE],
    ports: Annotated[str, Field(description="Port(s) to listen on, e.g. '2'")],
    seconds: Annotated[int, Field(description="Capture window (1-60)", ge=1, le=60)] = 10,
) -> str:
    """Capture monitor output — `LISTEN <ports>` — for a fixed window.

    Listen mode is left on; it clears when the session closes after this call.
    """
    spec = commands.validate_token(ports.strip(), field="ports")
    return await _capture_sys(_get_bpq_node(node), f"LISTEN {spec}", float(seconds))


@mcp.tool()
async def bpq_validcall(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[str, Field(description="Optional port")] = "",
) -> str:
    """Display valid callsigns — `VALIDCALL [port]` (read-only)."""
    cmd = f"VALIDCALL {commands.validate_token(port.strip(), field='port')}".strip()
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_iproute(
    node: Annotated[str, _BPQ_NODE],
    filter: Annotated[str, Field(description="Optional filter")] = "",  # noqa: A002
) -> str:
    """Display the IP routing table — `IPROUTE [filter]` (IP-gateway builds)."""
    cmd = f"IPROUTE {commands.validate_token(filter.strip(), field='filter')}".strip()
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_arp(node: Annotated[str, _BPQ_NODE]) -> str:
    """Display the IP ARP table — `ARP` (IP-gateway builds)."""
    return await _run_sys(_get_bpq_node(node), "ARP")


@mcp.tool()
async def bpq_nat(node: Annotated[str, _BPQ_NODE]) -> str:
    """Display the IP NAT table — `NAT` (IP-gateway builds)."""
    return await _run_sys(_get_bpq_node(node), "NAT")


@mcp.tool()
async def bpq_ping(
    node: Annotated[str, _BPQ_NODE],
    target: Annotated[str, Field(description="IP address to ping")],
) -> str:
    """Send an ICMP echo — `PING <ip>` (IP-gateway builds)."""
    tgt = commands.validate_token(target.strip(), field="target")
    return await _run_sys(_get_bpq_node(node), f"PING {tgt}", max_wait_s=20.0)


@mcp.tool()
async def bpq_telstatus(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[str, Field(description="Optional Telnet port")] = "",
) -> str:
    """Display Telnet server connection status — `TELSTATUS [port]`."""
    cmd = f"TELSTATUS {commands.validate_token(port.strip(), field='port')}".strip()
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_axresolver(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
) -> str:
    """Display the AXIP resolver table for a port — `AXRESOLVER <port>`."""
    return await _run_sys(_get_bpq_node(node), f"AXRESOLVER {port}")


@mcp.tool()
async def bpq_axmheard(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
) -> str:
    """Display the AXIP heard list for a port — `AXMHEARD <port>`."""
    return await _run_sys(_get_bpq_node(node), f"AXMHEARD {port}")


# ── BPQ32 / LinBPQ — Section B: routing writes ─────────────────────────────


@mcp.tool()
async def bpq_node_add(
    node: Annotated[str, _BPQ_NODE],
    alias: Annotated[str, Field(description="NetROM alias (1-6 alphanumerics)")],
    call: Annotated[str, Field(description="Node callsign")],
    quality: Annotated[int, Field(description="Route quality 0-255", ge=0, le=255)],
    neighbour: Annotated[str, Field(description="Neighbour callsign to reach it")],
) -> str:
    """Add a NetROM node — `NODE ADD <alias>:<call> <qual> <neighbour>` (additive, direct)."""
    cmd = commands.build_bpq_node_add(
        alias=alias, call=call, qual=quality, neighbour=neighbour
    )
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_node_del(
    node: Annotated[str, _BPQ_NODE],
    call: Annotated[str, Field(description="Node callsign to remove")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Delete a NetROM node — `NODE DEL <call>`. DANGEROUS — requires confirm=True."""
    cmd = commands.build_bpq_node_del(call=call)
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Delete NetROM node {call}",
            command=cmd,
            risk="Removes a routing-table entry; destinations via it become unreachable.",
        )
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_route_set(
    node: Annotated[str, _BPQ_NODE],
    call: Annotated[str, Field(description="Neighbour callsign")],
    port: Annotated[int, _BPQ_PORT],
    quality: Annotated[int, Field(description="Route quality 0-255", ge=0, le=255)],
    lock: Annotated[bool, Field(description="Lock the route (append '!')")] = False,
) -> str:
    """Set neighbour route quality / lock — `ROUTES <call> <port> <qual> [!]` (direct tune)."""
    cmd = commands.build_bpq_route_set(call=call, port=port, qual=quality, lock=lock)
    return await _run_sys(_get_bpq_node(node), cmd)


# ── BPQ32 / LinBPQ — Section C: port & CMS control ─────────────────────────


@mcp.tool()
async def bpq_startport(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
) -> str:
    """Reopen a closed port — `STARTPORT <port>` (restorative, direct)."""
    return await _run_sys(_get_bpq_node(node), f"STARTPORT {port}")


@mcp.tool()
async def bpq_stopport(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Close a port — `STOPPORT <port>`. DANGEROUS — requires confirm=True."""
    cmd = f"STOPPORT {port}"
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Stop port {port}",
            command=cmd,
            risk="Closes the port; all links on it drop.",
        )
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_startcms(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
) -> str:
    """Enable CMS (Winlink) on a Telnet port — `STARTCMS <port>` (restorative, direct)."""
    return await _run_sys(_get_bpq_node(node), f"STARTCMS {port}")


@mcp.tool()
async def bpq_stopcms(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Disable CMS (Winlink) on a Telnet port — `STOPCMS <port>`. DANGEROUS — confirm=True."""
    cmd = f"STOPCMS {port}"
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Stop CMS on port {port}",
            command=cmd,
            risk="Disables Winlink CMS access on the port.",
        )
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_kiss(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
    command: Annotated[str, Field(description="KISS command token")],
    value: Annotated[str, Field(description="Optional value")] = "",
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Send KISS parameters to a TNC — `KISS <port> <cmd> [value]`. DANGEROUS — confirm=True."""
    kcmd = commands.validate_token(command.strip(), field="command")
    val = commands.validate_token(value.strip(), field="value")
    cmd = f"KISS {port} {kcmd} {val}".strip()
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Send KISS '{kcmd}' to port {port}",
            command=cmd,
            risk="Reconfigures the TNC; a wrong value can take the radio link down.",
        )
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_telreconfig(
    node: Annotated[str, _BPQ_NODE],
    port: Annotated[int, _BPQ_PORT],
    mode: Annotated[str, Field(description="'ALL' or 'USERS'")],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Reconfigure a Telnet port — `TELReconfig <port> ALL|USERS`. DANGEROUS — confirm=True."""
    m = mode.strip().upper()
    if m not in ("ALL", "USERS"):
        raise ValueError("mode must be 'ALL' or 'USERS'")
    cmd = f"TELReconfig {port} {m}"
    if not confirm:
        return safety.approval_required(
            node=node,
            action=f"Reconfigure Telnet port {port} ({m})",
            command=cmd,
            risk="Reloads Telnet port config; active sessions may be disrupted.",
        )
    return await _run_sys(_get_bpq_node(node), cmd)


# ── BPQ32 / LinBPQ — Section D: persistence ────────────────────────────────


@mcp.tool()
async def bpq_savemh(node: Annotated[str, _BPQ_NODE]) -> str:
    """Persist the heard list — `SAVEMH` (direct)."""
    return await _run_sys(_get_bpq_node(node), "SAVEMH")


@mcp.tool()
async def bpq_savenodes(node: Annotated[str, _BPQ_NODE]) -> str:
    """Persist the nodes table — `SAVENODES` (direct)."""
    return await _run_sys(_get_bpq_node(node), "SAVENODES")


@mcp.tool()
async def bpq_sendnodes(node: Annotated[str, _BPQ_NODE]) -> str:
    """Broadcast the nodes table now — `SENDNODES` (direct)."""
    return await _run_sys(_get_bpq_node(node), "SENDNODES")


@mcp.tool()
async def bpq_getportctext(node: Annotated[str, _BPQ_NODE]) -> str:
    """Re-read port CTEXT files — `GETPORTCTEXT` (direct)."""
    return await _run_sys(_get_bpq_node(node), "GETPORTCTEXT")


# ── BPQ32 / LinBPQ — Section E: parameters (get / set) ─────────────────────


@mcp.tool()
async def bpq_get_param(
    node: Annotated[str, _BPQ_NODE],
    name: Annotated[str, Field(description="Parameter name (port or system; see docs)")],
    port: Annotated[int | None, _BPQ_OPT_PORT] = None,
) -> str:
    """Read a BPQ port/system parameter — `<NAME> [port]` (read-only).

    Valid names: port params (TXDELAY, MAXFRAME, FRACK, RESPTIME, PPACLEN,
    RETRIES, QUALITY, PERSIST, TXTAIL, XMITOFF, DIGIFLAG, DIGIPORT, MAXUSERS,
    VALIDCALL, L3ONLY, BBSALIAS, FULLDUP, SOFTDCD) and system params (REMDUMP,
    OBSINIT, OBSMIN, NODESINT, L3TTL, L4RETRIES, L4TIMEOUT, T3, NODEIDLETIME,
    LINKEDFLAG, IDINTERVAL, MINQUAL, FULLCTEXT, HIDENODES, L4DELAY, L4WINDOW,
    BTINTERVAL).
    """
    cmd = commands.build_bpq_param(name, port=port)
    return await _run_sys(_get_bpq_node(node), cmd)


@mcp.tool()
async def bpq_set_param(
    node: Annotated[str, _BPQ_NODE],
    name: Annotated[str, Field(description="Parameter name (allowlisted; see bpq_get_param)")],
    value: Annotated[str, Field(description="New value")],
    port: Annotated[int | None, _BPQ_OPT_PORT] = None,
) -> str:
    """Set a BPQ port/system parameter — `<NAME> [port] <value>` (runtime-only).

    The name is allowlisted (see bpq_get_param) so it can't smuggle an
    arbitrary console command. Changes are runtime-only — lost on restart
    unless persisted in bpq32.cfg.
    """
    cmd = commands.build_bpq_param(name, value=value, port=port)
    return await _run_sys(_get_bpq_node(node), cmd)


# ── BPQ32 / LinBPQ — Section F: system / lifecycle ─────────────────────────


@mcp.tool()
async def bpq_findbuffs(node: Annotated[str, _BPQ_NODE]) -> str:
    """Diagnostic: locate leaked buffer allocations — `FINDBUFFS` (read-only)."""
    return await _run_sys(_get_bpq_node(node), "FINDBUFFS", idle_ms=800)


@mcp.tool()
async def bpq_wl2ksysop(
    node: Annotated[str, _BPQ_NODE],
    create: Annotated[
        bool, Field(description="Create/update the record (WL2KSYSOP SET)")
    ] = False,
    confirm: Annotated[
        bool, Field(description="Operator-approval gate (required when create=True)")
    ] = False,
) -> str:
    """Show or create the Winlink 2000 sysop record — `WL2KSYSOP [SET]`.

    Reading is direct; create=True (`WL2KSYSOP SET`) is DANGEROUS and requires
    confirm=True.
    """
    if not create:
        return await _run_sys(_get_bpq_node(node), "WL2KSYSOP")
    if not confirm:
        return safety.approval_required(
            node=node,
            action="Create/update the Winlink 2000 sysop record",
            command="WL2KSYSOP SET",
            risk="Registers this node's sysop record with the Winlink CMS.",
        )
    return await _run_sys(_get_bpq_node(node), "WL2KSYSOP SET")


@mcp.tool()
async def bpq_reconfig(
    node: Annotated[str, _BPQ_NODE],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Reinitialize config from file — `RECONFIG`. DANGEROUS — requires confirm=True."""
    if not confirm:
        return safety.approval_required(
            node=node,
            action="Reinitialize node configuration from file",
            command="RECONFIG",
            risk="Reloads bpq32.cfg; links and ports may bounce.",
        )
    return await _run_sys(_get_bpq_node(node), "RECONFIG")


@mcp.tool()
async def bpq_reboot(
    node: Annotated[str, _BPQ_NODE],
    confirm: Annotated[bool, Field(description="Operator-approval gate")] = False,
) -> str:
    """Restart the node — `REBOOT`. DANGEROUS — requires confirm=True.

    Highest blast radius: the whole node restarts and all links drop.
    """
    if not confirm:
        return safety.approval_required(
            node=node,
            action="REBOOT the node",
            command="REBOOT",
            risk="Restarts the whole node — all links drop until it comes back.",
        )
    return await _run_sys(_get_bpq_node(node), "REBOOT", max_wait_s=5.0)


# ── CLI entry point ───────────────────────────────────────────────────────


def _init_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _test_run(node: str, command: str, sys: bool, idle_ms: int) -> int:
    """Smoke-test entry point: connect, run a single command, print, exit."""
    cfg = _get_xnet_node(node)
    async with open_transport(cfg, _NODES) as xn:
        if sys:
            await xn.elevate_sys()
        out = await xn.run_command(command, idle_ms=idle_ms)
    print(out)
    return 0


# ── Aggregation across all configured nodes ──────────────────────────────────


async def _collect_topology() -> dict[str, Any]:
    """Query every node's neighbour/link table and return a per-node map."""

    async def _one(name: str, cfg: NodeConfig) -> tuple[str, dict[str, Any]]:
        try:
            if cfg.type in _XNET_COMPATIBLE_TYPES:
                raw = await _run_user(cfg, "L")
                neighbours = parsers.to_dicts(parsers.parse_xnet_links(raw))
            else:
                raw = await _run_sys(cfg, "ROUTES")
                neighbours = parsers.to_dicts(parsers.parse_bpq_routes(raw))
            return name, {"type": cfg.type, "neighbours": neighbours}
        except Exception as e:  # noqa: BLE001 - one node failing must not abort the sweep
            return name, {"type": cfg.type, "error": str(e)}

    results: list[tuple[str, dict[str, Any]]] = await asyncio.gather(
        *(_one(n, c) for n, c in _NODES.items())
    )
    return {"nodes": dict(results)}


async def _search_callsign(target: str) -> dict[str, Any]:
    """Search every node's nodes/routes/links for `target` (upper-cased)."""

    async def _one(name: str, cfg: NodeConfig) -> tuple[str, dict[str, Any]]:
        try:
            hits: list[dict[str, Any]] = []
            if cfg.type in _XNET_COMPATIBLE_TYPES:
                for ln in parsers.parse_xnet_links(await _run_user(cfg, "L")):
                    if target in ln.callsign.upper():
                        hits.append(
                            {"where": "link", "callsign": ln.callsign,
                             "dest_type": ln.dest_type}
                        )
            else:
                for nd in parsers.parse_bpq_nodes(await _run_sys(cfg, "NODES")):
                    if target in nd.callsign.upper() or target in nd.alias.upper():
                        hits.append(
                            {"where": "nodes", "alias": nd.alias, "callsign": nd.callsign}
                        )
                for rt in parsers.parse_bpq_routes(await _run_sys(cfg, "ROUTES")):
                    if target in rt.callsign.upper():
                        hits.append(
                            {"where": "route", "callsign": rt.callsign,
                             "port": rt.port, "quality": rt.quality}
                        )
            return name, {"type": cfg.type, "matches": hits}
        except Exception as e:  # noqa: BLE001 - one node failing must not abort the sweep
            return name, {"type": cfg.type, "error": str(e)}

    results: list[tuple[str, dict[str, Any]]] = await asyncio.gather(
        *(_one(n, c) for n, c in _NODES.items())
    )
    detail = dict(results)
    found_on = [n for n, r in detail.items() if r.get("matches")]
    return {"callsign": target, "found_on": found_on, "detail": detail}


@mcp.tool()
async def network_topology() -> dict[str, Any]:
    """Aggregate the neighbour/link table of EVERY configured node.

    Runs the fitting command per node type ((X)Net: ``L``; BPQ/LinBPQ:
    ``ROUTES``), parses it into structured neighbours, and returns a per-node
    map. Per-node failures are captured inline (never fatal). Note: this opens a
    session to every configured node, so it can be slow; BPQ ``ROUTES`` elevates
    to SYS.
    """
    return await _collect_topology()


@mcp.tool()
async def find_callsign(
    callsign: Annotated[
        str, Field(description="Callsign (or substring) to search for across all nodes")
    ],
) -> dict[str, Any]:
    """Search every configured node for a callsign in its nodes/routes/links.

    Reports which nodes reference the callsign and how (BPQ NODES alias table,
    routes, or (X)Net link table), so you can see where it is reachable. Opens a
    session to every node; BPQ queries elevate to SYS.
    """
    return await _search_callsign(callsign.strip().upper())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pr-digi-mcp",
        description="MCP server (or smoke-test client) for packet-radio digi nodes",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level logging")
    sub = parser.add_subparsers(dest="cmd")

    p_test = sub.add_parser(
        "test", help="Run a single command against a node (smoke test; doesn't start MCP)"
    )
    p_test.add_argument("node", help="Node callsign as configured in nodes.yaml")
    p_test.add_argument("command", help="Command to send, e.g. 'L *'")
    p_test.add_argument("--sys", action="store_true", help="Elevate to SYS first")
    p_test.add_argument(
        "--idle-ms", type=int, default=400, help="Idle-ms before considering response complete"
    )

    sub.add_parser("serve", help="Run the MCP stdio server (default if no subcommand)")

    args = parser.parse_args()
    _init_logging(args.verbose)

    global _NODES
    _NODES = load_nodes()

    if args.cmd == "test":
        rc = asyncio.run(
            _test_run(args.node, args.command, args.sys, args.idle_ms)
        )
        sys.exit(rc)

    # Default: serve over stdio
    mcp.run()


if __name__ == "__main__":
    main()
