# Open PR-DIGI MCP Server

**Operate packet-radio digipeater nodes from Claude (and other MCP clients).**

An [MCP](https://modelcontextprotocol.io) server that exposes packet-radio
digital nodes — **(X)Net**, **PC/Flexnet**, **BPQ32 / LinBPQ** — as structured
tool calls. Instead of a sysop opening a telnet session per node, logging in,
running `L` / `D` / `FL` / `NODES` / `ROUTES`, and parsing the output by eye,
an LLM operator gets one typed tool per operation and can query or manage the
whole network from a single conversation.

> This is the **generalized, open** edition. It is config-driven — it ships
> with **no** station baked in. The original was developed for the IW2OHX
> station, which now serves as the reference deployment.

## What it can do

- **Diagnostics (read-only):** `L` / `D` / `FL` / `MH` / `NODES` / `ROUTES` /
  `PORTS` / links / stats / heard-lists / IP & ARP tables — returned as text/JSON.
- **Management (guarded):** parameter set, route/node add-del, link reset, port
  and CMS control, etc. Every state-changing / identity-changing / offline-taking
  command **refuses to run** unless called with an explicit confirmation flag that
  the LLM may set **only after the human operator approves** (see *Safety*).
- **Node types & transports:**
  - `xnet` — **(X)Net** telnet nodes ((X)Net V1.39 command set; the only type with
    the structured `xnet_*` write tools)
  - `bpq` / `linbpq` — BPQ32 (Windows) / LinBPQ (Linux), incl. `PASSWORD` sysop elevation
  - `xnet_chained` — AX.25-only nodes reached via `C <call>` from a transit node
    (single- or multi-hop; first hop may be (X)Net **or** BPQ/LinBPQ). **PC/Flexnet
    lives here** — it has *no telnet* and a *different command set* from (X)Net, so
    it's driven via `xnet_sys_command` (see [`docs/tools.md`](docs/tools.md)), not
    the structured (X)Net tools.

> **(X)Net ≠ PC/Flexnet.** They are distinct node families with different command
> sets. (X)Net is telnet-reachable; PC/Flexnet is packet-radio-only (chained).

## How it connects

Each node is described in `nodes.yaml`. Two connection modes:

- **Direct** — connect straight to `telnet_host:telnet_port` (node on your LAN,
  or reachable over HAMNET / AMPRNet / the Internet). Just omit `ssh_host`.
- **Via SSH jump host** — set `ssh_host` (an alias from your `~/.ssh/config`) and
  the telnet TCP channel is tunnelled over SSH. Handy when the nodes are only
  reachable from a gateway box.

Credentials live in your **OS keyring** (macOS Keychain / Windows Credential
Manager / Linux Secret Service, via [`keyring`](https://pypi.org/project/keyring/)),
with an optional `credentials.yaml` fallback. Passwords are never stored in the
node inventory and never committed.

## Install

Requires Python 3.10+.

```bash
pip install "git+https://github.com/onionuser79/Open-PR-DIGI-MCP-Server-for-Claude-AI"
# or, for a local dev checkout:
git clone https://github.com/onionuser79/Open-PR-DIGI-MCP-Server-for-Claude-AI
cd Open-PR-DIGI-MCP-Server-for-Claude-AI
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Quickstart

```bash
mkdir -p ~/.config/pr-digi-mcp
cp config/nodes.example.yaml       ~/.config/pr-digi-mcp/nodes.yaml
cp config/credentials.example.yaml ~/.config/pr-digi-mcp/credentials.yaml
chmod 600 ~/.config/pr-digi-mcp/credentials.yaml
# 1. edit nodes.yaml     — your callsigns, hosts, types, ssh_host (optional)
# 2. set passwords       — OS keyring (preferred) or credentials.yaml
# 3. run the server
pr-digi-mcp
```

Then point your MCP client (e.g. Claude Desktop / Claude Code) at the
`pr-digi-mcp` command — see [docs/mcp-clients.md](docs/mcp-clients.md) for
ready-to-copy Claude Desktop / Claude Code configs. Smoke-test a single node
without an MCP client:

```bash
pr-digi-mcp test N0CALL-14        # connect + run a read-only command
```

## Safety & authorization

This tool can send **sysop-level commands to live amateur-radio infrastructure**.

- Only operate nodes **you are authorized to operate.**
- Dangerous commands are gated behind an explicit `confirm=true` that the model
  must not set without human approval.
- You are responsible for compliance with your license conditions and national
  regulations. The software is provided "as is" (see [LICENSE](LICENSE), MIT).

## Credits

Developed for the **IW2OHX** digital station (the reference deployment) and
generalized for anyone to run.

**Docs:** [`docs/tools.md`](docs/tools.md) — supported node types + the full
81-tool catalog · [`docs/onboarding-nodes.md`](docs/onboarding-nodes.md) —
access prerequisites, credential storage, and how to onboard/offboard a node ·
[DESIGN.md](DESIGN.md) — architecture · [CONTRIBUTING.md](CONTRIBUTING.md) ·
[PLAN.md](PLAN.md) — roadmap.

**Onboarding a node?** Ask Claude Code — the repo ships `onboard-pr-digi` and
`offboard-pr-digi` skills (`.claude/skills/`) that drive it step by step.
