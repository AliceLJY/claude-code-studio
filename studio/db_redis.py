"""Redis storage layer for Claude Code Studio.

Drop-in replacement for db.py with pub/sub support.
Messages trigger real-time notifications via Redis pub/sub.
"""

import atexit
import json
import logging
import os
import time

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("STUDIO_REDIS_URL", "redis://localhost:6379")
REDIS_PREFIX = "studio:"
MSG_TTL = 3600 * 24  # messages expire after 24h
TASK_TTL = 3600 * 72  # tasks expire after 72h

_pool: redis.ConnectionPool | None = None

def _get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    return _pool


def _reset_pool():
    """Discard the current connection pool so the next call creates a fresh one."""
    global _pool
    if _pool is not None:
        try:
            _pool.disconnect()
        except Exception:
            pass
        _pool = None


# P2: Clean up global connection pool on process exit
atexit.register(_reset_pool)


def get_conn() -> redis.Redis:
    return redis.Redis(connection_pool=_get_pool())


def init_db():
    """Verify Redis before serving requests; a dead backend is a fatal startup error."""
    try:
        r = get_conn()
        r.ping()
        logger.info("Redis connection OK")
    except redis.RedisError as exc:
        _reset_pool()
        logger.error("Redis initialization failed (%s)", type(exc).__name__)
        raise


# ── Agents ──────────────────────────────────────────────

def register_agent(agent_id: str, name: str, role: str = "", project_dir: str = ""):
    r = get_conn()
    now = time.time()
    agent_data = {
        "agent_id": agent_id,
        "name": name,
        "role": role,
        "project_dir": project_dir,
        "status": "online",
        "registered_at": now,
        "last_seen": now,
    }
    mapping = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in agent_data.items()}
    # Use pipeline for atomicity (P1: Redis set race)
    pipe = r.pipeline(transaction=True)
    pipe.hset(f"{REDIS_PREFIX}agent:{agent_id}", mapping=mapping)
    pipe.sadd(f"{REDIS_PREFIX}agents", agent_id)
    pipe.execute()


def unregister_agent(agent_id: str):
    r = get_conn()
    r.hset(f"{REDIS_PREFIX}agent:{agent_id}", "status", "offline")


def heartbeat(agent_id: str):
    r = get_conn()
    r.hset(f"{REDIS_PREFIX}agent:{agent_id}", mapping={"last_seen": str(time.time()), "status": "online"})


def list_agents() -> list[dict]:
    r = get_conn()
    agent_ids = r.smembers(f"{REDIS_PREFIX}agents")
    agents = []
    for aid in sorted(agent_ids):
        data = r.hgetall(f"{REDIS_PREFIX}agent:{aid}")
        if data:
            # convert numeric strings back
            for k in ("registered_at", "last_seen"):
                if k in data:
                    data[k] = float(data[k])
            agents.append(data)
    return agents


# ── Messages ────────────────────────────────────────────

def _next_msg_id(r: redis.Redis) -> int:
    return r.incr(f"{REDIS_PREFIX}msg_seq")


def send_message(from_agent: str, to_agent: str, content: str):
    r = get_conn()
    msg_id = _next_msg_id(r)
    now = time.time()
    msg = {
        "id": msg_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "content": content,
        "created_at": now,
        "read": 0,
    }
    msg_key = f"{REDIS_PREFIX}msg:{msg_id}"
    notification = json.dumps({"type": "message", "msg_id": msg_id, "from": from_agent})

    # Use pipeline to batch writes atomically (P1: Redis set race)
    pipe = r.pipeline(transaction=True)
    pipe.hset(msg_key, mapping={k: str(v) for k, v in msg.items()})
    pipe.expire(msg_key, MSG_TTL)

    if to_agent == "__broadcast__":
        agent_ids = r.smembers(f"{REDIS_PREFIX}agents")
        for aid in agent_ids:
            if aid != from_agent:
                pipe.rpush(f"{REDIS_PREFIX}inbox:{aid}", msg_id)
                pipe.publish(f"{REDIS_PREFIX}notify:{aid}", notification)
    else:
        pipe.rpush(f"{REDIS_PREFIX}inbox:{to_agent}", msg_id)
        pipe.publish(f"{REDIS_PREFIX}notify:{to_agent}", notification)

    pipe.execute()


def broadcast(from_agent: str, content: str):
    send_message(from_agent, "__broadcast__", content)


def read_inbox(agent_id: str, unread_only: bool = True) -> list[dict]:
    r = get_conn()
    inbox_key = f"{REDIS_PREFIX}inbox:{agent_id}"
    # Broadcasts are one shared msg hash fanned out to every inbox, so a global
    # `read` bit can't represent per-recipient read state: the first agent to
    # read would mark it read for everyone. Track broadcast reads per agent.
    bcast_read_key = f"{REDIS_PREFIX}bcast_read:{agent_id}"
    already_bcast = set(r.smembers(bcast_read_key))

    msg_ids = r.lrange(inbox_key, 0, -1)
    msgs = []
    read_mids = []
    stale_mids = []
    new_direct_read = []
    new_bcast_read = []
    for mid in msg_ids:
        data = r.hgetall(f"{REDIS_PREFIX}msg:{mid}")
        if not data:
            stale_mids.append(mid)
            continue
        data["id"] = int(data["id"])
        data["created_at"] = float(data["created_at"])
        data["read"] = int(data["read"])
        is_bcast = data["to_agent"] == "__broadcast__"
        already_read = (mid in already_bcast) if is_bcast else (data["read"] == 1)
        if unread_only and already_read:
            continue
        msgs.append(data)
        read_mids.append(mid)
        (new_bcast_read if is_bcast else new_direct_read).append(mid)

    # Mark read and clean up in a pipeline to avoid partial state (P2: message loss)
    if read_mids or stale_mids:
        pipe = r.pipeline(transaction=True)
        for mid in stale_mids:
            pipe.lrem(inbox_key, 0, mid)
        # Direct messages live in exactly one inbox, so a shared read bit is safe.
        for mid in new_direct_read:
            pipe.hset(f"{REDIS_PREFIX}msg:{mid}", "read", "1")
        # Broadcasts: record read state against THIS agent only.
        if new_bcast_read:
            pipe.sadd(bcast_read_key, *new_bcast_read)
            pipe.expire(bcast_read_key, MSG_TTL)
        if unread_only:
            # Remove everything we just read (direct AND broadcast) from this
            # agent's inbox, so the watcher's llen-based check stops kicking us
            # for messages we've already handled.
            for mid in read_mids:
                pipe.lrem(inbox_key, 1, mid)
        pipe.execute()

    if not unread_only:
        msgs = msgs[-50:]

    return msgs


def count_unread(agent_id: str, connection=None) -> int:
    """Count unread direct and per-recipient broadcast messages.

    The inbox list also retains history when ``read_inbox(..., unread_only=False)``
    is used, so its raw length is not an unread count.
    """
    r = connection or get_conn()
    inbox_key = f"{REDIS_PREFIX}inbox:{agent_id}"
    already_bcast = set(r.smembers(f"{REDIS_PREFIX}bcast_read:{agent_id}"))
    stale_mids = []
    unread = 0
    for mid in r.lrange(inbox_key, 0, -1):
        data = r.hgetall(f"{REDIS_PREFIX}msg:{mid}")
        if not data:
            stale_mids.append(mid)
            continue
        if data.get("to_agent") == "__broadcast__":
            if mid not in already_bcast:
                unread += 1
        elif int(data.get("read", 0)) == 0:
            unread += 1

    if stale_mids:
        pipe = r.pipeline(transaction=True)
        for mid in stale_mids:
            pipe.lrem(inbox_key, 0, mid)
        pipe.execute()
    return unread


# ── Tasks ───────────────────────────────────────────────

def _next_task_id(r: redis.Redis) -> int:
    return r.incr(f"{REDIS_PREFIX}task_seq")


def create_task(title: str, description: str, assigned_to: str, assigned_by: str, priority: str = "medium") -> int:
    r = get_conn()
    task_id = _next_task_id(r)
    now = time.time()
    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "assigned_to": assigned_to,
        "assigned_by": assigned_by,
        "priority": priority,
        "status": "pending",
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }
    task_key = f"{REDIS_PREFIX}task:{task_id}"
    pipe = r.pipeline(transaction=True)
    pipe.hset(task_key, mapping={k: str(v) for k, v in task.items()})
    pipe.expire(task_key, TASK_TTL)
    pipe.rpush(f"{REDIS_PREFIX}tasks", task_id)
    pipe.execute()
    return task_id


def update_task(task_id: int, status: str = "", notes: str = "") -> bool:
    r = get_conn()
    task_key = f"{REDIS_PREFIX}task:{task_id}"
    if not r.exists(task_key):
        return False
    updates = {"updated_at": str(time.time())}
    if status:
        updates["status"] = status
    if notes:
        updates["notes"] = notes
    pipe = r.pipeline(transaction=True)
    pipe.hset(task_key, mapping=updates)
    pipe.expire(task_key, TASK_TTL)
    pipe.execute()
    return True


def get_tasks(agent_id: str = "", status: str = "") -> list[dict]:
    r = get_conn()
    task_ids = r.lrange(f"{REDIS_PREFIX}tasks", 0, -1)
    tasks = []
    stale_task_ids = []
    for tid in task_ids:
        data = r.hgetall(f"{REDIS_PREFIX}task:{tid}")
        if not data:
            stale_task_ids.append(tid)
            continue
        data["id"] = int(data["id"])
        data["created_at"] = float(data["created_at"])
        data["updated_at"] = float(data["updated_at"])
        if agent_id and data.get("assigned_to") != agent_id:
            continue
        if status and data.get("status") != status:
            continue
        tasks.append(data)
    if stale_task_ids:
        pipe = r.pipeline(transaction=True)
        for tid in stale_task_ids:
            pipe.lrem(f"{REDIS_PREFIX}tasks", 0, tid)
        pipe.execute()
    # sort by priority
    prio_order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda t: (prio_order.get(t.get("priority", "medium"), 1), t["created_at"]))
    return tasks
