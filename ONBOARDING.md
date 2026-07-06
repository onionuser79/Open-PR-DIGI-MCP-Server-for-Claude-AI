# Onboarding — Open PR-DIGI MCP Server

Welcome! This gets a new contributor from zero to a working dev setup. It
complements the repo docs: **README** (what/why + quickstart), **DESIGN.md**
(architecture), **CONTRIBUTING.md** (rules & workflow).

Repo: https://github.com/onionuser79/Open-PR-DIGI-MCP-Server-for-Claude-AI

## 1. What it is (30 seconds)
An MCP server that exposes packet-radio digipeater nodes — **(X)Net**,
**PC/Flexnet**, **BPQ32 / LinBPQ** — as tool calls an LLM (Claude) can drive.
It is **config-driven** (no station baked in), talks **stdio**, and gates every
state-changing command behind an explicit confirmation.

## 2. Prerequisites
- **Python 3.10+**. On macOS the system `python3` is 3.9 — use Homebrew
  (`python3.14`) or `pyenv`.
- `git`.
- A real (X)Net/BPQ node to test against is **not required** — the test suite
  runs against an in-process mock node.

## 3. Setup
```bash
git clone https://github.com/onionuser79/Open-PR-DIGI-MCP-Server-for-Claude-AI
cd Open-PR-DIGI-MCP-Server-for-Claude-AI
python3.12 -m venv .venv          # any 3.10+ interpreter (python3.14 on macOS)
.venv/bin/pip install -e ".[dev]"
```

## 4. Verify (exactly what CI runs — keep these green)
```bash
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m pytest -q     # 139 tests, no hardware needed
```

## 5. Run it (no hardware)
- The suite already exercises the full **connect → login → SYS/PASSWORD → command
  → disconnect** path against a mock node (`tests/test_integration_mock.py`).
- To run the real server: copy `config/nodes.example.yaml` →
  `~/.config/pr-digi-mcp/nodes.yaml`, edit for your node(s), then either
  `pr-digi-mcp` (MCP stdio server) or smoke-test one node:
  ```bash
  pr-digi-mcp test N0CALL-14 "L"      # add --sys to elevate first
  ```
- To wire it into Claude Desktop / Claude Code: see `docs/mcp-clients.md`.

## 6. Codebase map
Full table in **DESIGN.md §2.2**. The essentials:
- `config.py` — `nodes.yaml` schema + loader
- `credentials.py` — keyring → YAML fallback
- `transports/` — `xnet.py` (base: optional-SSH telnet, login, read, SYS),
  `bpq.py` (PASSWORD), `chained.py` (AX.25 `C <call>`)
- `safety.py` — dangerous-command classifier (the confirm gate)
- `server.py` — the MCP tools + CLI

## 7. How to contribute
- Read **CONTRIBUTING.md**.
- Open issues with the templates — especially **"Node compatibility"**: if your
  node build parses differently, paste a **sanitised** `L`/`D`/`FL`/login
  transcript so we can extend the transports/parsers and the mock test.
- PRs: small and focused; run ruff + mypy + pytest; extend
  `tests/test_integration_mock.py` if you touch a transport/parser; the PR
  template has the checklist.

## 8. Non-negotiables
- **Never commit secrets.** Passwords live in the OS keyring or a gitignored
  `credentials.yaml`. Use placeholders in the repo (`N0CALL-*`, `192.0.2.x`).
- **State-changing commands must go through the `safety.py` confirm gate** — the
  model may only set `confirm=True` after a human approves.
- Only operate nodes you're **licensed/authorised** for. The server is
  stdio-local with no client auth — **don't expose it beyond localhost**.

## 9. Working with Claude Code
Open the repo in Claude Code and ask it to: run the checks, explain a transport,
add a node type or tool following **DESIGN.md §10**, or extend the mock server
from a transcript. It will respect the confirm gate for anything that changes
node state.
