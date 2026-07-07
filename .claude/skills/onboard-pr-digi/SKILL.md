---
name: onboard-pr-digi
description: Onboard (add) a packet-radio digi node to the pr-digi-mcp server so it can be managed via MCP. Use when the operator wants to add/register/onboard a new PR digi node — (X)Net, PC/Flexnet, BPQ32/LinBPQ — including direct telnet, SSH-jump, or chained AX.25 (multi-hop) access. Handles nodes.yaml + credential storage + validation.
---

# Onboard a PR digi node

Drive the operator through adding a node to `pr-digi-mcp`. Reference:
`docs/onboarding-nodes.md`. **Never put passwords in `nodes.yaml`, in the repo,
or in the chat transcript** — credentials go in the OS keyring (preferred) or a
gitignored `credentials.yaml`.

## 1. Gather the node's details
Ask the operator (one question at a time if unclear):
- **Callsign** (e.g. `N0CALL-7`) and **node software** → `type`:
  `xnet` ((X)Net / PC-Flexnet) · `linbpq` · `bpq` (Windows) · `xnet_chained` (AX.25-only).
- **Access model** (see `docs/onboarding-nodes.md` §1):
  - **Direct telnet** → `telnet_host`, `telnet_port`.
  - **Via SSH jump** → also `ssh_host` (must be an alias in `~/.ssh/config`);
    `telnet_host` is the address *as seen from the jump host*.
  - **Chained AX.25** (the only way to reach a **PC/Flexnet** node — it has no
    telnet) → `transit_via` = the first-hop node, which may be an **(X)Net OR a
    BPQ/LinBPQ** node (any AX.25-capable node the MCP can telnet into; or another
    chained node for multi-hop) + `connect_command` (`C <CALLSIGN>`). No `user`.
    Note: PC/Flexnet's commands differ from (X)Net — it's driven via `xnet_sys_command`.
- **Login**: a `user` (login callsign/name) — or `login_required: false` for an
  open node with no login prompt.
- **`sys_required`**: `true` if the node needs SYS/PASSWORD for write tools.

## 2. Locate / create the config
- Config lives at `~/.config/pr-digi-mcp/nodes.yaml`. If it doesn't exist, create
  it from `config/nodes.example.yaml` (keep only a `nodes:` mapping).
- For a **chained** node, confirm `transit_via` already exists in the file (or is
  being added in the same pass) — a dangling chain fails to load.

## 3. Add the node block
Show the exact YAML you will add and get the operator's OK before writing. Shapes:
```yaml
  N0CALL-7:   {type: xnet, telnet_host: 192.0.2.10, telnet_port: 23, user: me, sys_required: true}
  N0CALL-14:  {type: xnet, ssh_host: my-gw, telnet_host: 44.0.0.2, telnet_port: 23, user: me, sys_required: true}
  N0CALL-12:  {type: xnet_chained, transit_via: N0CALL-14, connect_command: "C N0CALL-12", sys_required: true}
  N0CALL-9:   {type: xnet, telnet_host: 192.0.2.30, telnet_port: 23, login_required: false, sys_required: false}
```

## 4. Store credentials (operator runs these — passwords never touch the chat)
Preferred (OS keyring). Have the operator run, via the `!` shell prefix so the
prompt stays in their terminal:
```
! keyring set pr-digi-mcp "<CALLSIGN>_user"     # login pwd (skip for open/chained nodes)
! keyring set pr-digi-mcp "<CALLSIGN>_sys"      # only if sys_required
```
Chained nodes need only `_sys`; open nodes need neither. If the operator prefers
the file fallback, tell them to edit `~/.config/pr-digi-mcp/credentials.yaml`
(mode 0600) themselves — do not write real secrets on their behalf.

## 5. Validate
```bash
pr-digi-mcp test <CALLSIGN> "L"            # read path
pr-digi-mcp test <CALLSIGN> "PORTS" --sys  # write/sysop path (if sys_required)
```
Confirm you get sensible output (a link table, a prompt). For chained/multi-hop,
expect a short delay per hop.

## 6. Confirm & finish
- Have the operator restart their MCP client (or the `pr-digi-mcp` process) and run
  `list_nodes` — the new node should appear.
- Summarise what was added and where creds are stored. Do **not** echo secrets.

## Guardrails
- Confirm before editing `nodes.yaml`.
- Never write passwords into `nodes.yaml`, `credentials.example.yaml`, or the repo.
- Remind the operator to only onboard nodes they are licensed/authorised to operate.
