# Integrating & onboarding PR digis

How to make a packet-radio node reachable by the MCP: the access prerequisites,
how to store its credentials, and the step-by-step onboarding (and offboarding).
Claude Code can drive this for you — see the **`onboard-pr-digi`** /
**`offboard-pr-digi`** skills (`.claude/skills/`).

---

## 1. Prerequisites — how the MCP reaches a node

Every node reduces to a **telnet console** the MCP can open. There are three
access models; pick the one that matches how the node is reachable from the host
running the MCP.

### A. Direct telnet
The node's telnet port is reachable over TCP from the MCP host — same LAN, or over
HAMNET / AMPRNet / the Internet.
- **Need:** `telnet_host` + `telnet_port`, and a login `user` (unless the node has
  no login — then `login_required: false`).
- **No `ssh_host`.**

### B. Telnet via an SSH jump host
The node's telnet is only reachable **from a gateway box** (e.g. the node lives on
HAMNET behind a Pi you can SSH into).
- **Need:** SSH access (key/agent) to the gateway, with an alias in your
  `~/.ssh/config`; the node's `telnet_host`/`telnet_port` **as seen from that gateway**.
- **Set `ssh_host`** to the SSH alias — the telnet TCP channel is tunnelled over SSH.

### C. Chained AX.25 — a node with no telnet, reached over packet radio
The target has **no telnet at all**; it is reachable only by an AX.25 `C <call>`
connect from a transit node. **This is the only way to reach a PC/Flexnet node**
— PC/Flexnet has no telnet interface, so it is *always* this model.
- **First hop / transit node:** any **AX.25-capable node that the MCP can telnet
  into** — an **(X)Net** node *or* a **BPQ32/LinBPQ** node (directly or via SSH
  jump). It just needs to accept a `C <call>` connect.
- **Single hop:** `transit_via` = that first-hop node; `connect_command` = `C <TARGET>`.
- **Multi-hop:** `transit_via` may point at **another chained node**; the connect
  path is resolved automatically (base node → `C hop1` → … → `C target`). Cycles /
  chains that never reach a telnet-capable base are rejected at load time.
- **Login is inherited** from the base node (the AX.25 SABM carries its identity),
  so the target needs **no `user`** — only a `sys_pwd` if you want its write tools.
- **Commands differ:** PC/Flexnet's command set is *not* (X)Net V1.39's — drive it
  with the `xnet_sys_command` tool using PC/Flexnet's own syntax (see `docs/tools.md`).
- **Sysop keyword:** set `sys_command: SY` on a PC/Flexnet node so elevation sends
  `SY` (the (X)Net default is `SYS`).

**In all cases**, for the *write / sysop* tools you also need the node's **SYS**
(or BPQ **PASSWORD**) secret. Read-only tools need only the login (model A/B) or
nothing extra (model C).

---

## 2. Storing credentials

Passwords are **never** put in `nodes.yaml` and never committed. Two sources, tried
in order:

### Preferred — OS keyring (cross-platform)
Service `pr-digi-mcp`, one account per secret: `<CALLSIGN>_user` and `<CALLSIGN>_sys`.

```bash
# login password (models A/B):
keyring set pr-digi-mcp "N0CALL-14_user"
# SYS / PASSWORD secret (only if you use write/sysop tools):
keyring set pr-digi-mcp "N0CALL-14_sys"
# verify (prints the secret):
keyring get pr-digi-mcp "N0CALL-14_user"
```

Works with macOS Keychain, Windows Credential Manager, and Linux Secret
Service/KWallet. A keyring lookup is bounded by a 2 s timeout; on miss/timeout the
MCP falls back to:

### Fallback — `~/.config/pr-digi-mcp/credentials.yaml`
Mode **0600**, gitignored. `REPLACE_ME` means "unset".

```yaml
nodes:
  N0CALL-14:
    user_pwd: "…"
    sys_pwd:  "…"
  N0CALL-99:          # chained target — login inherited, so sys only
    sys_pwd:  "…"
```

**Notes**
- **Chained nodes** need only `sys_pwd` (login inherited from the base).
- **Open nodes** (`login_required: false`) need no `user_pwd`.
- **RF-plaintext caveat:** a chained node's SYS positional challenge is answered
  over the air — give RF-reached nodes a `sys_pwd` distinct from your other nodes.

---

## 3. Onboard a new node (manual)

> Or just ask Claude Code: *"onboard a new PR digi"* → the `onboard-pr-digi` skill.

1. **Pick the access model** (§1) and the `type` (`xnet`, `bpq`, `linbpq`,
   `xnet_chained`).
2. **Add the node** to `~/.config/pr-digi-mcp/nodes.yaml` (copy the shape from
   `config/nodes.example.yaml`). Examples:

   ```yaml
   nodes:
     # A) direct telnet
     N0CALL-7:  {type: xnet,   telnet_host: 192.0.2.10, telnet_port: 23, user: me, sys_required: true}
     # B) via SSH jump
     N0CALL-14: {type: xnet,   ssh_host: my-gw, telnet_host: 44.0.0.2, telnet_port: 23, user: me, sys_required: true}
     # C) chained (single hop) off N0CALL-14
     N0CALL-12: {type: xnet_chained, transit_via: N0CALL-14, connect_command: "C N0CALL-12", sys_required: true}
     # open node, no login
     N0CALL-9:  {type: xnet,   telnet_host: 192.0.2.30, telnet_port: 23, login_required: false, sys_required: false}
   ```
3. **Store credentials** (§2) — keyring preferred.
4. **Validate** (no MCP client needed):
   ```bash
   pr-digi-mcp test N0CALL-14 "L"          # read path
   pr-digi-mcp test N0CALL-14 "PORTS" --sys # write/sysop path (elevation)
   ```
5. **Confirm** it appears: restart the MCP client (or `pr-digi-mcp` process) and
   run `list_nodes`.

---

## 4. Offboard a node

> Or ask Claude Code: *"offboard PR digi <callsign>"* → the `offboard-pr-digi` skill.

1. **Check dependents:** if any `xnet_chained` node lists this node in `transit_via`,
   remove or rewire those first (a dangling chain fails to load).
2. **Remove** the node's block from `~/.config/pr-digi-mcp/nodes.yaml`.
3. **Delete credentials:**
   ```bash
   keyring del pr-digi-mcp "N0CALL-14_user"
   keyring del pr-digi-mcp "N0CALL-14_sys"
   ```
   and/or remove its block from `credentials.yaml`.
4. **Verify** it's gone: `list_nodes` no longer shows it; the config still loads
   (`pr-digi-mcp test <any-other-node> "L"` starts cleanly).
