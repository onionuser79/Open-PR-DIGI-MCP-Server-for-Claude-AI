---
name: Bug report
about: Something doesn't work as expected
title: "[bug] "
labels: bug
---

**What happened**
A clear description of the bug.

**Node**
- Software / build: <!-- e.g. (X)Net V1.39, LinBPQ 6.0.25.x, BPQ32 Windows, PC/Flexnet 3.3g -->
- Type in `nodes.yaml`: <!-- xnet | bpq | linbpq | xnet_chained -->
- Connection mode: <!-- direct (no ssh_host) | via SSH jump host -->

**Steps to reproduce**
1. …

**Expected vs actual**
- Expected:
- Actual:

**Logs**
Run with `-v` and paste the relevant output (`pr-digi-mcp -v`, or `pr-digi-mcp test <node> "<cmd>" -v`).

```
<paste here>
```

**Environment**
- OS + version:
- Python version:
- pr-digi-mcp version / commit:

> ⚠️ **Redact secrets.** Never paste passwords, SYS/PASSWORD challenge replies,
> or anything you wouldn't publish. Callsigns/IPs are fine to mask too.
