"""Unit tests for the config loader. No network."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pr_digi_mcp.config import NodeConfig, load_nodes, resolve_chain


def _write(path: Path, content: str) -> None:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def test_load_nodes_basic(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          IW2OHX-14:
            type: xnet
            ssh_host: iw2ohx-gw
            telnet_host: 44.134.24.2
            telnet_port: 23
            user: iw7eas-1
            sys_required: true
            description: "primary xnet"
          IW2OHX-4:
            type: xnet
            ssh_host: iw2ohx-gw
            telnet_host: 44.134.24.3
            telnet_port: 23
            user: iw7eas-2
            sys_required: true
        """,
    )
    nodes = load_nodes(path)
    assert set(nodes) == {"IW2OHX-14", "IW2OHX-4"}
    assert nodes["IW2OHX-14"] == NodeConfig(
        callsign="IW2OHX-14",
        type="xnet",
        ssh_host="iw2ohx-gw",
        telnet_host="44.134.24.2",
        telnet_port=23,
        user="iw7eas-1",
        sys_required=True,
        description="primary xnet",
    )
    assert nodes["IW2OHX-4"].sys_required is True
    assert nodes["IW2OHX-4"].description == ""  # default


def test_load_nodes_direct_no_ssh_host(tmp_path: Path) -> None:
    """A direct-access node may omit ssh_host — connect straight to telnet."""
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          N0CALL-7:
            type: xnet
            telnet_host: 192.0.2.10
            telnet_port: 23
            user: youruser
            sys_required: false
            description: "direct telnet"
        """,
    )
    node = load_nodes(path)["N0CALL-7"]
    assert node.ssh_host == ""  # omitted -> empty -> direct connect path
    assert node.telnet_host == "192.0.2.10"
    assert node.telnet_port == 23
    assert node.user == "youruser"
    assert node.sys_required is False
    assert node.sys_command == "SYS"  # default keyword


def test_load_nodes_sys_command(tmp_path: Path) -> None:
    """sys_command defaults to SYS; a PC/Flexnet node can set SY."""
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          XN:
            type: xnet
            telnet_host: 1.1.1.1
            telnet_port: 23
            user: me
          PCF:
            type: xnet_chained
            transit_via: XN
            connect_command: "C PCF"
            sys_command: SY
        """,
    )
    nodes = load_nodes(path)
    assert nodes["XN"].sys_command == "SYS"   # default
    assert nodes["PCF"].sys_command == "SY"   # override on the chained target


def test_load_nodes_missing_field_raises(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          BROKEN:
            type: xnet
            ssh_host: iw2ohx-gw
            # missing telnet_host
            telnet_port: 23
            user: x
        """,
    )
    with pytest.raises(ValueError, match="telnet_host"):
        load_nodes(path)


def test_load_nodes_no_top_level_nodes(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(path, "some_other_key: 1")
    with pytest.raises(ValueError, match="nodes"):
        load_nodes(path)


def test_load_nodes_file_not_found(tmp_path: Path) -> None:
    path = tmp_path / "does-not-exist.yaml"
    with pytest.raises(FileNotFoundError):
        load_nodes(path)


def test_load_nodes_chained_basic(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          IW2OHX-14:
            type: xnet
            ssh_host: iw2ohx-gw
            telnet_host: 44.134.24.2
            telnet_port: 23
            user: iw7eas-1
            sys_required: true
          IW2OHX-12:
            type: xnet_chained
            transit_via: IW2OHX-14
            connect_command: "C IW2OHX-12"
            sys_required: true
            description: "PCF via -14"
        """,
    )
    nodes = load_nodes(path)
    assert set(nodes) == {"IW2OHX-14", "IW2OHX-12"}
    chained = nodes["IW2OHX-12"]
    assert chained.type == "xnet_chained"
    assert chained.transit_via == "IW2OHX-14"
    assert chained.connect_command == "C IW2OHX-12"
    assert chained.sys_required is True
    assert chained.description == "PCF via -14"
    # Direct-access fields default to empty for chained nodes
    assert chained.ssh_host == ""
    assert chained.telnet_host == ""
    assert chained.telnet_port == 0
    assert chained.user == ""


def test_load_nodes_chained_missing_transit_via(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          IW2OHX-12:
            type: xnet_chained
            connect_command: "C IW2OHX-12"
        """,
    )
    with pytest.raises(ValueError, match="transit_via"):
        load_nodes(path)


def test_load_nodes_chained_unknown_transit(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          IW2OHX-12:
            type: xnet_chained
            transit_via: GHOST-99
            connect_command: "C IW2OHX-12"
        """,
    )
    with pytest.raises(ValueError, match="unknown transit node"):
        load_nodes(path)


def test_load_nodes_multi_hop_resolves(tmp_path: Path) -> None:
    """Multi-hop chains are supported: resolve to base + ordered connect path."""
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          BASE:
            type: xnet
            telnet_host: 1.1.1.1
            telnet_port: 23
            user: x
          MID:
            type: xnet_chained
            transit_via: BASE
            connect_command: "C MID"
          FAR:
            type: xnet_chained
            transit_via: MID
            connect_command: "C FAR"
        """,
    )
    nodes = load_nodes(path)  # must not raise
    base, commands = resolve_chain(nodes["FAR"], nodes)
    assert base.callsign == "BASE"
    assert base.type == "xnet"
    # Ordered from the base outward to the target.
    assert commands == ["C MID", "C FAR"]
    # Single-hop still works.
    base1, cmds1 = resolve_chain(nodes["MID"], nodes)
    assert base1.callsign == "BASE"
    assert cmds1 == ["C MID"]


def test_load_nodes_chain_cycle_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          A:
            type: xnet_chained
            transit_via: B
            connect_command: "C A"
          B:
            type: xnet_chained
            transit_via: A
            connect_command: "C B"
        """,
    )
    with pytest.raises(ValueError, match="cycle"):
        load_nodes(path)


def test_load_nodes_open_node_no_login(tmp_path: Path) -> None:
    """login_required: false lets a node omit `user` (open node, no login)."""
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          OPEN-1:
            type: xnet
            telnet_host: 192.0.2.20
            telnet_port: 23
            login_required: false
            description: "open node"
        """,
    )
    node = load_nodes(path)["OPEN-1"]
    assert node.login_required is False
    assert node.user == ""


def test_load_nodes_login_required_needs_user(tmp_path: Path) -> None:
    path = tmp_path / "nodes.yaml"
    _write(
        path,
        """
        nodes:
          NEEDS-USER:
            type: xnet
            telnet_host: 192.0.2.21
            telnet_port: 23
        """,
    )
    with pytest.raises(ValueError, match="user"):
        load_nodes(path)
