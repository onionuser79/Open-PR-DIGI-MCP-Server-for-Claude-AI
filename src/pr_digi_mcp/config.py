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
        `telnet_host` + `telnet_port` are required. `ssh_host` is OPTIONAL:
        set it to reach the node through an SSH jump host (the telnet TCP
        channel is tunnelled over SSH); leave it empty/omitted to connect
        directly to `telnet_host:telnet_port` (same LAN, or a node reachable
        over HAMNET/AMPRNet/Internet).

        `login_required` (default true) controls the telnet login step:
          - true  -> `user` is required; the transport sends it + the user
                     password at the login/password prompts.
          - false -> the node exposes its prompt without a login (some open
                     nodes); `user` may be omitted and no user password is used.

    For chained-access nodes (`type='xnet_chained'`) reachable only via an
    AX.25 `C` from a transit node:
        `transit_via` + `connect_command` are required. `transit_via` may point
        at a direct node (single hop) OR at another chained node (multi-hop):
        the chain is resolved to a base direct node plus the ordered list of
        `C …` commands. Direct-connect fields are inherited from the base node.
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
    login_required: bool = True
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


def resolve_chain(
    cfg: NodeConfig, all_nodes: dict[str, NodeConfig]
) -> tuple[NodeConfig, list[str]]:
    """Resolve a (possibly multi-hop) chained node to its base + connect path.

    Walks `transit_via` from the target inward until a direct (non-chained)
    node is reached. Returns `(base_direct_config, connect_commands)` where
    `connect_commands` is the ordered list of `C …` commands to issue **from
    the base node** to reach the target (base → … → target).

    Raises:
        ValueError: on an unknown `transit_via`, a cycle, or a chain that does
            not terminate at a direct node.
    """
    if cfg.type != "xnet_chained":
        raise ValueError(f"{cfg.callsign!r} is not a chained node")
    commands: list[str] = []
    seen: set[str] = set()
    cur = cfg
    while cur.type == "xnet_chained":
        if cur.callsign in seen:
            raise ValueError(
                f"chained node {cfg.callsign!r}: cycle detected at {cur.callsign!r}"
            )
        seen.add(cur.callsign)
        commands.append(cur.connect_command)
        nxt = all_nodes.get(cur.transit_via)
        if nxt is None:
            raise ValueError(
                f"chained node {cur.callsign!r} references unknown "
                f"transit node {cur.transit_via!r}"
            )
        cur = nxt
    commands.reverse()  # now ordered base -> ... -> target
    return cur, commands


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
                # Direct-access nodes need telnet_host/port; ssh_host optional;
                # user required only when login_required (default true).
                login_required = bool(fields.get("login_required", True))
                user = str(fields.get("user", ""))
                if login_required and not user:
                    raise ValueError(
                        f"{path}: node {callsign!r} needs 'user' "
                        f"(or set login_required: false)"
                    )
                out[callsign] = NodeConfig(
                    callsign=callsign,
                    type=node_type,
                    ssh_host=str(fields.get("ssh_host", "")),
                    telnet_host=fields["telnet_host"],
                    telnet_port=int(fields["telnet_port"]),
                    user=user,
                    login_required=login_required,
                    sys_required=bool(fields.get("sys_required", False)),
                    description=str(fields.get("description", "")),
                )
        except KeyError as e:
            raise ValueError(f"{path}: node {callsign!r} missing field {e}") from None

    # Validate every chained node resolves to a direct base (catches unknown
    # transit_via, cycles, and chains that never reach a direct node).
    for cfg in out.values():
        if cfg.type == "xnet_chained":
            resolve_chain(cfg, out)

    return out
