"""Credential lookup with macOS Keychain primary + YAML fallback.

Keychain layout (per DESIGN.md §10.8):
    service = "pr-digi-mcp"
    account = "<NODE>_user"  or  "<NODE>_sys"

Fallback path: ~/.config/pr-digi-mcp/credentials.yaml (0600), gitignored.

The keyring lookup runs in a daemon thread with a hard timeout. macOS will
block `SecItemCopyMatching` indefinitely if the calling binary isn't on the
item's ACL partition list (waiting for an invisible authorization dialog),
which wedges the entire MCP server. On timeout we treat the lookup as a
miss and fall through to YAML.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Literal

import keyring
import yaml

logger = logging.getLogger(__name__)

KIND = Literal["user", "sys"]
SERVICE = "pr-digi-mcp"
KEYRING_TIMEOUT_S = 2.0


def _yaml_fallback_path() -> Path:
    return Path.home() / ".config" / "pr-digi-mcp" / "credentials.yaml"


def _load_yaml_fallback() -> dict[str, dict[str, str]]:
    """Load the YAML credentials file if present; otherwise return empty dict."""
    path = _yaml_fallback_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("nodes", {})  # type: ignore[no-any-return]
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to read %s: %s", path, e)
        return {}


def _keyring_get_with_timeout(service: str, account: str, timeout_s: float) -> str | None:
    """Run `keyring.get_password` in a daemon thread; abandon it after `timeout_s`.

    Returns the password on success, None on miss or timeout. The thread is
    left running on timeout — it's blocked in a Mach IPC to `securityd` and
    can't be cancelled, but as a daemon it won't keep the interpreter alive.
    """
    result_q: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_q.put(("ok", keyring.get_password(service, account)))
        except Exception as e:  # noqa: BLE001
            result_q.put(("err", e))

    t = threading.Thread(
        target=worker, name=f"keyring-{account}", daemon=True
    )
    t.start()
    try:
        kind, value = result_q.get(timeout=timeout_s)
    except queue.Empty:
        logger.warning(
            "Keychain lookup for %s timed out after %.1fs — "
            "binary likely not on the item ACL partition list; "
            "falling back to YAML",
            account,
            timeout_s,
        )
        return None
    if kind == "err":
        logger.debug("Keychain lookup for %s failed: %s", account, value)
        return None
    return value  # type: ignore[return-value]


def get_password(node: str, kind: KIND) -> str:
    """Look up a password for `node`'s `kind` (user|sys).

    Order:
        1. macOS Keychain (service=pr-digi-mcp, account=<node>_<kind>)
           — bounded by KEYRING_TIMEOUT_S so a hung ACL prompt can't wedge
             the caller; a timeout is treated as a miss
        2. YAML fallback at ~/.config/pr-digi-mcp/credentials.yaml

    Raises:
        LookupError: if neither source has the credential
    """
    account = f"{node}_{kind}"

    pw = _keyring_get_with_timeout(SERVICE, account, KEYRING_TIMEOUT_S)
    if pw:
        return pw

    # 2. YAML fallback
    fallback = _load_yaml_fallback()
    node_creds = fallback.get(node, {})
    field = "user_pwd" if kind == "user" else "sys_pwd"
    pw = node_creds.get(field)
    if pw and pw != "REPLACE_ME":
        return str(pw)

    raise LookupError(
        f"No {kind} password for {node}. "
        f"Set keychain entry (service='{SERVICE}', account='{account}') "
        f"or populate {_yaml_fallback_path()}"
    )
