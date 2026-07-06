"""Approval gate for dangerous (X)Net SYS commands.

The server never executes a state-destroying, identity/addressing-changing, or
node-affecting command on its own initiative. Dangerous structured tools take a
``confirm: bool`` flag; the raw ``xnet_sys_command`` escape hatch classifies its
argument with :func:`is_dangerous_command`. In both cases execution is refused —
a human-readable APPROVAL block (from :func:`approval_required`) is returned
instead — unless ``confirm=True``.

The LLM may only set ``confirm=True`` AFTER the human operator has explicitly
approved the exact command in conversation. It must never approve on its own.
"""

from __future__ import annotations

# Canonical (X)Net commands whose effect is destructive, changes node identity
# or addressing, or takes a port/service/the node offline.
#
# (X)Net matches commands by case-insensitive prefix (e.g. `RES` -> RESET), so
# the classifier flags a verb when it is a prefix of — or is prefixed by — any
# of these. That deliberately errs toward caution for ambiguous abbreviations
# (`RE` matches READ/REName/RESET, so it is treated as dangerous).
DANGEROUS_COMMANDS: frozenset[str] = frozenset(
    {
        "ATTACH",
        "DETACH",
        "RESET",
        "PRGEXIT",
        "RUN",
        "RM",
        "LOAD",
        "EDIT",
        "MY",  # MY CALL / MY ALIAS
        "MYIP",
        "TIME",
        "PASSWD",
        "IPSTOP",
        "IPTRANS",
        "IFCONFIG",
        "SUBNET",
        "MCROUTE",
        "COMPH",
        "STOP",
        "EXECUTE",
        "RATTACH",
    }
)

# BPQ32 / LinBPQ dangerous commands (different dialect from (X)Net — e.g. BPQ
# `ATTACH` is a harmless user command, so it is NOT here). Pass this set to
# is_dangerous_command() when classifying a BPQ console command.
BPQ_DANGEROUS_COMMANDS: frozenset[str] = frozenset(
    {
        "REBOOT",
        "RECONFIG",
        "STOPPORT",
        "STOPCMS",
        "KISS",
        "TELRECONFIG",
        "WL2KSYSOP",
    }
)

# Sub-command tokens that turn an otherwise-readonly prefix command destructive,
# e.g. `Router flexnet del ...`, `NODE DEL ...`, `IPRoute del ...`.
DANGEROUS_ARG_TOKENS: frozenset[str] = frozenset(
    {"DEL", "DELETE", "KILL", "FLUSH", "CLEAR", "REMOVE"}
)


# Below this length, a prefix is too ambiguous to flag by abbreviation — e.g.
# the common read commands `D` (Dest) and `L` (Links) are 1-char prefixes of
# DETACH / LOAD. Short dangerous verbs (RM, MY) are still caught by exact match.
_MIN_PREFIX_LEN = 3


def is_dangerous_command(
    command: str,
    *,
    dangerous_commands: frozenset[str] = DANGEROUS_COMMANDS,
    arg_tokens: frozenset[str] = DANGEROUS_ARG_TOKENS,
) -> bool:
    """Return True if ``command`` should require explicit operator approval.

    Dangerous when the first verb (a) exactly matches a dangerous command,
    (b) is a >=3-char abbreviation of one (RES -> RESET, ATTA -> ATTACH), or
    (c) any later token is a destructive sub-token (DEL/KILL/FLUSH/...), which
    catches `Router flexnet del`, `NODE DEL`, `IPRoute del`, etc.

    Pass ``dangerous_commands=BPQ_DANGEROUS_COMMANDS`` to classify a BPQ
    console command instead of the default (X)Net dialect.
    """
    tokens = command.strip().upper().split()
    if not tokens:
        return False

    verb = tokens[0]
    if verb in dangerous_commands:
        return True
    if len(verb) >= _MIN_PREFIX_LEN and any(
        canon.startswith(verb) for canon in dangerous_commands
    ):
        return True

    return any(tok in arg_tokens for tok in tokens[1:])


def approval_required(*, node: str, action: str, command: str, risk: str) -> str:
    """Build the standard "NOT EXECUTED — approval required" response block."""
    return (
        "⚠️  APPROVAL REQUIRED — NOT EXECUTED\n"
        "\n"
        f"Node:    {node}\n"
        f"Action:  {action}\n"
        f"Command: {command}\n"
        f"Risk:    {risk}\n"
        "\n"
        "This command changes persistent or live node state and was NOT run.\n"
        "Present it to the operator verbatim. Re-invoke this tool with "
        "confirm=true\nONLY after the operator has explicitly approved. Never "
        "set confirm=true\non your own initiative."
    )
