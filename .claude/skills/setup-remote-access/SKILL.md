---
name: setup-remote-access
description: Configure authenticated remote (HTTP) access to the pr-digi-mcp server. Use when the operator wants to expose the MCP over the network / enable serve-http / set up a bearer token so a remote MCP client can connect. Drives token generation + storage, host/TLS choice, launch, verification, and client config.
---

# Configure remote access + bearer-token auth

Drive the operator through enabling `pr-digi-mcp serve-http` (MCP over Streamable
HTTP, gated by a bearer token). Full reference: `docs/remote-access.md`.

> **Secret hygiene — non-negotiable.** The bearer token must NOT land in this chat,
> in `nodes.yaml`, or in the repo. Have the operator **generate and store it
> themselves** using the `!` shell prefix (so the value stays in their terminal).
> Never run a command that prints the token into the conversation, and never ask
> the operator to paste it to you.

## 1. Establish the deployment shape (ask first)
- **Local only** (client on the same host, or you'll add a tunnel/proxy later) →
  bind loopback `127.0.0.1` (default). No TLS needed on the MCP itself.
- **Remote, direct TLS** → bind a reachable host with `--tls-cert`/`--tls-key`.
- **Remote, behind a reverse proxy** (nginx/caddy/traefik terminates TLS) → keep
  `--host 127.0.0.1` and proxy to it.

`serve-http` **refuses a non-loopback bind without TLS** unless `--insecure` is
passed — steer away from `--insecure` except for a throwaway local test.

## 2. Generate + store the token (operator runs; secret stays out of chat)
Have the operator run, via `!`:
```
! python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
Then store it — **keyring preferred** (paste at the prompt; multiple comma-separated
for several operators / rotation):
```
! keyring set pr-digi-mcp http_tokens
```
…or, for an env-based setup, add to their shell profile (not committed):
```
export PR_DIGI_MCP_HTTP_TOKENS="<token>[,<token2>...]"
```
You (Claude) don't need the value — only confirm it's stored.

## 3. Start the server
Pick the flags for the shape from step 1, e.g.:
```
pr-digi-mcp serve-http --host 127.0.0.1 --port 8080                    # local / behind proxy
pr-digi-mcp serve-http --host 0.0.0.0 --port 8080 --tls-cert cert.pem --tls-key key.pem   # direct TLS
```
For a persistent service, suggest a systemd unit (Linux) or launchd agent (macOS)
that sets the token env / uses the keyring and runs `serve-http` — offer to draft
one if wanted. It won't start without a token configured.

## 4. Verify
- **Unauthenticated check (safe — no token, you may run it):**
  ```
  curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/mcp      # expect 401
  ```
- **Authenticated check (operator runs via `!` so the token stays out of chat):**
  ```
  ! curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOK" \
      -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
      -X POST -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' http://127.0.0.1:8080/mcp
  ```
  Expect **not 401** (a `400` for a bare ping is fine — it means auth passed and the
  request reached the MCP layer).

## 5. Point the MCP client at it
Configure the client with the URL and the token in an `Authorization` header,
stored in the client's own config (never committed):
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

## Guardrails / reminders
- **Never** echo the token, commit it, or put it in `nodes.yaml`.
- Use **TLS** whenever the port is reachable off-host; keep loopback default otherwise.
- A valid token grants **full** access (no per-user scoping yet) — issue/rotate
  tokens deliberately and keep the port firewalled.
- The dangerous-command **confirm-gate still applies** over HTTP — unchanged.
