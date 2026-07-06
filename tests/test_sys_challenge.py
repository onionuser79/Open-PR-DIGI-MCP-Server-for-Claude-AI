"""Unit tests for the xnet/PCF positional SYS challenge parser."""

from __future__ import annotations

import pytest

from pr_digi_mcp.transports.xnet import SYS_CHALLENGE


def _resolve(buf: bytes, pwd: str) -> str:
    """Pure function: parse the challenge from `buf`, build response from `pwd`."""
    m = SYS_CHALLENGE.search(buf)
    assert m is not None, f"no challenge in {buf!r}"
    positions = [int(p) for p in m.group(1).split()]
    return "".join(pwd[p - 1] for p in positions)


def test_xnet_8char_challenge() -> None:
    # Real wire shape captured 2026-05-20 (8-char pwd); using fake pwd here.
    buf = b"\r\nIW2OHX>  1 3 2 8 4\r\n"
    pwd = "ABCDEFGH"  # synthetic 8-char fixture
    # positions 1,3,2,8,4 → A C B H D
    assert _resolve(buf, pwd) == "ACBHD"


def test_pcf_10char_challenge() -> None:
    # Wire shape Marco shared 2026-05-20 — uses 10-char pwd. Synthetic fixture.
    buf = b"\r\nIW2OHX>  10 6 4 3 1\r\n"
    pwd = "ABCDEFGHIJ"  # synthetic 10-char fixture
    # positions 10,6,4,3,1 → J F D C A
    assert _resolve(buf, pwd) == "JFDCA"


def test_challenge_with_surrounding_noise() -> None:
    buf = (
        b"\r\n=>SYS\r\n"
        b"IW2OHX>  5 7 2\r\n"
        b"\r\n"
        b"=>"
    )
    # positions 5,7,2 of "ABCDEFGH" → E G B
    assert _resolve(buf, "ABCDEFGH") == "EGB"


def test_challenge_position_out_of_range() -> None:
    buf = b"IW2OHX>  20 1 2\r\n"
    pwd = "ABCDEFGH"  # only 8 chars; position 20 is out of range
    with pytest.raises(IndexError):
        _resolve(buf, pwd)


def test_no_challenge_pattern_returns_none_via_search() -> None:
    buf = b"some random output\r\n=>"
    assert SYS_CHALLENGE.search(buf) is None
