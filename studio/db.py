"""SQLite storage layer for Claude Code Studio."""

import sqlite3
import time
import os
from pathlib import Path

DB_PATH = os.environ.get(
    "STUDIO_DB_PATH",
    str(Path.home() / ".claude-code-studio" / "studio.db"),
)


def _ensure_dir():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id   TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            role       TEXT DEFAULT '',
            project_dir TEXT DEFAULT '',
            status     TEXT DEFAULT 'online',
            registered_at REAL NOT NULL,
            last_seen  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            from_agent TEXT NOT NULL,
            to_agent   TEXT NOT NULL,  -- agent_id or '__broadcast__'
            content    TEXT NOT NULL,
            created_at REAL NOT NULL,
            read       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            description TEXT DEFAULT '',
            assigned_to TEXT DEFAULT '',
            assigned_by TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',
            priority    TEXT DEFAULT 'medium',
            notes       TEXT DEFAULT '',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ── Agents ──────────────────────────────────────────────

def register_agent(agent_id: str, name: str, role: str = "", project_dir: str = ""):
    conn = get_conn()
    now = time.time()
    conn.execute(
        """INSERT INTO agents (agent_id, name, role, project_dir, registered_at, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
             name=excluded.name, role=excluded.role,
             project_dir=excluded.project_dir,
             status='online', last_seen=excluded.last_seen""",
        (agent_id, name, role, project_dir, now, now),
    )
    conn.commit()
    conn.close()


def unregister_agent(agent_id: str):
    conn = get_conn()
    conn.execute("UPDATE agents SET status='offline' WHERE agent_id=?", (agent_id,))
    conn.commit()
    conn.close()


def heartbeat(agent_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE agents SET last_seen=?, status='online' WHERE agent_id=?",
        (time.time(), agent_id),
    )
    conn.commit()
    conn.close()


def list_agents() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM agents ORDER BY registered_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Messages ────────────────────────────────────────────

def send_message(from_agent: str, to_agent: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (from_agent, to_agent, content, created_at) VALUES (?,?,?,?)",
        (from_agent, to_agent, content, time.time()),
    )
    conn.commit()
    conn.close()


def broadcast(from_agent: str, content: str):
    send_message(from_agent, "__broadcast__", content)


def read_inbox(agent_id: str, unread_only: bool = True) -> list[dict]:
    conn = get_conn()
    if unread_only:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE (to_agent=? OR to_agent='__broadcast__') AND read=0
               ORDER BY created_at""",
            (agent_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE to_agent=? OR to_agent='__broadcast__'
               ORDER BY created_at DESC LIMIT 50""",
            (agent_id,),
        ).fetchall()
    # mark as read
    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"UPDATE messages SET read=1 WHERE id IN ({placeholders})", ids)
        conn.commit()
    conn.close()
    return [dict(r) for r in rows]


# ── Tasks ───────────────────────────────────────────────

def create_task(title: str, description: str, assigned_to: str, assigned_by: str, priority: str = "medium") -> int:
    conn = get_conn()
    now = time.time()
    cur = conn.execute(
        """INSERT INTO tasks (title, description, assigned_to, assigned_by, priority, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (title, description, assigned_to, assigned_by, priority, now, now),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def update_task(task_id: int, status: str = "", notes: str = "") -> bool:
    conn = get_conn()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        conn.close()
        return False
    updates = ["updated_at=?"]
    params: list = [time.time()]
    if status:
        updates.append("status=?")
        params.append(status)
    if notes:
        updates.append("notes=?")
        params.append(notes)
    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return True


def get_tasks(agent_id: str = "", status: str = "") -> list[dict]:
    conn = get_conn()
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list = []
    if agent_id:
        query += " AND assigned_to=?"
        params.append(agent_id)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
