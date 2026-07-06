"""Transport layer — SSH tunnels, telnet clients, chained AX.25 sessions."""

from __future__ import annotations

from ..config import NodeConfig
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
    `all_nodes` mapping is consulted to resolve `transit_via`.

    Raises:
        ValueError: for unsupported node types or missing outer config.
    """
    if cfg.type == "xnet":
        return XnetTransport(cfg)
    if cfg.type in ("bpq", "linbpq"):
        return BpqTransport(cfg)
    if cfg.type == "xnet_chained":
        outer = all_nodes.get(cfg.transit_via)
        if outer is None:
            raise ValueError(
                f"chained node {cfg.callsign!r} references unknown outer "
                f"{cfg.transit_via!r}"
            )
        return Ax25ChainedTransport(cfg, outer)
    raise ValueError(
        f"node {cfg.callsign!r} has type {cfg.type!r}; supported: "
        f"xnet, xnet_chained, bpq, linbpq"
    )
