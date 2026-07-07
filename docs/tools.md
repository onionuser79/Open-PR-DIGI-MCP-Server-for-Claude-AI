# Supported nodes & tool catalog

## Supported PR digis (today)

| `type` | Node software | CLI family | Notes |
|--------|---------------|-----------|-------|
| `xnet` | **(X)Net** (e.g. V1.39) and **PC/Flexnet**-family telnet nodes | single-letter (`L`/`D`/`MH`/`U`/`INFO`) + `SYS` positional challenge | Target of the structured `xnet_*` **write** tools |
| `linbpq` | **LinBPQ** (Linux BPQ32) | BPQ console + `PASSWORD` sysop | Adds the FlexNet `FL`/`D` tools (linbpq-flexnet builds) |
| `bpq` | **BPQ32** (Windows) | BPQ console + `PASSWORD` sysop | Same as LinBPQ minus FlexNet |
| `xnet_chained` | Any (X)Net/PC-Flexnet node reachable **only over AX.25** | (X)Net/PCF | Reached by `C <call>` from a transit node (single- or multi-hop). Generic read tools + the `xnet_sys_command` escape hatch apply; structured writes do not. |

**Tool applicability rules**
- `xnet_*` read tools work on any (X)Net-family node (`xnet`, `xnet_chained`).
- `xnet_*` **structured write** tools require a **direct** `xnet` node (chained nodes
  use `xnet_sys_command`).
- `bpq_*` tools require `bpq`/`linbpq`; FlexNet tools (`bpq_flexnet_*`) require `linbpq`.
- Aggregation tools (`network_topology`, `find_callsign`) sweep **all** configured nodes.

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
