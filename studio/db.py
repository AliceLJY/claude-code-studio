"""SQLite storage layer for Claude Code Studio."""

import logging
import sqlite3
import time
import os
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "STUDIO_DB_PATH",
    str(Path.home() / ".claude-code-studio" / "studio.db"),
)

# P0 Fix 4: Allowlist of valid column names for dynamic SQL
_VALID_COLUMNS = frozenset({
    "agent_id", "name", "role", "project_dir", "status",
    "registered_at", "last_seen",
    "id", "from_agent", "to_agent", "content", "created_at", "read",
    "title", "description", "assigned_to", "assigned_by",
    "priority", "notes", "updated_at",
})


def _ensure_dir():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _managed_conn():
    """Context manager that commits on success, rolls back on error, always closes."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    try:
        with _managed_conn() as conn:
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
    except sqlite3.OperationalError as exc:
        logger.warning("init_db schema setup: %s (tables may already exist)", exc)


# ── Agents ──────────────────────────────────────────────

def register_agent(agent_id: str, name: str, role: str = "", project_dir: str = ""):
    now = time.time()
    with _managed_conn() as conn:
        conn.execute(
            """INSERT INTO agents (agent_id, name, role, project_dir, registered_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 name=excluded.name, role=excluded.role,
                 project_dir=excluded.project_dir,
                 status='online', last_seen=excluded.last_seen""",
            (agent_id, name, role, project_dir, now, now),
        )


def unregister_agent(agent_id: str):
    with _managed_conn() as conn:
        conn.execute("UPDATE agents SET status='offline' WHERE agent_id=?", (agent_id,))


def heartbeat(agent_id: str):
    with _managed_conn() as conn:
        conn.execute(
            "UPDATE agents SET last_seen=?, status='online' WHERE agent_id=?",
            (time.time(), agent_id),
        )


def list_agents() -> list[dict]:
    with _managed_conn() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY registered_at").fetchall()
    return [dict(r) for r in rows]


# ── Messages ────────────────────────────────────────────

def send_message(from_agent: str, to_agent: str, content: str):
    with _managed_conn() as conn:
        conn.execute(
            "INSERT INTO messages (from_agent, to_agent, content, created_at) VALUES (?,?,?,?)",
            (from_agent, to_agent, content, time.time()),
        )


def broadcast(from_agent: str, content: str):
    send_message(from_agent, "__broadcast__", content)


# Track whether broadcast_reads table has been ensured this process
_broadcast_reads_ensured = False


def _ensure_broadcast_reads(conn: sqlite3.Connection):
    """Create broadcast_reads table once per process, not on every call (P0 Fix 2)."""
    global _broadcast_reads_ensured
    if _broadcast_reads_ensured:
        return
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS broadcast_reads (
            agent_id TEXT, msg_id INTEGER, PRIMARY KEY (agent_id, msg_id))""")
        _broadcast_reads_ensured = True
    except sqlite3.OperationalError:
        # Table already exists or concurrent creation -- safe to ignore
        _broadcast_reads_ensured = True


def read_inbox(agent_id: str, unread_only: bool = True) -> list[dict]:
    with _managed_conn() as conn:
        _ensure_broadcast_reads(conn)

        if unread_only:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE (to_agent=? AND read=0)
                      OR (to_agent='__broadcast__'
                          AND id NOT IN (SELECT msg_id FROM broadcast_reads WHERE agent_id=?))
                   ORDER BY created_at""",
                (agent_id, agent_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE to_agent=? OR to_agent='__broadcast__'
                   ORDER BY created_at DESC LIMIT 50""",
                (agent_id,),
            ).fetchall()

        # mark as read -- only mark direct messages; broadcasts use per-agent tracking
        direct_ids = [r["id"] for r in rows if r["to_agent"] != "__broadcast__"]
        broadcast_ids = [r["id"] for r in rows if r["to_agent"] == "__broadcast__"]

        # P0 Fix 3: Guard against empty IN clause
        if direct_ids:
            placeholders = ",".join("?" * len(direct_ids))
            conn.execute(f"UPDATE messages SET read=1 WHERE id IN ({placeholders})", direct_ids)

        # track broadcast reads per-agent
        for mid in broadcast_ids:
            conn.execute("INSERT OR IGNORE INTO broadcast_reads (agent_id, msg_id) VALUES (?,?)",
                         (agent_id, mid))

    return [dict(r) for r in rows]


# ── Tasks ───────────────────────────────────────────────

def create_task(title: str, description: str, assigned_to: str, assigned_by: str, priority: str = "medium") -> int:
    # P2: Input validation
    if priority not in ("high", "medium", "low"):
        priority = "medium"
    now = time.time()
    with _managed_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (title, description, assigned_to, assigned_by, priority, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (title, description, assigned_to, assigned_by, priority, now, now),
        )
        task_id = cur.lastrowid
    return task_id


def update_task(task_id: int, status: str = "", notes: str = "") -> bool:
    # P0 Fix 4: Validate dynamic column names against allowlist
    update_fields: dict[str, object] = {"updated_at": time.time()}
    if status:
        if "status" not in _VALID_COLUMNS:
            raise ValueError("Invalid column name: status")
        update_fields["status"] = status
    if notes:
        if "notes" not in _VALID_COLUMNS:
            raise ValueError("Invalid column name: notes")
        update_fields["notes"] = notes

    with _managed_conn() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return False
        set_clause = ", ".join(f"{col}=?" for col in update_fields)
        params = list(update_fields.values()) + [task_id]
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id=?", params)
    return True


def get_tasks(agent_id: str = "", status: str = "") -> list[dict]:
    with _managed_conn() as conn:
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
    return [dict(r) for r in rows]
