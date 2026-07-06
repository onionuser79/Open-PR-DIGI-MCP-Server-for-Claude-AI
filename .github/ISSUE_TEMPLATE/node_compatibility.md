---
name: Node compatibility report
about: A node build behaves differently (prompt / challenge / command output) — help us support it
title: "[node] "
labels: node-compat
---

Use this when your (X)Net / PC-Flexnet / BPQ32 / LinBPQ build doesn't parse
cleanly — different login prompt, SYS/PASSWORD challenge shape, banner, or
command output. A transcript lets us extend the transports, parsers, and the
mock-server test to cover it (see CONTRIBUTING → Testing).

**Node software + version**
<!-- e.g. XNET V1.40, LinBPQ 6.0.24.x, BPQ32 6.0.25.x (Windows) -->

**What differs / what fails**
<!-- e.g. "login prompt is 'Callsign>' not 'login:'", "SYS challenge has 6 positions", "L output columns differ" -->

**Sanitised transcript**
Paste the raw session showing the issue — login flow, the `SYS`/`PASSWORD`
challenge line(s), and/or the `L` / `D` / `FL` / `NODES` output.

```
<paste here>
```

> ⚠️ **Sanitise before posting.** Mask passwords and challenge *replies*;
> masking callsigns/IPs is welcome too. The prompt/challenge *shape* and column
> layout are what we need — not the secret values.
