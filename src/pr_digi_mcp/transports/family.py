"""PR-Digi node-family recognition from a connect banner / MOTD or `V` output.

The three families that share the packet-radio console surface print
recognisable signatures either in their connect banner (MOTD) or in the version
line emitted by the ``V`` command:

  * ``xnet`` — "(X)NET 1.39 for DLC7" and similar
  * ``bpq``  — "BPQ32" / "LinBPQ" / a "…}" node prompt
  * ``pcf``  — "PC/Flexnet", "PCFLEX", bare "FlexNet" version banners

Detection is best-effort and side-effect-free: it only inspects text a caller
already has (banner) or fetches once (``V``). Unknown output returns ``None`` so
the caller can fall back to the generic single-letter command surface.
"""

from __future__ import annotations

import re

# Order matters: check the most specific signatures first. (X)Net and PC/Flexnet
# both mention "flexnet" in places, so match the explicit family tokens.
_SIGNATURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("xnet", re.compile(r"\(X\)NET|\bXNET\b", re.IGNORECASE)),
    ("pcf", re.compile(r"PC[\s/=-]?FLEX(NET)?|\bPCFLEX", re.IGNORECASE)),
    # Match "BPQ" anywhere — covers "BPQ Packet Switch", "BPQ32", "LinBPQ",
    # "G8BPQ". (X)Net / PC-Flexnet are matched first, so a stray "BPQ" in an
    # xnet banner can't win.
    ("bpq", re.compile(r"BPQ", re.IGNORECASE)),
)

Family = str  # "xnet" | "bpq" | "pcf"


def detect_family(text: str) -> Family | None:
    """Return the PR-Digi family inferred from ``text``, or None if unclear."""
    if not text:
        return None
    for name, pattern in _SIGNATURES:
        if pattern.search(text):
            return name
    return None
