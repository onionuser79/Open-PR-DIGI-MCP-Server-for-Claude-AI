# Open PR-DIGI MCP Server

MCP server exposing packet-radio digipeater nodes — **(X)Net**, **PC/Flexnet**,
**BPQ32/LinBPQ** — as typed tool calls. Python 3.10+, asyncio, FastMCP over stdio.
Station-agnostic: **no station knowledge in code**, all of it in `nodes.yaml`.

## Commands

```bash
.venv/bin/pip install -e ".[dev]"   # dev setup (python3 -m venv .venv first)

.venv/bin/ruff check .              # lint — line length 100
.venv/bin/mypy src                  # types — strict
.venv/bin/python -m pytest -q       # unit + in-process mock-transport integration

pr-digi-mcp                         # run the server (stdio)
pr-digi-mcp test N0CALL-14          # smoke-test one node, read-only command
pr-digi-mcp serve-http              # opt-in bearer-token HTTP, loopback by default
```

Those three checks are exactly what CI runs (Python 3.10–3.13). Keep them green.
No network or radio hardware is needed for any test.

## Hard rules

1. **Never commit secrets or real station data.** No real callsigns, hosts or
   passwords anywhere in the repo — use `N0CALL-*` and `192.0.2.x`. Secrets live
   in the OS keyring (service `pr-digi-mcp`) or a gitignored 0600
   `credentials.yaml`. Never in `nodes.yaml`.
2. **The confirm gate is not optional.** Any tool that changes persistent state,
   changes identity, or takes a node offline must be classified in `safety.py`
   and must refuse to run without `confirm=True`. Never add an unguarded
   write/reset/delete path. This drives live amateur-radio infrastructure.
3. **`mypy --strict` must pass on `src`.** Type hints everywhere.
4. **Tests accompany behaviour changes.** If a node build behaves differently,
   extend `tests/test_integration_mock.py` with a sanitised transcript rather
   than reaching for real hardware.
5. Docstrings on public functions explain **why**, not what.

## Code map

| Area | File |
|------|------|
| MCP tool definitions + CLI | `src/pr_digi_mcp/server.py` (large — grep, don't read whole) |
| Node inventory schema / loader / `resolve_chain()` | `src/pr_digi_mcp/config.py` |
| Credentials (keyring → YAML fallback, 2 s timeout) | `src/pr_digi_mcp/credentials.py` |
| Dangerous-command classifier | `src/pr_digi_mcp/safety.py` |
| Command syntax tables + callsign validation | `src/pr_digi_mcp/commands.py` |
| Tolerant output parsers → typed records | `src/pr_digi_mcp/parsers.py` |
| On-demand route discovery + ranking (`_rank_key`) | `src/pr_digi_mcp/discovery.py` |
| Base transport: telnet/SSH, login, `SYS` elevation | `src/pr_digi_mcp/transports/xnet.py` |
| BPQ `PASSWORD` elevation | `src/pr_digi_mcp/transports/bpq.py` |
| AX.25 chained transport | `src/pr_digi_mcp/transports/chained.py` |
| Family detection (MOTD, else `V`) | `src/pr_digi_mcp/transports/family.py` |
| Bearer-token ASGI gate | `src/pr_digi_mcp/http_auth.py` |

## Domain gotchas

- **(X)Net ≠ PC/Flexnet.** Distinct families, different command sets. (X)Net is
  telnet-reachable and the only type with structured `xnet_*` write tools;
  PC/Flexnet is packet-radio-only (`xnet_chained`) and is driven through
  `xnet_sys_command`. Don't let them blur together in tools or docs.
- **Sysop elevation is a positional challenge** — the node asks for characters at
  1-indexed positions; reply concatenated, no spaces. The full password never
  goes on the wire. BPQ instead answers `Ok` *or* a 5-number challenge.
- **RF-plaintext caveat:** answering a SYS challenge over an AX.25 hop leaks
  password characters on the air over time. Chained/RF nodes are lower-trust and
  should have a distinct sys password.
- **Reads use an idle heuristic** (`idle_ms` silence, bounded by `max_wait_s`),
  not a prompt match. Bursty nodes need a higher `idle_ms`. Streaming commands
  (`MOnitor`, `IPDump`) must use `capture()`'s fixed window instead, or frames
  get truncated.
- Bytes decode as **latin-1** (lossless 1:1); telnet IAC sequences are stripped.
- One short-lived transport per tool call (`async with`) — no connection pool.
  The `asyncio.Lock` in `XnetTransport` is **per session**: it serialises
  send/receive inside one transport, not across tool calls. Don't introduce
  long-lived or pooled sessions without revisiting that.
- Discovery reads only FlexNet `D` and NetROM `N` tables. Link tables (`L`) are
  deliberately excluded. FlexNet cost always outranks NetROM; ranking policy
  belongs in `_rank_key` and nowhere else.
- Over stdio there is **no client authentication** — launching the server grants
  every configured node's credentials. Single-operator local trust boundary.

## Deeper docs — read on demand, not by default

Intentionally **not** `@`-imported, so they cost nothing until needed:

- `DESIGN.md` — architecture, transports, credential and safety model.
- `docs/tools.md` — full tool catalog and per-type support matrix.
- `docs/onboarding-nodes.md` — access prerequisites, credential storage.
- `docs/remote-access.md` — authenticated HTTP.
- `CONTRIBUTING.md` — PR expectations. `PLAN.md` — roadmap.
- `.claude/skills/` — `onboard-pr-digi`, `offboard-pr-digi`,
  `setup-remote-access`. Prefer invoking these over improvising node changes.
