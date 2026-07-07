---
name: offboard-pr-digi
description: Offboard (remove) a packet-radio digi node from the pr-digi-mcp server. Use when the operator wants to remove/deregister/offboard a PR digi node — deletes it from nodes.yaml, clears its stored credentials, checks for chained dependents, and verifies the config still loads.
---

# Offboard a PR digi node

Cleanly remove a node from `pr-digi-mcp`. Reference: `docs/onboarding-nodes.md` §4.

## 1. Identify the node
Confirm the exact callsign the operator wants to remove, and show its current
block from `~/.config/pr-digi-mcp/nodes.yaml`.

## 2. Check for dependents (important)
Search the config for chained nodes that transit through this one:
```bash
grep -n "transit_via: *<CALLSIGN>" ~/.config/pr-digi-mcp/nodes.yaml
```
If any exist, warn the operator: those chained nodes will fail to load once this
node is gone. Offer to remove/rewire them in the same pass.

## 3. Remove the node block
Delete the node's block from `nodes.yaml` (confirm the diff before writing).

## 4. Clear credentials
Remove the keyring entries (deleting a secret exposes nothing, so this is safe to run):
```bash
keyring del pr-digi-mcp "<CALLSIGN>_user"   # ignore "not found"
keyring del pr-digi-mcp "<CALLSIGN>_sys"    # ignore "not found"
```
Also remove the node's block from `~/.config/pr-digi-mcp/credentials.yaml` if it
was using the file fallback.

## 5. Verify
- Config still loads: `pr-digi-mcp test <some-other-node> "L"` starts without a
  config error (proves no dangling chain).
- The node is gone from `list_nodes` after the MCP client / process restarts.

## Guardrails
- Confirm before editing `nodes.yaml`.
- Never delete a node that is still a `transit_via` for another node without
  handling that dependency first.
