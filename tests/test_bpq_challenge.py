"""Unit tests for the BPQ32 / LinBPQ PASSWORD challenge parser."""

from __future__ import annotations

import pytest

from pr_digi_mcp.transports.bpq import (
    BPQ_OK_REPLY,
    BPQ_PASSWORD_CHALLENGE,
    BPQ_REJECTED,
)


def _resolve(buf: bytes, pwd: str) -> str:
    """Pure function: parse the BPQ challenge from `buf`, build response from `pwd`."""
    m = BPQ_PASSWORD_CHALLENGE.search(buf)
    assert m is not None, f"no challenge in {buf!r}"
    positions = [int(p) for p in m.groups()]
    return "".join(pwd[p - 1] for p in positions)


def test_space_separated_two_digit_challenge() -> None:
    # Wire shape from the BPQ SYSOP guide.
    buf = b"BPQBOL:IW2OHX-13} 04 10 03 07 04\r\n"
    pwd = "ABCDEFGHIJ"  # 10-char synthetic
    # positions 4,10,3,7,4 → D J C G D
    assert _resolve(buf, pwd) == "DJCGD"


def test_space_separated_one_digit_challenge() -> None:
    buf = b"BPQBOL:IW2OHX-13} 1 3 2 8 4\r\n"
    pwd = "ABCDEFGH"  # 8-char synthetic (SHERWOOD is also 8 chars)
    # positions 1,3,2,8,4 → A C B H D
    assert _resolve(buf, pwd) == "ACBHD"


def test_hyphen_separated_challenge() -> None:
    # Some BPQ flavours emit hyphenated digits.
    buf = b"UFVBPQ:IR2UFV} 02-05-01-08-03\r\n"
    pwd = "ABCDEFGH"
    # positions 2,5,1,8,3 → B E A H C
    assert _resolve(buf, pwd) == "BEAHC"


def test_mixed_separator_challenge() -> None:
    # Mixed spaces and hyphens, just in case.
    buf = b"BOLHF:IW2OHX-15} 1-2 3-4 5\r\n"
    pwd = "ABCDEFGH"
    # positions 1,2,3,4,5 → A B C D E
    assert _resolve(buf, pwd) == "ABCDE"


def test_challenge_position_out_of_range_raises() -> None:
    # 10 exceeds an 8-char password.
    m = BPQ_PASSWORD_CHALLENGE.search(b"BPQBOL:N0CALL} 10 1 1 1 1\r\n")
    assert m is not None
    positions = [int(p) for p in m.groups()]
    with pytest.raises(IndexError):
        _ = "".join("ABCDEFGH"[p - 1] for p in positions)


def test_ok_reply_recognised() -> None:
    # Sessions BPQ deems local skip the challenge entirely.
    assert BPQ_OK_REPLY.search(b"BPQBOL:IW2OHX-13} Ok\r\n") is not None
    assert BPQ_OK_REPLY.search(b"UFVBPQ:IR2UFV} ok\r\n") is not None
    assert BPQ_OK_REPLY.search(b"BOLHF:IW2OHX-15} OK\r\n") is not None


def test_no_match_returns_none() -> None:
    assert BPQ_PASSWORD_CHALLENGE.search(b"random output\r\nBPQBOL}") is None
    assert BPQ_OK_REPLY.search(b"random output\r\nBPQBOL}") is None


def test_rejected_markers() -> None:
    assert BPQ_REJECTED.search(b"Invalid password\r\n") is not None
    assert BPQ_REJECTED.search(b"sorry - try again\r\n") is not None
    assert BPQ_REJECTED.search(b"Ok\r\n") is None


def test_only_four_digits_is_not_a_challenge() -> None:
    # Four-of-a-kind shouldn't be misread as a challenge.
    assert BPQ_PASSWORD_CHALLENGE.search(b"} 1 2 3 4\r\n") is None
