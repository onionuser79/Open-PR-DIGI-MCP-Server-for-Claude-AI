"""Family-recognition tests — real banner / V-command signatures."""

from __future__ import annotations

import pytest

from pr_digi_mcp.transports.family import detect_family

# Real `V` output captured from IW2OHX-14.
XNET_V = """
(X)NET 1.39 for DLC7

 500 Users
2000 L3 Flexnet Destinations
TF-Version 1.88 DLC7BOX 1.35
"""

BPQ_BANNER = "Connected to IW2OHX-15\r\nBOLHF:IW2OHX-15} LinBPQ 6.0.24.1\r\n"
PCF_BANNER = "*** connected to IW2OHX-12\r\nPC/Flexnet 3.3g\r\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (XNET_V, "xnet"),
        ("*** CONNECTED to IW2OHX-4\r\n(X)Net node\r\n", "xnet"),
        (BPQ_BANNER, "bpq"),
        ("BPQ32 Version 6.0.24\r\n", "bpq"),
        # Real W9GM banner — plain "BPQ", no "32"/"Lin" (regression: was unknown).
        ("Welcome to the W9GM BPQ Packet Switch - Ken in La Crosse, WI\r\n", "bpq"),
        (PCF_BANNER, "pcf"),
        ("PCFLEX 3.3g\r\n", "pcf"),
        ("", None),
        ("some unrelated banner text\r\n", None),
    ],
)
def test_detect_family(text: str, expected: str | None) -> None:
    assert detect_family(text) == expected
