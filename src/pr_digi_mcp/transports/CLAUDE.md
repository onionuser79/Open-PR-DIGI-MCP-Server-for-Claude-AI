# Transports

Wire-level layer. Everything above this directory assumes a transport gives it
`connect() → run_command()/capture() → elevate_sys() → disconnect()` and hides
whether the bytes travelled over LAN telnet, an SSH tunnel, or an AX.25 hop.
Keep that contract intact.

## Class hierarchy

`XnetTransport` (`xnet.py`) is the base and owns **all** IO: connection,
login, IAC stripping, read heuristics, `SYS` elevation, teardown.
`BpqTransport` and `Ax25ChainedTransport` subclass it and override only what
differs. Fix an IO bug once, in the base — never by copying into a subclass.

- `bpq.py` — overrides elevation only (`PASSWORD` → `Ok` *or* a 5-number
  positional challenge). Inherits connect/login unchanged.
- `chained.py` — calls `super().connect()` for the outer node, then issues each
  `C <call>` in order. The target has **no separate login**: the AX.25 SABM
  carries the base node's identity inward. SYS elevation targets the *innermost*
  node's password.
- `family.py` — `detect_family()` on the MOTD, falling back to the `V` command.
- `__init__.py` — `open_transport()` (from config) and `open_dynamic_chain()`
  (ephemeral config synthesised by discovery). Add new types here, not inline.

## Connection modes

`connect()` branches on one field. `ssh_host` set → `asyncssh.connect()` then
`open_connection()`, tunnelling telnet over SSH; empty → plain
`asyncio.open_connection()`. The two stream objects share the
`read/write/drain/close/is_closing` surface, which is *why* the rest of the
transport is mode-agnostic. **Anything you add must stay within that surface** —
reaching for an `asyncssh`- or `asyncio`-specific API breaks the other mode for
every node type.

## Reading is heuristic, not prompt-matched

- `run_command()` returns after `idle_ms` of silence (measured from the first
  byte), bounded by `max_wait_s`. Bursty nodes need a higher `idle_ms`.
- `capture()` reads a **fixed window** instead — mandatory for streaming output
  (`MOnitor`, `IPDump`), where silence is normal and idle-detection truncates.
- Decode as **latin-1** (1:1, lossless). Never UTF-8: node output is arbitrary
  bytes and the LLM consumes raw text. Telnet IAC sequences are stripped first.

## Prompt, challenge and banner regexes

They live here, and they are the main thing that varies between node builds:

- login prompt: `login|user|name|callsign` + `:`/`>`; then a password prompt
- `SYS` positional challenge: `NODE>  p1 p2 p3 …`, **1-indexed**; reply with those
  characters of the sys password, concatenated, no spaces. The whole password is
  never transmitted — keep it that way.
- chained hops: wait for `*** CONNECTED to …` at each hop; failure markers raise.

When extending a regex, add a case to the mock server in
`tests/test_integration_mock.py` in the same change — a sanitised transcript
from the real node is the expected evidence. Never widen a failure-marker
pattern so far that a failed login reads as success.

## Invariants

- One short-lived session per tool call (`async with`); no pooling. The
  `asyncio.Lock` is **per instance** (`self._lock`, set in `XnetTransport`) and
  guards send/receive *within* a session — interleaved reads on one stream
  corrupt each other. It is **not** a global or per-node lock: two concurrent
  tool calls open two independent sessions to the same node.
- `disconnect()` sends `BYE` then closes; intermediate chained hops are left to
  their inactivity timeout by design.
- Transports never decide *whether* a command is allowed. That is `safety.py`.
- Transports never read credentials from disk. That is `credentials.py`.
