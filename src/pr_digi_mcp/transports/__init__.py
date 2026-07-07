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
