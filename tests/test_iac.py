"""Unit tests for the telnet IAC-stripping helper. No network."""

from __future__ import annotations

from pr_digi_mcp.transports.xnet import XnetTransport


def _strip(data: bytes) -> bytes:
    return XnetTransport._strip_iac(data)


def test_strip_iac_passthrough_plain_text() -> None:
    assert _strip(b"Hello, world\r\n") == b"Hello, world\r\n"


def test_strip_iac_removes_will() -> None:
    # IAC WILL ECHO  →  drop 3 bytes
    assert _strip(b"abc\xff\xfb\x01def") == b"abcdef"


def test_strip_iac_removes_wont_do_dont() -> None:
    cases = [
        (b"\xff\xfc\x18", b""),  # WONT TERMINAL-TYPE
        (b"\xff\xfd\x03", b""),  # DO   SUPPRESS-GA
        (b"\xff\xfe\x05", b""),  # DONT STATUS
    ]
    for src, expected in cases:
        assert _strip(b"pre" + src + b"post") == b"pre" + expected + b"post"


def test_strip_iac_escaped_ff_becomes_data_byte() -> None:
    # IAC IAC  →  literal 0xFF as data
    assert _strip(b"a\xff\xffb") == b"a\xffb"


def test_strip_iac_two_byte_command_skipped() -> None:
    # IAC IP (interrupt process) is 2 bytes
    assert _strip(b"a\xff\xf4b") == b"ab"


def test_strip_iac_handles_chunked_truncation_safely() -> None:
    # Trailing IAC without its option byte: leave the data we have,
    # caller will receive the rest on the next chunk.
    out = _strip(b"data\xff\xfb")
    assert out == b"data"
