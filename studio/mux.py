"""Terminal multiplexer abstraction -- supports tmux and zellij.

Selection via STUDIO_MUX env var: "tmux" (default) or "zellij".
"""

import atexit
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_mux = os.environ.get("STUDIO_MUX", "tmux")
SESSION = "studio"
PANE_MAP_FILE = "/tmp/studio-zellij-panes.json"


# P2: Zellij temp file cleanup on exit
def _cleanup_zellij_temp():
    if _mux == "zellij" and os.path.exists(PANE_MAP_FILE):
        try:
            os.remove(PANE_MAP_FILE)
        except OSError:
            pass


atexit.register(_cleanup_zellij_temp)


# ── Shared helpers ─────────────────────────────────────

def _run(cmd: list[str], timeout: int = 5) -> str:
    """Run a command and return stdout. Empty string on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 and result.stderr:
            # P1 Fix 7: Log mux failures instead of silent swallow
            logger.debug("mux command %s failed (rc=%d): %s", cmd[0], result.returncode, result.stderr.strip())
        return result.stdout.strip() if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        logger.warning("mux command timed out: %s", " ".join(cmd))
        return ""
    except FileNotFoundError:
        logger.warning("mux binary not found: %s", cmd[0])
        return ""
    except OSError as e:
        logger.warning("mux command error: %s", e)
        return ""


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


# ── tmux backend ───────────────────────────────────────

def _tmux_list_panes() -> set[str]:
    out = _run(["tmux", "list-windows", "-t", SESSION, "-F", "#{window_name}"])
    return set(out.split("\n")) if out else set()


def _tmux_capture_pane(agent_id: str) -> str:
    return _run(["tmux", "capture-pane", "-t", f"{SESSION}:{agent_id}", "-p"])


def _tmux_send_keys(agent_id: str, text: str):
    _run(["tmux", "send-keys", "-t", f"{SESSION}:{agent_id}", "-l", text])


def _tmux_send_enter(agent_id: str):
    _run(["tmux", "send-keys", "-t", f"{SESSION}:{agent_id}", "Enter"])


# ── zellij backend ─────────────────────────────────────

def _zellij_load_pane_map() -> dict[str, str]:
    """Load agent_id -> pane_id mapping from file."""
    try:
        with open(PANE_MAP_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _zellij_list_panes() -> set[str]:
    pane_map = _zellij_load_pane_map()
    if not pane_map:
        return set()
    # verify session exists
    out = _run(["zellij", "list-sessions", "-n", "-s"])
    if SESSION not in out:
        return set()
    return set(pane_map.keys())


def _zellij_capture_pane(agent_id: str) -> str:
    pane_map = _zellij_load_pane_map()
    pane_id = pane_map.get(agent_id)
    if pane_id is None:
        return ""
    out = _run(["zellij", "--session", SESSION, "action", "dump-screen",
                "--pane-id", str(pane_id)])
    return _strip_ansi(out)


def _zellij_send_keys(agent_id: str, text: str):
    pane_map = _zellij_load_pane_map()
    pane_id = pane_map.get(agent_id)
    if pane_id is None:
        return
    _run(["zellij", "--session", SESSION, "action", "write-chars",
          "--pane-id", str(pane_id), text])


def _zellij_send_enter(agent_id: str):
    pane_map = _zellij_load_pane_map()
    pane_id = pane_map.get(agent_id)
    if pane_id is None:
        return
    _run(["zellij", "--session", SESSION, "action", "write",
          "--pane-id", str(pane_id), "13"])


# ── Public API ─────────────────────────────────────────

def list_panes() -> set[str]:
    """Return set of agent_id strings for all active panes."""
    if _mux == "zellij":
        return _zellij_list_panes()
    return _tmux_list_panes()


def capture_pane(agent_id: str) -> str:
    """Return text content of a pane. Empty string on failure."""
    if _mux == "zellij":
        return _zellij_capture_pane(agent_id)
    return _tmux_capture_pane(agent_id)


def send_keys(agent_id: str, text: str):
    """Type text into a pane (literal, no Enter)."""
    if _mux == "zellij":
        _zellij_send_keys(agent_id, text)
    else:
        _tmux_send_keys(agent_id, text)


def send_enter(agent_id: str):
    """Press Enter in a pane."""
    if _mux == "zellij":
        _zellij_send_enter(agent_id)
    else:
        _tmux_send_enter(agent_id)
