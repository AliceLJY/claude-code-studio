"""Auto-kick daemon — watches for unread messages and wakes agents via tmux."""

import subprocess
import time
import sys
import os

from studio import db


def get_tmux_windows() -> set[str]:
    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-t", "studio", "-F", "#{window_name}"],
            capture_output=True, text=True, timeout=5,
        )
        return set(result.stdout.strip().split("\n")) if result.returncode == 0 else set()
    except Exception:
        return set()


def is_agent_idle(agent_id: str) -> bool:
    """Check if the agent's tmux pane is waiting for input (not busy)."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"studio:{agent_id}", "-p", "-l", "3"],
            capture_output=True, text=True, timeout=5,
        )
        last_lines = result.stdout.strip()
        # if the last line ends with common idle indicators, agent is waiting
        return last_lines.endswith(">") or last_lines.endswith("% ") or last_lines.endswith("$ ")
    except Exception:
        return False


def kick_agent(agent_id: str):
    """Send a prompt to the agent's tmux window."""
    prompt = "You have new messages. Check inbox and handle them."
    subprocess.run(
        ["tmux", "send-keys", "-t", f"studio:{agent_id}", prompt, "Enter"],
        capture_output=True, text=True, timeout=5,
    )


def main():
    db.init_db()
    interval = int(os.environ.get("WATCHER_INTERVAL", "5"))
    print(f"Watcher started. Polling every {interval}s...")

    # track which agents we already kicked (avoid spamming)
    kicked: dict[str, float] = {}
    cooldown = 30  # don't kick same agent within 30s

    while True:
        try:
            windows = get_tmux_windows()
            agents = db.list_agents()

            for agent in agents:
                aid = agent["agent_id"]
                if aid not in windows:
                    continue

                # check unread messages
                conn = db.get_conn()
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM messages WHERE (to_agent=? OR to_agent='__broadcast__') AND read=0",
                    (aid,),
                ).fetchone()
                conn.close()
                unread = row["cnt"] if row else 0

                if unread > 0:
                    # cooldown check
                    last_kick = kicked.get(aid, 0)
                    if time.time() - last_kick < cooldown:
                        continue

                    if is_agent_idle(aid):
                        print(f"[watcher] {aid} has {unread} unread msg(s) — kicking!")
                        kick_agent(aid)
                        kicked[aid] = time.time()

        except Exception as e:
            print(f"[watcher] error: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
