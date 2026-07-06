# Contributing

Thanks for helping improve the Open PR-DIGI MCP Server! It drives **live
amateur-radio infrastructure**, so correctness and safety matter — please read
the safety note below.

## Dev setup

Requires Python **3.10+** (CI runs 3.10–3.13). On macOS the system `python3`
may be older; use a Homebrew/pyenv interpreter.

```bash
git clone https://github.com/onionuser79/Open-PR-DIGI-MCP-Server-for-Claude-AI
cd Open-PR-DIGI-MCP-Server-for-Claude-AI
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Checks (run before opening a PR)

CI runs exactly these — keep them green:

```bash
.venv/bin/ruff check .        # lint (line length 100)
.venv/bin/mypy src            # types (strict)
.venv/bin/python -m pytest -q # unit + mock-transport integration tests
```

## Testing

- Add or update tests for any behaviour you change.
- Network/hardware are **not** required: `tests/test_integration_mock.py` runs a
  small in-process TCP server that speaks the (X)Net/BPQ login + challenge +
  command protocol, and the transports drive it over the direct path.
- **If your node build behaves differently** (different prompt shape, SYS/PASSWORD
  challenge format, banner, command output), please include a **sanitised**
  `L` / `D` / `FL` / login transcript in your issue/PR so the mock server and
  parsers can be extended to cover it. This is how we grow real-world coverage
  without a second physical station.

## Where things live

| Area | File |
|------|------|
| Node inventory schema / loader | `src/pr_digi_mcp/config.py` |
| Credentials (keyring + YAML fallback) | `src/pr_digi_mcp/credentials.py` |
| Transports (SSH-tunnelled or direct telnet; BPQ; chained AX.25) | `src/pr_digi_mcp/transports/` |
| Command syntax / callsign validation | `src/pr_digi_mcp/commands.py` |
| Dangerous-command classifier (confirm gate) | `src/pr_digi_mcp/safety.py` |
| MCP tools | `src/pr_digi_mcp/server.py` |

**Adding a tool that changes state:** it must be classified by `safety.py` and
refuse to run unless called with `confirm=True`. Never let a write/reset/delete
path run unguarded.

## Security

- **Never commit credentials.** Secrets live in the OS keyring (service
  `pr-digi-mcp`) or a gitignored `credentials.yaml`. Do not add real callsigns,
  hosts, or passwords to the repo — use placeholders (`N0CALL-*`, `192.0.2.x`).
- Only operate nodes you are authorised to operate; respect your license terms.

## Style

- Type hints everywhere; `mypy --strict` must pass on `src`.
- `ruff` clean (imports sorted, line length 100).
- Docstrings on public functions; explain *why*, not *what*.

## Licensing

By contributing you agree your contributions are licensed under the project's
**MIT** license (see [LICENSE](LICENSE)).
