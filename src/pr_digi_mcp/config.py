"""Node configuration loader.

Reads the per-node YAML config (endpoints, ssh paths, user names, sys
requirement flag). Passwords are NEVER stored here — see credentials.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

NodeType = Literal["xnet", "xnet_chained", "bpq", "linbpq", "pcf"]


@dataclass(frozen=True, slots=True)
class NodeConfig:
    """Static configuration for a single digi node.

    For direct-access nodes (`type='xnet'`, `'bpq'`, `'linbpq'`):
        `telnet_host` + `telnet_port` + `user` are required. `ssh_host` is
        OPTIONAL: set it to reach the node through an SSH jump host (the
        telnet TCP channel is tunnelled over SSH); leave it empty/omitted to
        connect directly to `telnet_host:telnet_port` (same LAN, or a node
        directly reachable over HAMNET/AMPRNet/Internet).

    For chained-access nodes (`type='xnet_chained'`) — e.g. IW2OHX-12
    reachable only via an AX.25 `C` from IW2OHX-14:
        `transit_via` + `connect_command` are required.
        The outer node's `ssh_host`/`telnet_host`/`user` are inherited
        at connect time, so the chained node's same-named fields are
        ignored (and may be left empty in the YAML).
    """

    callsign: str
    type: NodeType
    sys_required: bool
    description: str = ""
    # Direct-access fields (xnet, bpq, linbpq)
    ssh_host: str = ""
    telnet_host: str = ""
    telnet_port: int = 0
    user: str = ""
    # Chained-access fields (xnet_chained)
    transit_via: str = ""
    connect_command: str = ""


def _config_search_paths() -> list[Path]:
    """Where to look for nodes.yaml, in priority order."""
    return [
        Path.home() / ".config" / "pr-digi-mcp" / "nodes.yaml",
        Path.cwd() / "config" / "nodes.yaml",
        Path(__file__).resolve().parent.parent.parent / "config" / "nodes.yaml",
    ]


def load_nodes(path: Path | None = None) -> dict[str, NodeConfig]:
    """Load the node configuration file and return a callsign-keyed map.

    If `path` is None, search the standard locations in order.

    Raises:
        FileNotFoundError: if no config file is found
        ValueError: if the YAML is malformed or a required field is missing
    """
    if path is None:
        for candidate in _config_search_paths():
            if candidate.is_file():
                path = candidate
                break
        else:
            searched = "\n  ".join(str(p) for p in _config_search_paths())
            raise FileNotFoundError(
                f"No nodes.yaml found. Searched:\n  {searched}\n"
                f"Copy config/nodes.example.yaml to one of these paths and adjust."
            )

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "nodes" not in raw:
        raise ValueError(f"{path}: expected top-level 'nodes:' mapping")

    out: dict[str, NodeConfig] = {}
    for callsign, fields in raw["nodes"].items():
        if not isinstance(fields, dict):
            raise ValueError(f"{path}: node {callsign!r} must be a mapping")
        node_type = fields.get("type")
        if not node_type:
            raise ValueError(f"{path}: node {callsign!r} missing field 'type'")
        try:
            if node_type == "xnet_chained":
                # Chained nodes don't need direct-connect fields; require chain fields.
                for required in ("transit_via", "connect_command"):
                    if required not in fields:
                        raise ValueError(
                            f"{path}: chained node {callsign!r} missing field "
                            f"{required!r}"
                        )
                out[callsign] = NodeConfig(
                    callsign=callsign,
                    type=node_type,
                    sys_required=bool(fields.get("sys_required", False)),
                    description=str(fields.get("description", "")),
                    transit_via=str(fields["transit_via"]),
                    connect_command=str(fields["connect_command"]),
                )
            else:
                # Direct-access nodes need the SSH+telnet quartet.
                out[callsign] = NodeConfig(
                    callsign=callsign,
                    type=node_type,
                    ssh_host=str(fields.get("ssh_host", "")),
                    telnet_host=fields["telnet_host"],
                    telnet_port=int(fields["telnet_port"]),
                    user=fields["user"],
                    sys_required=bool(fields.get("sys_required", False)),
                    description=str(fields.get("description", "")),
                )
        except KeyError as e:
            raise ValueError(f"{path}: node {callsign!r} missing field {e}") from None

    # Validate transit_via references for chained nodes.
    for cfg in out.values():
        if cfg.type == "xnet_chained":
            if cfg.transit_via not in out:
                raise ValueError(
                    f"{path}: chained node {cfg.callsign!r} references unknown "
                    f"outer node {cfg.transit_via!r}"
                )
            if out[cfg.transit_via].type == "xnet_chained":
                raise ValueError(
                    f"{path}: chained node {cfg.callsign!r}'s transit_via "
                    f"{cfg.transit_via!r} is itself chained — multi-hop chains "
                    f"not supported in v0.x"
                )

    return out
