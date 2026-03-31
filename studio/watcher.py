"""Auto-kick daemon — watches for unread messages and wakes agents.

Supports two modes:
- Redis pub/sub (STUDIO_BACKEND=redis): instant notification, no polling
- SQLite polling (default): checks every 5s

Terminal multiplexer: set STUDIO_MUX=tmux (default) or zellij.
"""

import json
import time
import os

from studio import mux

_backend = os.environ.get("STUDIO_BACKEND", "sqlite")


def is_agent_idle(agent_id: str) -> bool:
    """Check if the agent's pane is waiting for input (not busy)."""
    last_lines = mux.capture_pane(agent_id)
    if not last_lines:
        return False
    last_line = last_lines.split("\n")[-1].strip()
    idle_indicators = ["? for shortcuts", "%", "$", ">"]
    return any(last_line.endswith(ind) for ind in idle_indicators)


def kick_agent(agent_id: str):
    """Send a prompt to the agent's pane."""
    prompt = "You have new messages. Check inbox and handle them."
    mux.send_keys(agent_id, prompt)
    mux.send_enter(agent_id)


# ── Redis pub/sub mode ──────────────────────────────────

def _try_kick(agent_id: str, kicked: dict[str, float], cooldown: int, reason: str) -> bool:
    """Attempt to kick an agent if idle and not in cooldown. Returns True if kicked."""
    panes = mux.list_panes()
    if agent_id not in panes:
        return False
    last_kick = kicked.get(agent_id, 0)
    if time.time() - last_kick < cooldown:
        return False
    if is_agent_idle(agent_id):
        print(f"[watcher] kicking {agent_id} ({reason})!", flush=True)
        kick_agent(agent_id)
        kicked[agent_id] = time.time()
        return True
    return False


def run_redis():
    """Subscribe to Redis notifications with fallback polling for missed messages."""
    import threading
    import redis as redis_lib

    redis_url = os.environ.get("STUDIO_REDIS_URL", "redis://localhost:6379")
    r = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    pubsub = r.pubsub()
    pubsub.psubscribe("studio:notify:*")

    print("[watcher] Redis pub/sub mode — listening for messages...", flush=True)

    kicked: dict[str, float] = {}
    cooldown = 30

    # Fallback polling thread: catch messages missed by pub/sub
    def _fallback_poll():
        poll_interval = 15
        while True:
            time.sleep(poll_interval)
            try:
                panes = mux.list_panes()
                for aid in r.smembers("studio:agents"):
                    if aid not in panes:
                        continue
                    inbox_len = r.llen(f"studio:inbox:{aid}")
                    if inbox_len > 0:
                        _try_kick(aid, kicked, cooldown, "fallback poll")
            except Exception as e:
                print(f"[watcher] fallback poll error: {e}", flush=True)

    poll_thread = threading.Thread(target=_fallback_poll, daemon=True)
    poll_thread.start()

    for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue

        try:
            agent_id = message["channel"].split(":")[-1]
            data = json.loads(message["data"])
            print(f"[watcher] notification for {agent_id}: {data}", flush=True)

            time.sleep(1)
            _try_kick(agent_id, kicked, cooldown, "pub/sub")

        except Exception as e:
            print(f"[watcher] error: {e}", flush=True)


# ── SQLite polling mode ─────────────────────────────────

def run_sqlite():
    """Poll SQLite every N seconds — fallback mode."""
    from studio import db

    db.init_db()
    interval = int(os.environ.get("WATCHER_INTERVAL", "5"))
    print(f"[watcher] SQLite polling mode — every {interval}s...", flush=True)

    kicked: dict[str, float] = {}
    cooldown = 30

    while True:
        try:
            panes = mux.list_panes()
            agents = db.list_agents()

            for agent in agents:
                aid = agent["agent_id"]
                if aid not in panes:
                    continue

                conn = db.get_conn()
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM messages WHERE (to_agent=? OR to_agent='__broadcast__') AND read=0",
                    (aid,),
                ).fetchone()
                conn.close()
                unread = row["cnt"] if row else 0

                if unread > 0:
                    last_kick = kicked.get(aid, 0)
                    if time.time() - last_kick < cooldown:
                        continue
                    if is_agent_idle(aid):
                        print(f"[watcher] {aid} has {unread} unread — kicking!", flush=True)
                        kick_agent(aid)
                        kicked[aid] = time.time()

        except Exception as e:
            print(f"[watcher] error: {e}", flush=True)

        time.sleep(interval)


def main():
    if _backend == "redis":
        run_redis()
    else:
        run_sqlite()


if __name__ == "__main__":
    main()
