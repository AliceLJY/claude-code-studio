"""Auto-kick daemon — watches for unread messages and wakes agents.

Supports two modes:
- Redis pub/sub (STUDIO_BACKEND=redis): instant notification, no polling
- SQLite polling (default): checks every 5s

Terminal multiplexer: set STUDIO_MUX=tmux (default) or zellij.
"""

import json
import logging
import signal
import time
import os

from studio import mux

logger = logging.getLogger(__name__)

_backend = os.environ.get("STUDIO_BACKEND", "sqlite")

# P2: Make sleep values configurable instead of hardcoded
KICK_COOLDOWN = int(os.environ.get("WATCHER_COOLDOWN", "30"))
REDIS_KICK_DELAY = float(os.environ.get("WATCHER_REDIS_KICK_DELAY", "1"))
FALLBACK_POLL_INTERVAL = int(os.environ.get("WATCHER_FALLBACK_INTERVAL", "15"))

# Auto-kick relies on is_agent_idle(), a best-effort terminal-scraping heuristic
# that can misread a busy agent as idle and interrupt it. Default on (it's the
# point of the watcher), but allow disabling to avoid the false-positive kicks.
AUTO_KICK = os.environ.get("STUDIO_AUTO_KICK", "1").lower() not in ("0", "false", "no")

# P2: Daemon shutdown flag
_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    logger.info("Received signal %d, shutting down watcher...", signum)
    _shutdown = True


def is_agent_idle(agent_id: str) -> bool:
    """Best-effort guess at whether the agent's pane is waiting for input.

    This scrapes the last terminal line and is inherently unreliable: a bare
    ">" was dropped from the indicators because Claude Code emits it constantly
    while streaming markdown quotes and code, which made the watcher kick agents
    that were mid-output. The remaining markers (shell prompts, the Claude TUI
    "? for shortcuts" hint) are still heuristic, not authoritative.
    """
    last_lines = mux.capture_pane(agent_id)
    if not last_lines:
        return False
    last_line = last_lines.split("\n")[-1].strip()
    idle_indicators = ["? for shortcuts", "❯", "$ ", "% "]
    return any(last_line.endswith(ind) for ind in idle_indicators)


def kick_agent(agent_id: str):
    """Send a prompt to the agent's pane (best-effort auto-wake).

    Honors STUDIO_AUTO_KICK as a final guard so a misfiring idle-heuristic can
    be turned off without disabling the rest of the watcher.
    """
    if not AUTO_KICK:
        logger.info("Auto-kick disabled (STUDIO_AUTO_KICK=0); not kicking %s", agent_id)
        return
    prompt = "You have new messages. Check inbox and handle them."
    mux.send_keys(agent_id, prompt)
    mux.send_enter(agent_id)


# ── Redis pub/sub mode ──────────────────────────────────

def _try_kick(agent_id: str, kicked: dict[str, float], cooldown: int, reason: str) -> bool:
    """Attempt to kick an agent if idle and not in cooldown. Returns True if kicked."""
    try:
        panes = mux.list_panes()
    except Exception as e:
        logger.warning("Failed to list panes: %s", e)
        return False
    if agent_id not in panes:
        return False
    last_kick = kicked.get(agent_id, 0)
    if time.time() - last_kick < cooldown:
        return False
    if is_agent_idle(agent_id):
        logger.info("Kicking %s (%s)", agent_id, reason)
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

    logger.info("Redis pub/sub mode -- listening for messages...")

    kicked: dict[str, float] = {}
    cooldown = KICK_COOLDOWN

    # Fallback polling thread: catch messages missed by pub/sub
    def _fallback_poll():
        while not _shutdown:
            time.sleep(FALLBACK_POLL_INTERVAL)
            if _shutdown:
                break
            try:
                panes = mux.list_panes()
                for aid in r.smembers("studio:agents"):
                    if aid not in panes:
                        continue
                    inbox_len = r.llen(f"studio:inbox:{aid}")
                    if inbox_len > 0:
                        _try_kick(aid, kicked, cooldown, "fallback poll")
            except redis_lib.ConnectionError as e:
                logger.warning("Fallback poll Redis connection error: %s", e)
            except Exception as e:
                logger.error("Fallback poll error: %s", e, exc_info=True)

    poll_thread = threading.Thread(target=_fallback_poll, daemon=True)
    poll_thread.start()

    try:
        for message in pubsub.listen():
            if _shutdown:
                break
            if message["type"] != "pmessage":
                continue

            try:
                agent_id = message["channel"].split(":")[-1]
                data = json.loads(message["data"])
                logger.info("Notification for %s: %s", agent_id, data)

                time.sleep(REDIS_KICK_DELAY)
                _try_kick(agent_id, kicked, cooldown, "pub/sub")

            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON in pub/sub message: %s", e)
            except Exception as e:
                logger.error("Pub/sub handler error: %s", e, exc_info=True)
    finally:
        # P1 Fix 5: Clean up watcher connections on exit
        logger.info("Cleaning up Redis pub/sub connection...")
        try:
            pubsub.punsubscribe()
            pubsub.close()
        except Exception:
            pass


# ── SQLite polling mode ─────────────────────────────────

def run_sqlite():
    """Poll SQLite every N seconds -- fallback mode."""
    from studio import db

    db.init_db()
    interval = int(os.environ.get("WATCHER_INTERVAL", "5"))
    logger.info("SQLite polling mode -- every %ds...", interval)

    kicked: dict[str, float] = {}
    cooldown = KICK_COOLDOWN

    while not _shutdown:
        try:
            panes = mux.list_panes()
            agents = db.list_agents()

            for agent in agents:
                aid = agent["agent_id"]
                if aid not in panes:
                    continue

                # P1 Fix 5: Use managed connection to prevent leaks
                try:
                    with db._managed_conn() as conn:
                        # Broadcast read state lives in broadcast_reads (per
                        # agent), NOT messages.read — which for broadcasts is
                        # never set, so counting `read=0` alone would treat every
                        # past broadcast as forever-unread and kick endlessly.
                        db._ensure_broadcast_reads(conn)
                        row = conn.execute(
                            """SELECT COUNT(*) as cnt FROM messages
                               WHERE (to_agent=? AND read=0)
                                  OR (to_agent='__broadcast__'
                                      AND id NOT IN (
                                          SELECT msg_id FROM broadcast_reads WHERE agent_id=?))""",
                            (aid, aid),
                        ).fetchone()
                    unread = row["cnt"] if row else 0
                except Exception as e:
                    logger.warning("Failed to check unread for %s: %s", aid, e)
                    continue

                if unread > 0:
                    last_kick = kicked.get(aid, 0)
                    if time.time() - last_kick < cooldown:
                        continue
                    if is_agent_idle(aid):
                        logger.info("%s has %d unread -- kicking!", aid, unread)
                        kick_agent(aid)
                        kicked[aid] = time.time()

        except Exception as e:
            logger.error("SQLite poll error: %s", e, exc_info=True)

        time.sleep(interval)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # P2: Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    if _backend == "redis":
        run_redis()
    else:
        run_sqlite()

    logger.info("Watcher stopped.")


if __name__ == "__main__":
    main()
