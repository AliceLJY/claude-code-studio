"""Claude Code Studio — MCP Server.

A shared MCP server that enables multiple Claude Code sessions
to communicate, coordinate tasks, and collaborate as a team.
"""

import datetime
import logging
import os
import subprocess

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Backend selection: STUDIO_BACKEND=redis or sqlite (default)
_backend = os.environ.get("STUDIO_BACKEND", "sqlite")
if _backend == "redis":
    from studio import db_redis as db
else:
    from studio import db

mcp = FastMCP(
    "Claude Code Studio",
    instructions="""You are connected to Claude Code Studio — a shared workspace
where multiple Claude Code sessions collaborate as a team.

On startup, call `register` with a unique agent_id (e.g. "architect", "frontend").
Periodically call `check_inbox` to see if anyone sent you a message or task.
Use `studio_status` to see the big picture — who's online and what's happening.
When you finish a task, call `update_task` to report completion.""",
)

# ── Helpers ─────────────────────────────────────────────

def _ts(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def _agent_status_icon(status: str) -> str:
    return {"online": "[ONLINE]", "offline": "[OFFLINE]", "busy": "[BUSY]"}.get(status, "[?]")


# ── Agent lifecycle ─────────────────────────────────────

@mcp.tool()
def register(agent_id: str, name: str, role: str = "", project_dir: str = "") -> str:
    """Join the studio. Call this when your session starts.

    Args:
        agent_id: Unique ID for this agent (e.g. "architect", "backend", "tester")
        name: Display name (e.g. "Backend Engineer")
        role: What this agent is responsible for
        project_dir: Working directory of this agent's project
    """
    db.register_agent(agent_id, name, role, project_dir)
    agents = db.list_agents()
    online = [a for a in agents if a["status"] == "online"]
    return f"Registered as '{agent_id}'. Studio has {len(online)} agent(s) online: {', '.join(a['agent_id'] for a in online)}"


@mcp.tool()
def unregister(agent_id: str) -> str:
    """Leave the studio. Call this when your session ends.

    Args:
        agent_id: Your agent ID
    """
    db.unregister_agent(agent_id)
    return f"Agent '{agent_id}' is now offline."


@mcp.tool()
def heartbeat(agent_id: str) -> str:
    """Signal that you're still active. Call periodically.

    Args:
        agent_id: Your agent ID
    """
    db.heartbeat(agent_id)
    return "OK"


# ── Messaging ───────────────────────────────────────────

@mcp.tool()
def send_message(from_agent: str, to_agent: str, content: str) -> str:
    """Send a direct message to another agent.

    Args:
        from_agent: Your agent ID
        to_agent: Recipient's agent ID
        content: Message content (markdown supported)
    """
    agents = {a["agent_id"] for a in db.list_agents()}
    if to_agent not in agents:
        return f"Error: agent '{to_agent}' not found. Available: {', '.join(sorted(agents))}"
    db.send_message(from_agent, to_agent, content)
    return f"Message sent to '{to_agent}'."


@mcp.tool()
def broadcast(from_agent: str, content: str) -> str:
    """Send a message to ALL agents in the studio.

    Args:
        from_agent: Your agent ID
        content: Message content (markdown supported)
    """
    db.broadcast(from_agent, content)
    return "Broadcast sent to all agents."


@mcp.tool()
def check_inbox(agent_id: str, unread_only: bool = True) -> str:
    """Check your inbox for messages and broadcasts.

    Args:
        agent_id: Your agent ID
        unread_only: If True, only show unread messages
    """
    msgs = db.read_inbox(agent_id, unread_only)
    if not msgs:
        return "Inbox empty — no new messages."
    lines = []
    for m in msgs:
        sender = m["from_agent"]
        is_broadcast = m["to_agent"] == "__broadcast__"
        prefix = "[BROADCAST]" if is_broadcast else f"[DM from {sender}]"
        lines.append(f"{prefix} ({_ts(m['created_at'])})\n{m['content']}")
    return f"{len(msgs)} message(s):\n\n" + "\n\n---\n\n".join(lines)


# ── Task dispatch ───────────────────────────────────────

@mcp.tool()
def dispatch_task(
    assigned_by: str,
    assigned_to: str,
    title: str,
    description: str = "",
    priority: str = "medium",
) -> str:
    """Assign a task to an agent.

    Args:
        assigned_by: Your agent ID (who's dispatching)
        assigned_to: Target agent ID (who should do the work)
        title: Brief task title
        description: Detailed task description
        priority: "high", "medium", or "low"
    """
    if priority not in ("high", "medium", "low"):
        priority = "medium"
    agents = {a["agent_id"] for a in db.list_agents()}
    if assigned_to not in agents:
        return f"Error: agent '{assigned_to}' not found. Available: {', '.join(sorted(agents))}"
    task_id = db.create_task(title, description, assigned_to, assigned_by, priority)
    # also notify via message
    db.send_message(
        assigned_by,
        assigned_to,
        f"**New Task #{task_id}** [{priority.upper()}]: {title}\n\n{description}",
    )
    return f"Task #{task_id} created and assigned to '{assigned_to}'."


@mcp.tool()
def update_task(task_id: int, status: str, notes: str = "") -> str:
    """Update a task's status. Automatically notifies the task dispatcher.

    Args:
        task_id: The task ID to update
        status: New status: "in_progress", "done", "blocked"
        notes: Optional notes about the update
    """
    if status not in ("pending", "in_progress", "done", "blocked"):
        return f"Invalid status '{status}'. Use: pending, in_progress, done, blocked"
    # look up task to notify dispatcher
    tasks = db.get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return f"Task #{task_id} not found."
    db.update_task(task_id, status, notes)
    # auto-notify the person who dispatched this task
    if task["assigned_by"] and task["assigned_by"] != task["assigned_to"]:
        notes_str = f"\n\nNotes: {notes}" if notes else ""
        db.send_message(
            task["assigned_to"],
            task["assigned_by"],
            f"**Task #{task_id} → {status.upper()}**: {task['title']}{notes_str}",
        )
    return f"Task #{task_id} updated to '{status}'. Notified '{task['assigned_by']}'."


@mcp.tool()
def my_tasks(agent_id: str) -> str:
    """List tasks assigned to you.

    Args:
        agent_id: Your agent ID
    """
    tasks = db.get_tasks(agent_id=agent_id)
    if not tasks:
        return "No tasks assigned to you."
    lines = []
    for t in tasks:
        icon = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "blocked": "[!]"}.get(t["status"], "[?]")
        lines.append(f"{icon} #{t['id']} [{t['priority'].upper()}] {t['title']} (from {t['assigned_by']})")
        if t["notes"]:
            lines.append(f"    Notes: {t['notes']}")
    return "\n".join(lines)


# ── Studio overview ─────────────────────────────────────

@mcp.tool()
def studio_status() -> str:
    """Get full overview of the studio: who's online, all tasks, recent messages.
    Use this to understand the big picture.
    """
    agents = db.list_agents()
    tasks = db.get_tasks()

    lines = ["# Studio Status", ""]

    # Agents
    lines.append("## Agents")
    if not agents:
        lines.append("No agents registered yet.")
    for a in agents:
        icon = _agent_status_icon(a["status"])
        role_str = f" — {a['role']}" if a["role"] else ""
        lines.append(f"- {icon} **{a['agent_id']}** ({a['name']}{role_str})")
    lines.append("")

    # Task board
    lines.append("## Task Board")
    if not tasks:
        lines.append("No tasks yet.")
    else:
        for status_group in ["in_progress", "pending", "blocked", "done"]:
            group = [t for t in tasks if t["status"] == status_group]
            if group:
                lines.append(f"\n### {status_group.replace('_', ' ').title()}")
                for t in group:
                    lines.append(
                        f"- #{t['id']} [{t['priority'].upper()}] {t['title']} "
                        f"→ {t['assigned_to']} (by {t['assigned_by']})"
                    )
                    if t["notes"]:
                        lines.append(f"  Notes: {t['notes']}")

    return "\n".join(lines)


# ── Kick (auto-prompt agent via tmux) ───────────────────

@mcp.tool()
def kick(agent_id: str, prompt: str = "") -> str:
    """Wake up an agent by sending a prompt to their terminal pane.
    Use this so you don't have to manually switch windows.

    Args:
        agent_id: The agent to kick (e.g. "agent-1", "agent-2")
        prompt: What to tell them (default: "check inbox and do your tasks")
    """
    from studio import mux

    # P2: Input validation
    if not agent_id or not agent_id.strip():
        return "Error: agent_id cannot be empty."

    if not prompt:
        prompt = "check inbox, if there are tasks do them, report back when done"

    try:
        panes = mux.list_panes()
        if agent_id not in panes:
            return f"Pane '{agent_id}' not found in studio. Available: {', '.join(sorted(panes))}"

        mux.send_keys(agent_id, prompt)
        mux.send_enter(agent_id)
        return f"Kicked '{agent_id}' with: {prompt}"
    except (OSError, subprocess.SubprocessError) as e:
        # P1 Fix 10: Narrow exception types, add logging
        logger.error("Failed to kick '%s': %s", agent_id, e, exc_info=True)
        return f"Failed to kick '{agent_id}': {e}"
    except Exception as e:
        logger.error("Unexpected error kicking '%s': %s", agent_id, e, exc_info=True)
        return f"Failed to kick '{agent_id}': {e}"


# ── Entrypoint ──────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # P2: Server startup error handling -- log and exit cleanly on fatal errors
    try:
        db.init_db()
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc, exc_info=True)
        raise SystemExit(1) from exc

    host = os.environ.get("STUDIO_HOST", "localhost")
    port_str = os.environ.get("STUDIO_PORT", "3777")
    try:
        port = int(port_str)
    except ValueError:
        logger.error("Invalid STUDIO_PORT value: %r (must be integer)", port_str)
        raise SystemExit(1)

    logger.info("Starting Claude Code Studio on %s:%d (backend=%s)", host, port, _backend)
    mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    main()
