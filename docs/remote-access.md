# Remote access (authenticated HTTP)

By default the server runs over **stdio** (a local child process — no network).
For a remote MCP client, an **opt-in** authenticated HTTP transport is available:
MCP **Streamable HTTP** gated by a **bearer token**.

> Nothing changes for stdio users — this is a separate subcommand.
>
> **Claude Code can walk you through this** — use the `setup-remote-access` skill
> (`.claude/skills/`); it drives token generation/storage, host/TLS choice, launch,
> and verification while keeping the token out of the chat.

## Enable it

```bash
pr-digi-mcp serve-http [--host 127.0.0.1] [--port 8080] \
                       [--tls-cert cert.pem --tls-key key.pem] [--insecure] \
                       [--allowed-host NAME[:PORT] ...]
```

- **`--host`** defaults to `127.0.0.1` (loopback only). Bind wider only deliberately.
- **Non-loopback bind without TLS is refused** unless you pass `--insecure` — bearer
  tokens must not cross the network in cleartext.
- **DNS-rebinding protection:** the transport only accepts requests whose `Host`
  header matches the bind `host:port`. When you bind a LAN IP (e.g.
  `--host 192.168.1.202 --port 8765`) that address is allowed automatically; add
  **`--allowed-host`** (repeatable) for any *additional* name a client may use — a
  DNS hostname (`--allowed-host iw2ohx-gw:8765`) or a reverse-proxy public name.
  Without this a mismatched `Host` header is rejected with **HTTP 421**.
- The per-command **confirm-gate still applies** (auth ≠ authorization for destructive
  commands).

## Tokens

Valid bearer tokens are read from (merged):
1. env **`PR_DIGI_MCP_HTTP_TOKENS`** — comma-separated
2. OS keyring — service `pr-digi-mcp`, account `http_tokens` (comma-separated)

Multiple tokens are allowed (issue one per operator / rotate). Generate a strong one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# then, e.g.:
export PR_DIGI_MCP_HTTP_TOKENS="<token1>,<token2>"
# or store in the keyring:
keyring set pr-digi-mcp http_tokens        # paste comma-separated tokens
```

The server refuses to start if no tokens are configured.

## TLS

- **Direct HTTPS:** pass `--tls-cert`/`--tls-key` (uvicorn serves TLS).
- **Reverse proxy:** terminate TLS at nginx/caddy/traefik in front and proxy to the
  loopback `serve-http` port. Either way, **use TLS whenever the port is reachable
  off-host** — the token is a bearer credential.

## Point a client at it

The endpoint is the MCP Streamable-HTTP URL (`/mcp`), with the token in the
`Authorization` header. In a client that supports remote MCP + custom headers:

```json
{
  "mcpServers": {
    "pr-digi-remote": {
      "url": "https://your-host:8080/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

For **Claude Code** specifically:

```bash
claude mcp add --scope user --transport http pr-digi-remote \
  https://your-host:8080/mcp --header "Authorization: Bearer <token>"
```

**Self-signed TLS cert?** Node (which Claude Code runs on) validates HTTPS against
its own CA store, so a self-signed server cert is rejected until you trust it. Export
the cert's path via `NODE_EXTRA_CA_CERTS` in the environment that launches the client
(e.g. add `export NODE_EXTRA_CA_CERTS="$HOME/.config/pr-digi-mcp/server-cert.pem"` to
your shell profile). Use `--scope user` so the entry is available in every project.

## Verify

```bash
# no token -> 401
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/mcp
# with token -> reaches the MCP layer (not 401)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer <token>' \
     -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
     -X POST -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' http://127.0.0.1:8080/mcp
```

## Security model & limits

- **Authentication:** a valid bearer token grants access. **All tokens grant full
  access** — per-user / per-node scoping is not yet implemented (a future item).
- **Authorization:** dangerous commands still require the human-approved `confirm`
  flag (see the README *Safety* section).
- **Exposure:** loopback by default; use TLS + a firewall before exposing off-host;
  never commit tokens (env/keyring only).
