# Supported nodes & tool catalog

## Supported PR digis (today)

| `type` | Node software | Reached by | CLI family | Notes |
|--------|---------------|-----------|-----------|-------|
| `xnet` | **(X)Net** (e.g. V1.39) | telnet (direct or SSH-jump) | (X)Net single-letter CLI (`L`/`D`/`MH`/`U`/`INFO`) + `SYS` positional challenge | **The only type that has the full structured `xnet_*` write toolset.** |
| `linbpq` | **LinBPQ** (Linux BPQ32) | telnet (direct or SSH-jump) | BPQ console + `PASSWORD` sysop | Adds the FlexNet `FL`/`D` tools |
| `bpq` | **BPQ32** (Windows) | telnet (direct or SSH-jump) | BPQ console + `PASSWORD` sysop | LinBPQ minus FlexNet |
| `xnet_chained` | any AX.25-only node — **notably PC/Flexnet** | **AX.25 `C <call>` from a transit node** (single/multi-hop) | the *target's* own CLI (e.g. PC/Flexnet) | Driven by generic reads + `xnet_sys_command`; **no** structured writes. First hop may be (X)Net **or** BPQ/LinBPQ. |

### (X)Net ≠ PC/Flexnet — read this

**PC/Flexnet is not a `type: xnet` node.** PC/Flexnet has **no telnet interface**,
so it can never be reached directly — it is **always** configured as
`xnet_chained` and reached over **AX.25 (`C <call>`)** through a transit node.
That first hop can be **any AX.25-capable node** — an (X)Net node *or* a
BPQ32/LinBPQ node (or a further chained hop for multi-hop).

Its **command set differs** from (X)Net V1.39. So a PC/Flexnet node is driven
with **its own commands via `xnet_sys_command`** (verbatim), *not* the structured
`xnet_*` tools (those target (X)Net V1.39 only). The single-letter read wrappers
(`xnet_links`=`L`, `xnet_destinations`=`D`, …) are *accepted* on a chained node but
send the **(X)Net** letters — treat their output as best-effort on PC/Flexnet and
prefer `xnet_sys_command` with PC/Flexnet's native syntax.

**Tool applicability rules**
- `xnet_*` **read** tools accept any (X)Net-family node incl. `xnet_chained`, but
  send **(X)Net** commands — reliable on `xnet` ((X)Net V1.39), best-effort on a
  chained PC/Flexnet target.
- `xnet_*` **structured write** tools require a **direct `xnet` ((X)Net V1.39)** node
  — **not** PC/Flexnet. Drive PC/Flexnet with `xnet_sys_command`.
- `bpq_*` tools require `bpq`/`linbpq`; FlexNet tools (`bpq_flexnet_*`) require `linbpq`.
- Aggregation tools (`network_topology`, `find_callsign`) sweep **all** configured nodes.

### Tools usable on a PC/Flexnet node (`xnet_chained`)
A chained PC/Flexnet node is managed with **exactly** these — everything else is
(X)Net-V1.39-only:

| Tool | Role on PC/Flexnet |
|------|--------------------|
| `xnet_sys_command` | **Primary driver** — run PC/Flexnet's *own* commands verbatim (after SYS elevation); dangerous ones gated by `confirm` |
| `xnet_run_command` | Run a verbatim read command (no elevation) |
| `xnet_links` / `xnet_l_star` / `xnet_destinations` / `xnet_mh` / `xnet_users` / `xnet_info` | Generic read wrappers — *accepted*, but they send the **(X)Net** letters; output is best-effort on PC/Flexnet |
| `list_nodes` · `network_topology` · `find_callsign` | Inventory / aggregation (best-effort) |

**Not applicable to PC/Flexnet:** the structured `xnet_*` routing / IP / ARP / file /
parameter / dangerous tools, and all `bpq_*` tools.

#### PC/Flexnet commands (and how they differ from (X)Net)

Source: *RMNC/FlexNet & PC/FlexNet Sysop Manual* (Günter Jost, DK7WJ) —
<https://archive.org/details/eastnet-flex> §5. PC/Flexnet's console is **not**
(X)Net's. Drive reads with `xnet_run_command` and sysop actions with
`xnet_sys_command`.

**User (read) commands** (§5.1): `C <call>` connect · `D [*] [call]` **destination
table / path** (FlexNet's signature routing view) · `F <call>` find · `H` help ·
`I` info · `L` interlink (link) info · `MH [...]` heard list · `MY` show mycall/SSID ·
`P` parameters + statistics · `U [*]` user table · `Q` quit.

**Sysop commands** (§5.2 — enter sysop mode with **`SY`**, which answers the same
5-number positional challenge as (X)Net's `SYS`):

| Command | Action |
|---------|--------|
| `SY` | Sysop authorization (positional challenge) |
| `L <ch> <call>` | Route `<call>` to channel `<ch>` |
| `L <viacall> <call>` | Route `<call>` **via** `<viacall>` |
| `L - <call>` | Delete link/route `<call>` |
| `MY <call> [ssid1 ssid2]` | Set mycall + SSID range |
| `MO <ch> <mode>` | Set port `<ch>` mode / baud |
| `PS <ssid> <ch>` | Map SSID `<ssid>` → port `<ch>` |
| `PT <x>` | Node timeout, minutes *(OCR-derived mnemonic)* |
| `M <call>` | Assign local BBS |
| `K <QSO_no>` | Kill (disconnect) a QSO by number |
| `CAL <ch> [min]` | Send a calibration signal (RMNC hardware) |
| `IO <bit> 0\|1` | Set a hardware output bit (RMNC) |
| `TR <ch>` | Monitor/trace a port (solomaster only) |
| `W <A/B/C/H/I/L/S>` | Write text files (news / beacon / CTEXT / help / info / local / setsearch); end with `/ex` |
| `RESET` / `RESTART` | Cold / warm reboot |

**Key differences vs (X)Net V1.39** — this is why the structured `xnet_*` tools do
**not** apply to PC/Flexnet:

| Function | PC/Flexnet | (X)Net V1.39 (structured `xnet_*` tools) |
|----------|-----------|------------------------------------------|
| Sysop-auth keyword | **`SY`** | **`SYS`** |
| Routing | `L <ch> <call>` / `L <viacall> <call>` / `L - <call>` | `ROUTER {bc\|flexnet\|local} add/del` |
| Disconnect | `K <QSO_no>` | `DISCONNECT` |
| Port setup | `MO` (mode/baud), `PS` (SSID→port); fixed via MRMNC/EPROM | `ATTACH`/`DETACH` + port params |
| Node timeout | `PT <x>` | parameter set |
| TCP/IP admin | **none** — FlexNet here is an AX.25/NetROM-FlexNet router | `IPROUTE`/`ARP`/`MYIP`/`SUBNET`/`IPSTOP`/`NETSTAT`/`PING` + nameserver |
| Services / procs / logs / files | `W` in-node text editor only | `SERVICE`/`PROCESSES`/`STATISTICS`/`LOG`, filesystem ops |
| Hardware I/O / calibration | `CAL`, `IO` (RMNC hardware) | — |

> **`SY` vs `SYS`:** the MCP's SYS elevation sends `SYS`; PC/Flexnet's documented
> keyword is `SY`. FlexNet parsers usually match on the `SY` prefix (so `SYS` works),
> but a per-node sysop-auth keyword is a candidate robustness enhancement — if your
> PC/Flexnet build rejects `SYS`, flag it (see PLAN.md Tier-3).

**Gate legend:** 🔒 = refuses to run unless `confirm=true` (human-approved);
⚠ = escape hatch, danger-classified per command.

---

## The 81 tools

### Discovery / aggregation (3)
| Tool | Action |
|------|--------|
| `list_nodes` | Enumerate configured nodes (callsign, type, access path, sys flag) |
| `network_topology` | Merge every node's neighbour/link table into one structured map |
| `find_callsign` | Search all nodes' nodes/routes/links for a callsign; report where it's reachable |

### Generic (1)
| Tool | Action |
|------|--------|
| `xnet_run_command` | Run an arbitrary **read** command on a node; return raw text |

### (X)Net — read / diagnostics (13)
| Tool | Command | Action |
|------|---------|--------|
| `xnet_links` | `L` | Current AX.25 links |
| `xnet_l_star` | `L *` | Full routing/destination dump |
| `xnet_destinations` | `D [filter]` | Destination/route table |
| `xnet_mh` | `MH` | Heard list |
| `xnet_users` | `U` | Active users |
| `xnet_info` | `INFO` | Version / identity banner |
| `xnet_netstat` | `NETSTAT` | TCP/IP status |
| `xnet_processes` | — | Process list |
| `xnet_statistics` | — | Counters |
| `xnet_log` | — | Node log |
| `xnet_ping` | `PING` | ICMP/AX.25 reachability |
| `xnet_monitor` | `MONITOR` (bounded capture) | Live frame capture for N seconds |
| `xnet_ipdump` | `IPDUMP` (bounded capture) | IP packet capture for N seconds |

> **The structured (X)Net groups below** (routing, IP/ARP, config, files,
> dangerous) target a **direct `xnet` ((X)Net V1.39)** node only — they do **not**
> apply to PC/Flexnet (`xnet_chained`), which is driven via `xnet_sys_command`.

### (X)Net — routing (4)
| Tool | Action | Gate |
|------|--------|------|
| `xnet_router_list` | Show a router table (bc / flexnet / local) | |
| `xnet_router_add` | Add a router entry | |
| `xnet_router_del` | Delete a router entry | 🔒 |
| `xnet_disconnect` | Force-disconnect a link | 🔒 |

### (X)Net — IP / ARP / config (10)
| Tool | Action | Gate |
|------|--------|------|
| `xnet_iproute_list` / `xnet_iproute_add` / `xnet_iproute_del` | View / add / delete IP routes | del: (state change) |
| `xnet_arp_list` / `xnet_arp_add` / `xnet_arp_del` | View / add / delete ARP entries | |
| `xnet_set_nameserver` | Set the DNS nameserver | |
| `xnet_set_param` | Set a node parameter | |
| `xnet_port_param` | Set a per-port parameter (runtime) | |
| `xnet_service` | Enable/disable a service | |

### (X)Net — files (4)
| Tool | Action |
|------|--------|
| `xnet_dir` | List files |
| `xnet_read_file` | Read a file |
| `xnet_copy_file` | Copy a file |
| `xnet_rename_file` | Rename a file |

### (X)Net — dangerous (9, all 🔒)
| Tool | Action |
|------|--------|
| `xnet_attach` / `xnet_detach` | Attach / detach a port |
| `xnet_set_identity` | Change the node callsign/identity |
| `xnet_set_ip` / `xnet_set_subnet` | Change the node IP / subnet |
| `xnet_set_time` | Set the node clock |
| `xnet_remove_file` | Delete a file |
| `xnet_ipstop` | Stop IP |
| `xnet_reset` | Reset the node |

### (X)Net — escape hatch (1)
| Tool | Action | Gate |
|------|--------|------|
| `xnet_sys_command` | Run a verbatim SYS-mode command (also the way to drive chained nodes) | ⚠ |

### BPQ32 / LinBPQ — read / diagnostics (14)
| Tool | Command | Action |
|------|---------|--------|
| `bpq_version` | `VERSION` | Build/version |
| `bpq_stats` | `STATS` | System/port counters |
| `bpq_listen` | `LISTEN` | Listen state |
| `bpq_validcall` | `VALIDCALL` | Callsign validation |
| `bpq_iproute` | `IPROUTE` | IP routes |
| `bpq_arp` | `ARP` | ARP table |
| `bpq_nat` | `NAT` | NAT table |
| `bpq_ping` | `PING` | Reachability |
| `bpq_telstatus` | `TELSTATUS` | Telnet server status |
| `bpq_axresolver` | `AXRESOLVER` | AXIP resolver table |
| `bpq_axmheard` | `AXMHEARD <port>` | AXIP heard list for a port |
| `bpq_ports` | `PORTS` | Port inventory |
| `bpq_routes` | `ROUTES` | L2 neighbour routes |
| `bpq_nodes` | `NODES` | NetROM node table |

### BPQ FlexNet — LinBPQ only (2)
| Tool | Command | Action |
|------|---------|--------|
| `bpq_flexnet_links` | `FL` | FlexNet links |
| `bpq_flexnet_destinations` | `D [query]` | FlexNet destinations (+ per-callsign query) |

### BPQ — routing (3)
| Tool | Action | Gate |
|------|--------|------|
| `bpq_node_add` | Add a NetROM node | |
| `bpq_node_del` | Delete a NetROM node | 🔒 |
| `bpq_route_set` | Set a route (quality / locked) | |

### BPQ — port / CMS (6)
| Tool | Action | Gate |
|------|--------|------|
| `bpq_startport` / `bpq_stopport` | Start / stop a port | stop: 🔒 |
| `bpq_startcms` / `bpq_stopcms` | Start / stop the CMS (Winlink) link | stop: 🔒 |
| `bpq_kiss` | Send a KISS command to a port | 🔒 |
| `bpq_telreconfig` | Reconfigure telnet users/port | 🔒 |

### BPQ — persistence (4)
| Tool | Action |
|------|--------|
| `bpq_savemh` | Save the MH list |
| `bpq_savenodes` | Save the nodes table |
| `bpq_sendnodes` | Broadcast a nodes update |
| `bpq_getportctext` | Re-read port CTEXT files |

### BPQ — parameters (2)
| Tool | Action |
|------|--------|
| `bpq_get_param` | Read an allowlisted parameter |
| `bpq_set_param` | Set an allowlisted parameter |

### BPQ — lifecycle (4)
| Tool | Action | Gate |
|------|--------|------|
| `bpq_findbuffs` | Buffer diagnostics | |
| `bpq_wl2ksysop` | Winlink sysop view/set | 🔒 on SET |
| `bpq_reconfig` | Reload config | 🔒 |
| `bpq_reboot` | Reboot the node | 🔒 |

### BPQ — escape hatch (1)
| Tool | Action | Gate |
|------|--------|------|
| `bpq_sysop_command` | Run a verbatim BPQ console command | ⚠ |

---

*Count: 3 + 1 + 13 + 4 + 10 + 4 + 9 + 1 (X)Net-side + 14 + 2 + 3 + 6 + 4 + 2 + 4 + 1 BPQ-side = **81**.
Was 79 before the two aggregation tools were added.*
