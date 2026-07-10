"""Transport layer — SSH tunnels, telnet clients, chained AX.25 sessions."""

from __future__ import annotations

from ..config import NodeConfig, resolve_chain
from .bpq import BpqTransport
from .chained import Ax25ChainedTransport
from .xnet import XnetError, XnetTransport

__all__ = [
    "Ax25ChainedTransport",
    "BpqTransport",
    "XnetError",
    "XnetTransport",
    "open_dynamic_chain",
    "open_transport",
]


def open_transport(
    cfg: NodeConfig, all_nodes: dict[str, NodeConfig]
) -> XnetTransport:
    """Factory: return the right transport class for the node type.

    Returns an `XnetTransport` (or subclass) — callers use it as an async
    context manager and ignore the concrete class. For chained nodes the
    `all_nodes` mapping is consulted to resolve the (single- or multi-hop)
    connect path to a base direct node.

    Raises:
        ValueError: for unsupported node types or an unresolvable chain.
    """
    if cfg.type == "xnet":
        return XnetTransport(cfg)
    if cfg.type in ("bpq", "linbpq"):
        return BpqTransport(cfg)
    if cfg.type == "xnet_chained":
        base, connect_commands = resolve_chain(cfg, all_nodes)
        return Ax25ChainedTransport(cfg, base, connect_commands)
    raise ValueError(
        f"node {cfg.callsign!r} has type {cfg.type!r}; supported: "
        f"xnet, xnet_chained, bpq, linbpq"
    )


def open_dynamic_chain(
    base_cfg: NodeConfig,
    connect_commands: list[str],
    target_callsign: str,
    *,
    sys_command: str = "SYS",
) -> Ax25ChainedTransport:
    """Build a chained transport for a route discovered at runtime.

    Unlike `open_transport`, the target is NOT in `nodes.yaml`: discovery has
    produced a `base_cfg` (a configured direct node with a console) and the
    ordered `C …` commands to reach `target_callsign` from it. We synthesise an
    ephemeral `xnet_chained` NodeConfig for the target and reuse the standard
    `Ax25ChainedTransport` connect/teardown machinery — nothing is persisted.
    """
    target_cfg = NodeConfig(
        callsign=target_callsign,
        type="xnet_chained",
        sys_required=False,
        description=f"ephemeral discovered route via {base_cfg.callsign}",
        sys_command=sys_command,
        transit_via=base_cfg.callsign,
        connect_command=connect_commands[-1] if connect_commands else "",
    )
    return Ax25ChainedTransport(target_cfg, base_cfg, connect_commands)
