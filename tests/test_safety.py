"""Unit tests for the dangerous-command classifier and approval gate."""

from __future__ import annotations

import pytest

from pr_digi_mcp import safety


@pytest.mark.parametrize(
    "cmd",
    [
        "RESET",
        "reset",
        "RES",  # abbreviation
        "ATTACH axudp xnet 256",
        "DETACH xnet",
        "RM /flash/foo.txt",
        "LOAD bin",
        "MY CALL IW2OHX-9",
        "MYIP 44.134.24.2",
        "TIME 2026-06-09",
        "STOP HTTPD",
        "PRGEXIT",
        "Router flexnet del 6 IQ2LB-6",  # destructive sub-token
        "IPRoute del 44.0.0.0",
        "ARp DEL 44.134.24.1",
    ],
)
def test_dangerous_commands_flagged(cmd: str) -> None:
    assert safety.is_dangerous_command(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "L",
        "D",
        "MH",
        "INFO",
        "Router flexnet",  # read view
        "IPRoute",
        "ARp",
        "PS",
        "NETStat",
        "PING 44.134.24.1",
        "LOG",
        "",
    ],
)
def test_safe_commands_not_flagged(cmd: str) -> None:
    assert safety.is_dangerous_command(cmd) is False


@pytest.mark.parametrize(
    "cmd",
    [
        "REBOOT",
        "REB",  # abbreviation
        "RECONFIG",
        "STOPPORT 2",
        "STO",  # abbreviation of STOPPORT/STOPCMS
        "STOPCMS 2",
        "KISS 2 TXDELAY 30",
        "TELReconfig 5 ALL",
        "WL2KSYSOP SET",
        "NODE DEL IW2OHX-13",  # destructive sub-token
    ],
)
def test_bpq_dangerous_flagged(cmd: str) -> None:
    assert (
        safety.is_dangerous_command(
            cmd, dangerous_commands=safety.BPQ_DANGEROUS_COMMANDS
        )
        is True
    )


@pytest.mark.parametrize(
    "cmd",
    [
        "PORTS",
        "ROUTES",
        "NODES",
        "NODE ADD BOLNET:IW2OHX-13 200 IW2OHX-14",  # additive, not destructive
        "STATS",
        "STARTPORT 2",  # restorative
        "STARTCMS 2",
        "TELSTATUS",
        "VERSION",
        "TXDELAY 2",
    ],
)
def test_bpq_safe_not_flagged(cmd: str) -> None:
    assert (
        safety.is_dangerous_command(
            cmd, dangerous_commands=safety.BPQ_DANGEROUS_COMMANDS
        )
        is False
    )


def test_bpq_attach_is_not_dangerous() -> None:
    # BPQ ATTACH is a harmless user command (unlike (X)Net ATTACH).
    assert (
        safety.is_dangerous_command(
            "ATTACH 2", dangerous_commands=safety.BPQ_DANGEROUS_COMMANDS
        )
        is False
    )


def test_approval_block_contains_command_and_marker() -> None:
    block = safety.approval_required(
        node="IW2OHX-14",
        action="Delete flexnet route on port 6 to IQ2LB-6",
        command="ROUTER FLEXNET DEL 6 IQ2LB-6",
        risk="Tears down a live peering.",
    )
    assert "APPROVAL REQUIRED" in block
    assert "NOT EXECUTED" in block
    assert "ROUTER FLEXNET DEL 6 IQ2LB-6" in block
    assert "IW2OHX-14" in block
    assert "confirm=true" in block
