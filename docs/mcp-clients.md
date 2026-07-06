# Connecting an MCP client

The server speaks MCP over **stdio** — a client launches the `pr-digi-mcp`
command and talks to it on stdin/stdout. Before wiring up a client:

1. **Install** the server (see the README) so `pr-digi-mcp` is on your PATH
   (or note its absolute path — e.g. a venv's `.../.venv/bin/pr-digi-mcp`,
   or the pipx shim `~/.local/bin/pr-digi-mcp`).
2. **Configure** `~/.config/pr-digi-mcp/nodes.yaml` (and credentials) — the
   server reads them at startup regardless of which client launches it.
3. **Smoke-test** without a client:
   ```bash
   pr-digi-mcp test N0CALL-14 "L"        # add --sys to elevate first
   ```

Find the exact command path to use in the configs below:

```bash
which pr-digi-mcp        # e.g. /Users/you/.local/bin/pr-digi-mcp
```

## Claude Desktop

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Add a `pr-digi` server (a ready-to-copy file is in
[`examples/claude_desktop_config.json`](../examples/claude_desktop_config.json)):

```json
{
  "mcpServers": {
    "pr-digi": {
      "command": "pr-digi-mcp"
    }
  }
}
```

Use the **absolute path** if `pr-digi-mcp` isn't on Claude Desktop's PATH, and
add `-v` for debug logging:

```json
{
  "mcpServers": {
    "pr-digi": {
      "command": "/Users/you/.venv/bin/pr-digi-mcp",
      "args": ["-v"]
    }
  }
}
```

Restart Claude Desktop, then ask it to run a read-only query (e.g. "show the
link table on N0CALL-14").

## Claude Code

Add it from the CLI (stdio is the default transport):

```bash
# user scope (available in all your projects)
claude mcp add pr-digi -- pr-digi-mcp
# or with an absolute path + debug
claude mcp add pr-digi -- /Users/you/.venv/bin/pr-digi-mcp -v
```

Or commit a **project-scoped** `.mcp.json` at the repo root so collaborators get it:

```json
{
  "mcpServers": {
    "pr-digi": {
      "command": "pr-digi-mcp",
      "args": []
    }
  }
}
```

Verify with `claude mcp list` (or `/mcp` inside a session).

## Notes

- The server exposes read-only diagnostic tools plus guarded write/sysop tools;
  dangerous commands require an explicit confirmation the model may set only
  after you approve (see the README *Safety* section).
- All node endpoints and credentials come from your local config — nothing is
  passed on the client command line.
