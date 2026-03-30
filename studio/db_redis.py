"""Redis storage layer for Claude Code Studio.

Drop-in replacement for db.py with pub/sub support.
Messages trigger real-time notifications via Redis pub/sub.
"""

import json
import os
import time

import redis

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


def get_conn() -> redis.Redis:
    return redis.Redis(connection_pool=_get_pool())


def init_db():
    """Test connection."""
    r = get_conn()
    r.ping()


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
    r.hset(f"{REDIS_PREFIX}agent:{agent_id}", mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in agent_data.items()})
    r.sadd(f"{REDIS_PREFIX}agents", agent_id)


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
    r.hset(msg_key, mapping={k: str(v) for k, v in msg.items()})
    r.expire(msg_key, MSG_TTL)

    # add to recipient's inbox
    if to_agent == "__broadcast__":
        # add to all agents' inboxes
        for aid in r.smembers(f"{REDIS_PREFIX}agents"):
            if aid != from_agent:
                r.rpush(f"{REDIS_PREFIX}inbox:{aid}", msg_id)
                # pub/sub: notify immediately
                r.publish(f"{REDIS_PREFIX}notify:{aid}", json.dumps({"type": "message", "msg_id": msg_id, "from": from_agent}))
    else:
        r.rpush(f"{REDIS_PREFIX}inbox:{to_agent}", msg_id)
        # pub/sub: notify immediately
        r.publish(f"{REDIS_PREFIX}notify:{to_agent}", json.dumps({"type": "message", "msg_id": msg_id, "from": from_agent}))


def broadcast(from_agent: str, content: str):
    send_message(from_agent, "__broadcast__", content)


def read_inbox(agent_id: str, unread_only: bool = True) -> list[dict]:
    r = get_conn()
    msg_ids = r.lrange(f"{REDIS_PREFIX}inbox:{agent_id}", 0, -1)
    msgs = []
    for mid in msg_ids:
        data = r.hgetall(f"{REDIS_PREFIX}msg:{mid}")
        if not data:
            continue
        data["id"] = int(data["id"])
        data["created_at"] = float(data["created_at"])
        data["read"] = int(data["read"])
        if unread_only and data["read"] == 1:
            continue
        msgs.append(data)
        # mark as read
        r.hset(f"{REDIS_PREFIX}msg:{mid}", "read", "1")

    # clear inbox after reading
    if not unread_only:
        msgs = msgs[-50:]  # last 50
    else:
        # remove read messages from inbox list
        r.delete(f"{REDIS_PREFIX}inbox:{agent_id}")

    return msgs


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
    r.hset(task_key, mapping={k: str(v) for k, v in task.items()})
    r.expire(task_key, TASK_TTL)
    r.rpush(f"{REDIS_PREFIX}tasks", task_id)
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
    r.hset(task_key, mapping=updates)
    return True


def get_tasks(agent_id: str = "", status: str = "") -> list[dict]:
    r = get_conn()
    task_ids = r.lrange(f"{REDIS_PREFIX}tasks", 0, -1)
    tasks = []
    for tid in task_ids:
        data = r.hgetall(f"{REDIS_PREFIX}task:{tid}")
        if not data:
            continue
        data["id"] = int(data["id"])
        data["created_at"] = float(data["created_at"])
        data["updated_at"] = float(data["updated_at"])
        if agent_id and data.get("assigned_to") != agent_id:
            continue
        if status and data.get("status") != status:
            continue
        tasks.append(data)
    # sort by priority
    prio_order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda t: (prio_order.get(t.get("priority", "medium"), 1), t["created_at"]))
    return tasks
