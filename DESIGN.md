# Design — Open PR-DIGI MCP Server

Architecture and design notes for the station-agnostic MCP server that exposes
packet-radio digipeater nodes — **(X)Net**, **PC/Flexnet**, **BPQ32 / LinBPQ** —
as MCP tools. This document is generic; the **IW2OHX** station is the reference
deployment referred to in a few examples.

---

## 1. Goal

Replace the manual sysop loop — *SSH to a host → telnet to a node's port → log
in → run `L` / `D` / `FL` / `NODES` / `ROUTES` → parse by eye → repeat per node*
— with one typed MCP tool per operation, so an LLM operator can query and manage
a whole packet network from a single conversation. The server holds **no station
knowledge in code**: the node inventory and secrets are entirely configuration.

---

## 2. Architecture

### 2.1 Stack
- **Language:** Python 3.10+ (`asyncio`).
- **MCP:** [`mcp[cli]`](https://pypi.org/project/mcp/) (FastMCP), served over **stdio**.
- **SSH:** `asyncssh` (optional per-node jump-host tunnel).
- **Config:** `pyyaml`. **Secrets:** `keyring` (+ YAML fallback).

### 2.2 Module layout (`src/pr_digi_mcp/`)
| Module | Responsibility |
|--------|----------------|
| `config.py` | Load & validate `nodes.yaml` → `NodeConfig` objects |
| `credentials.py` | Resolve per-node passwords (keyring → YAML fallback) |
| `transports/xnet.py` | Base transport: (optional SSH) telnet, login, read, `SYS` elevation |
| `transports/bpq.py` | BPQ32/LinBPQ transport: `PASSWORD` elevation |
| `transports/chained.py` | AX.25 chained transport: outer → `C <inner>` → inner |
| `transports/family.py` | Recognise the node family (xnet/bpq/pcf) from MOTD or `V` |
| `transports/__init__.py` | `open_transport()` + `open_dynamic_chain()` factories |
| `discovery.py` | On-demand route discovery across `D`/`N` tables (ranked candidates) |
| `commands.py` | Command syntax tables + callsign validation |
| `parsers.py` | Tolerant parsers: raw command text → typed records (JSON) |
| `safety.py` | Dangerous-command classifier (the confirmation gate) |
| `server.py` | MCP tool definitions + CLI (`serve` / `test`) |

### 2.3 Connection model
Each tool call opens a transport, runs, and tears down (`async with`) — a short
telnet session per operation rather than a long-lived pool. Sessions are
serialised internally by an `asyncio.Lock` so interleaved reads can't corrupt
one another.

---

## 3. Node model & configuration

Nodes are declared in `nodes.yaml` (searched at `~/.config/pr-digi-mcp/nodes.yaml`,
then `./config/nodes.yaml`, then the packaged example). Each entry is a
`NodeConfig`:

| Field | Applies to | Notes |
|-------|-----------|-------|
| `type` | all | `xnet` · `bpq` · `linbpq` · `xnet_chained` |
| `telnet_host`, `telnet_port` | direct-access | node endpoint |
| `user` | direct-access | login callsign/name (required unless `login_required: false`) |
| `login_required` | direct-access | default **true**; `false` = open node with no login prompt |
| `sys_command` | all | sysop-auth keyword: `SYS` (default, (X)Net) / `SY` (PC/Flexnet); BPQ uses `PASSWORD` |
| `ssh_host` | direct-access | **optional** SSH jump-host alias (see §4) |
| `transit_via`, `connect_command` | `xnet_chained` | transit node (a direct node **or** another chained node → multi-hop) + its `C …` command |
| `sys_required` | all | whether write tools need SYS/PASSWORD elevation |
| `description` | all | free text |

Validation rejects: unknown types, missing required fields, a chained node whose
`transit_via` is unknown or itself chained (multi-hop chains are not supported).

---

## 4. Connectivity: direct vs SSH jump

`ssh_host` decides how the telnet channel is opened — implemented once in
`XnetTransport.connect()`:

- **`ssh_host` set** → `asyncssh.connect(ssh_host)` then `open_connection(telnet_host, port)`
  tunnels the telnet TCP channel over SSH. Use when nodes are only reachable
  from a gateway box. SSH auth is **the operator's own** setup (keys/agent/
  `~/.ssh/config`).
- **`ssh_host` empty** → `asyncio.open_connection(telnet_host, port)` connects
  directly. Use for nodes on the LAN or reachable over HAMNET/AMPRNet/Internet.

The two stream types (`asyncssh` vs `asyncio`) share the `read/write/drain/
close/is_closing` surface, so the rest of the transport is identical either way.
`BpqTransport` inherits `connect()`; `Ax25ChainedTransport` calls `super().connect()`
for the outer node — so both connection modes work for every node type.

---

## 5. Transports

### 5.1 `XnetTransport` (base)
Lifecycle: `connect()` (open + `_login()`), `run_command()`, `capture()`,
`elevate_sys()`, `disconnect()` (`BYE` + close).

- **Login:** wait for a login prompt (`login|user|name|callsign` + `:`/`>`), send
  `user`; wait for a password prompt, send the **user password**; drain the
  banner. A login-failure marker raises.
- **Reading — idle heuristic:** `run_command()` returns once the stream has been
  silent for `idle_ms` (after the first byte), bounded by `max_wait_s`. Bursty
  nodes → raise `idle_ms`. `capture()` instead reads for a fixed window (for
  streaming commands like `MOnitor`/`IPDump`) so intermittent frames aren't
  truncated.
- **Wire handling:** telnet IAC negotiation sequences are stripped; bytes are
  decoded as latin-1 (1:1, lossless) — the LLM consumes raw text.
- **SYS elevation:** send `SYS`; the node replies with a **positional challenge**
  (`NODE>  p1 p2 p3 …` — 1-indexed positions); the client replies with those
  characters of the **sys password**, concatenated, no spaces. Rejections are
  detected heuristically; the whole password is never transmitted.

### 5.2 `BpqTransport`
Inherits IO/login. Elevation sends `PASSWORD`, then either:
- `Ok` — the session is already privileged (e.g. local to the BPQ host), or
- a **5-number positional challenge** answered from the sys password.

### 5.3 `Ax25ChainedTransport`
For nodes reachable only over RF/AX.25 via one or more transit hops — notably
**PC/Flexnet**, which has no telnet interface and a command set distinct from
(X)Net V1.39 (drive it via `xnet_sys_command`, not the structured (X)Net tools).
The base/first-hop node may be any direct node — **(X)Net or BPQ/LinBPQ**.
`config.resolve_chain()` walks `transit_via` to a **base direct node** and the
ordered list of `C …` commands (single-hop if `transit_via` is a direct node,
multi-hop if it points at another chained node — cycles/dead-ends are rejected at
load time). `connect()` logs into the base, then issues each `C …` command in
order, waiting for the `*** CONNECTED to …` banner at each hop (failure markers
raise). The target has **no separate login** — the AX.25 SABM carries the base's
user identity through. SYS elevation targets the **target** node's password.
Teardown sends `BYE` (innermost) then lets the base class `BYE`/close; intermediate
hops fall back on their inactivity timeout.

### 5.4 On-demand route discovery (`discovery.py` + `remote_run`)
Statically-chained nodes above must be pre-declared. `remote_run` removes that
requirement: it reaches a target that is **not** in `nodes.yaml` by discovering a
route at call time (nothing pre-scanned, nothing persisted).

`discovery.discover_routes(target, all_nodes, run_user)`:
1. **Consult** every configured console node (`xnet`/`bpq`/`linbpq`) concurrently,
   reading only two tables — FlexNet destinations `D <call>` (cost) and NetROM
   route detail `N <call>` (quality + hops). Link tables (`L`) are deliberately
   **not** used. A bare-token target is first resolved from the NODES alias map.
2. **Rank** all matches into ONE list by `_rank_key = (metric, hops)` ascending —
   lower cost/metric then fewer hops wins. FlexNet cost is used directly; NetROM
   quality is inverted onto the same lower-is-better axis. `_rank_key` /
   `RouteCandidate.sort_metric()` is the single, documented, tunable place for the
   ranking scale (flip there if a live capture shows a different preference).

`remote_run` then connects best-first via `open_dynamic_chain()` (which synthesises
an ephemeral `xnet_chained` config and reuses `Ax25ChainedTransport`), **falling
back** to the next candidate on connect failure. On success it calls
`transport.probe_family()` — `detect_family()` on the captured MOTD, falling back
to the `V` version command — then runs the (user-mode) command verbatim in that
family's command set and attaches a structured parse when one exists for the verb.

---

## 6. Authentication & credentials

Up to three layers per node (see the README/summary for the operator view):

1. **Transport (optional):** SSH to `ssh_host` via the operator's SSH keys/agent.
2. **Node login:** `user` + user-password over telnet (chained nodes inherit the
   transit node's login).
3. **Sysop elevation:** `SYS` positional challenge ((X)Net/PCF) or `PASSWORD`
   (`Ok`/5-number) (BPQ), answered from the sys-password. Required only for
   write/sysop tools on nodes with `sys_required: true`.

**Credential resolution (`credentials.py`):**
1. **OS keyring** (cross-platform via `keyring`): `service="pr-digi-mcp"`,
   `account="<NODE>_user"` / `"<NODE>_sys"`. Bounded by a 2 s timeout so a hung
   keyring/ACL prompt cannot wedge the server; a timeout is treated as a miss.
2. **YAML fallback:** `~/.config/pr-digi-mcp/credentials.yaml` (mode 0600,
   gitignored), fields `user_pwd` / `sys_pwd` (`REPLACE_ME` = unset).

Passwords are never stored in `nodes.yaml` and never committed.

> **RF-plaintext caveat.** A positional SYS challenge answered over an RF/AX.25
> hop (chained nodes) exposes selected password characters on the air over time.
> Give chained/RF nodes a **sys password distinct** from any node reachable only
> over encrypted paths, and treat those secrets as lower-trust.

---

## 7. Authorization / safety model

Authentication proves *who*; this gate controls *what*. `safety.py` classifies
each sysop command:

- **Read-only** (`L`, `D`, `NODES`, `ROUTES`, `PORTS`, stats, heard, IP/ARP, …) —
  run freely.
- **Dangerous** — anything that changes persistent/live state or takes a node
  offline (`RESET`, `REBOOT`, `RECONFIG`, `STOPPORT`, `KISS`, param writes, and
  `DEL`/`KILL`/`FLUSH`-class commands). These **refuse to run** unless the tool
  is called with `confirm=True`, which the LLM may set **only after the human
  operator explicitly approves**.
- **Escape hatches** (`bpq_sysop_command`, `xnet_sys_command`) run arbitrary
  console commands and are classified by the same dialect-aware rules, so a
  dangerous command smuggled through them is still gated.

---

## 8. Tool surface

Grouped in `server.py` (exact set evolves — see the tool list at runtime):

- **Diagnostics (read-only):** links, destinations/routes, FlexNet links &
  destinations (LinBPQ), heard lists, node/route tables, ports, stats, IP/ARP,
  bounded `MOnitor`/`IPDump` captures.
- **Management (gated):** parameter get/set, node/route add-del, link reset,
  port & CMS control, persistence (`SAVEMH`/`SAVENODES`/`SENDNODES`), lifecycle.
- **Meta:** `list_nodes` (from config), per-node version/identity.
- **Aggregation (cross-node):** `network_topology` (merge every node's
  neighbour/link table) and `find_callsign` (which nodes reference a callsign,
  and how) — both parse output via `parsers.py` and capture per-node failures
  inline rather than aborting the sweep.

Tool parameter descriptions are generic ("as configured in nodes.yaml") — no
station is baked into the schema.

---

## 9. Security considerations

- **Local trust boundary (default).** Over stdio the server has **no client-side
  authentication** — whoever can launch it inherits access to every configured
  node's credentials. This suits a single-operator, local setup.
- **Authenticated remote access (opt-in).** `pr-digi-mcp serve-http` serves the MCP
  over **Streamable HTTP** behind a **bearer-token** ASGI gate (`http_auth.py`),
  loopback by default, refusing a non-loopback bind without TLS. Tokens come from
  `PR_DIGI_MCP_HTTP_TOKENS` / keyring. All tokens currently grant full access —
  **per-user/per-node scoping and OAuth remain future work**. See
  [`docs/remote-access.md`](docs/remote-access.md). Never expose the stdio port or
  an untokenised/cleartext HTTP endpoint off-host.
- **Secrets** live in the OS keyring or a gitignored, 0600 YAML file — never in
  the repo or `nodes.yaml`.
- **Authorization:** the confirm-gate keeps state-changing commands behind
  explicit human approval.
- **Operate only nodes you are licensed/authorised to operate.**

---

## 10. Extending

- **New node type / build:** add it to `NodeType` + `config.py` validation, and a
  transport (subclass `XnetTransport` if it's telnet + a login/elevation variant),
  and wire it into `open_transport()`. Register tools in `server.py`.
- **New tool:** add the function in `server.py`; if it can change state, ensure
  `safety.py` classifies it and it takes a `confirm` flag.
- **Different prompt / challenge shapes:** the login/SYS/PASSWORD regexes live in
  the transports; extend them and add a mock-server case (see §11).

---

## 11. Testing

- **Unit tests** cover config loading, callsign/command validation, the
  challenge-response math, IAC stripping, and the safety classifier — no network.
- **Integration** (`tests/test_integration_mock.py`): an in-process asyncio TCP
  server speaks a minimal (X)Net/BPQ protocol (login → `SYS`/`PASSWORD` challenge
  → command → `BYE`); the transports drive it over the **direct** path, so
  connect → login → elevate → command → disconnect is exercised end-to-end with
  no hardware. This is the substitute for testing against a second physical
  station — please extend the mock with real (sanitised) transcripts when a node
  build behaves differently.
- **CI** runs `ruff` + `mypy src` + `pytest` on Python 3.10–3.13.

---

## 12. Reference deployment

The project was built for the **IW2OHX** station (Bollate, IT): (X)Net nodes on
HAMNET reached through an SSH gateway, LinBPQ instances on the same Pi, a Windows
BPQ32 hub, a PC/Flexnet node reachable only by chained AX.25, and a partner club
node. It exercises every transport and both connection modes — a useful worked
example when writing your own `nodes.yaml`.
