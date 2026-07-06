# Open PR-DIGI MCP — Generalization Plan

Roadmap for turning the IW2OHX-specific `pr-digi-mcp` into a project **anyone**
can run against their own packet-radio nodes. The core was already
config-driven (node inventory in `nodes.yaml`, secrets in the OS keyring), so
this is packaging-and-polish, not a rewrite.

## Status legend
✅ done · 🔶 in progress · ⬜ todo

---

## Tier 1 — "anyone can run it" (current target)

The functional bar: a new operator can point the server at their own nodes —
**with or without an SSH jump host** — and drive them.

- ✅ **Optional SSH jump** — `ssh_host` is now optional. With it set, telnet is
  tunnelled over SSH (as before); omitted, the server connects directly to
  `telnet_host:telnet_port`. Implemented once in `XnetTransport.connect()`
  (BPQ inherits it; the chained transport calls `super().connect()`), plus the
  `config.py` loader no longer requires `ssh_host`.
- ✅ **Config loader** accepts direct nodes (only `telnet_host`/`telnet_port`/`user`
  required for direct-access types).
- ✅ **Generic example configs** — `nodes.example.yaml` / `credentials.example.yaml`
  ship with placeholder `N0CALL-*` nodes demonstrating direct, SSH-jump, BPQ,
  and chained modes. No station baked in.
- ✅ **Genericized user-facing surface** — MCP tool parameter descriptions no
  longer name IW2OHX nodes ("as configured in nodes.yaml").
- ✅ **LICENSE** — MIT.
- ✅ **pyproject** — public metadata, MIT, project URLs, keywords, classifiers.
- ✅ **README** — generic quickstart, connection modes, safety/authorization note.
- ✅ **Credentials portability** — already cross-platform via `keyring`
  (macOS/Windows/Linux) + YAML fallback; documented generically.
- 🔶 **Tests** — existing unit tests (config, commands, safety, challenge parsing)
  kept; add a direct-node (no `ssh_host`) config test.
- ⬜ **Final docstring/example sweep** — a few internal docstrings still use real
  callsigns as *format examples* (e.g. `IW2OHX-14` in a callsign-validator
  docstring, `BPQBOL:IW2OHX-13}` as a prompt-shape example). Harmless, but tidy
  to a neutral example (`N0CALL`) before a tagged release.

## Tier 2 — polished public release

- ✅ **CI** — GitHub Actions (`.github/workflows/ci.yml`): ruff + mypy(src) +
  pytest on Python 3.10 / 3.11 / 3.12 / 3.13.
- ✅ **Mock transport + integration test** (`tests/test_integration_mock.py`) —
  an in-process asyncio TCP server speaks a minimal (X)Net/BPQ protocol
  (login → SYS/PASSWORD challenge → command → BYE); the transports drive it
  over the **direct** path (no SSH, no hardware), covering connect→login→
  elevate→command→disconnect + a wrong-password rejection case.
- ✅ **`CONTRIBUTING.md`** — dev setup, checks, testing (incl. "send a transcript"),
  where-things-live, safety, licensing.
- ✅ **Client config examples** — `docs/mcp-clients.md` + `examples/claude_desktop_config.json`
  (Claude Desktop + Claude Code, stdio).
- ✅ **Tagged release `v0.1.0`** — annotated git tag + GitHub release.
- ✅ **`DESIGN.md`** — generic architecture doc (stack, node/config model, direct-vs-SSH
  connectivity, transports, auth & credentials, safety gate, security, extending, testing);
  IW2OHX kept only as a §12 reference-deployment example.
- ⬜ **Publish to PyPI** (`pipx install pr-digi-mcp`).
- ⬜ Issue/PR templates.

## Tier 3 — capability breadth (optional, post-release)

- ⬜ Optional-login nodes (no user/password prompt).
- ⬜ Structured parsers (typed JSON for `L`/`D`/`NODES`) rather than raw text.
- ⬜ Aggregation tools across all configured nodes (network-wide topology, route
  search, link-quality history).
- ⬜ Multi-hop AX.25 chains (currently single-hop `xnet_chained`).
- ⬜ **Authenticated remote access.** Today the server is **stdio-only with no
  client-side authentication** — anyone who can launch the process inherits
  access to every configured node's credentials. That fits the intended
  single-operator, local model. For remote or multi-user use it would need an
  authenticated HTTP/SSE transport in front (e.g. bearer token / OAuth, per-user
  scoping, and TLS). Until then, do **not** expose the server beyond the local
  host.

---

## Known caveat
The maintainer can make the server *architecturally* generic and unit-test it,
but cannot fully validate it against a **second real station's** nodes. The
Tier-2 mock-transport harness is the best substitute; real-world confirmation
depends on early adopters. Please open issues with `L`/`D`/`FL` transcripts if
your (X)Net/BPQ build behaves differently.
