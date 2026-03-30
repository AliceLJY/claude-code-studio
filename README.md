# Claude Code Studio

> Multi-session collaboration studio for Claude Code. Run multiple CC instances as a coordinated team.

Claude Code Studio turns multiple Claude Code CLI sessions into a collaborative team. One session dispatches tasks, others execute — and everyone can communicate through a shared MCP server.

```
┌─────────────────────────────────────────────┐
│              CLAUDE CODE STUDIO              │
│                                              │
│   [You + Commander]  ← strategy & dispatch   │
│       │                                      │
│       ├── Agent A (research)     [ONLINE]    │
│       ├── Agent B (backend)      [ONLINE]    │
│       ├── Agent C (frontend)     [BUSY]      │
│       └── Agent D (testing)      [OFFLINE]   │
│                                              │
│   Agent A → Agent B: "API spec changed"      │
│   Agent B → Agent A: "Got it, updating"      │
│                                              │
│            ┌──────────────┐                  │
│            │  Shared MCP  │ ← message bus    │
│            │  Server      │    + task board   │
│            └──────────────┘                  │
└─────────────────────────────────────────────┘
```

## Why?

You're researching 5 projects across 5 Claude Code sessions. Halfway through, you realize they depend on each other. Now you need them to **talk**.

Existing solutions solve pieces of this (messaging, file locks, task queues) but none deliver the full experience: **dispatch tasks, exchange messages, see the big picture — all through MCP tools that every CC session can call natively.**

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- tmux
- Claude Code CLI

### Install

```bash
git clone https://github.com/AliceLJY/claude-code-studio.git
cd claude-code-studio
uv venv && uv pip install -e .
```

### Launch

```bash
# Launch studio with 1 commander + 3 agent windows
./scripts/launch.sh

# Or specify agent count
./scripts/launch.sh 5
```

This will:
1. Start the MCP server on `localhost:3777`
2. Create a tmux session with separate windows for commander and agents
3. Attach you to the session

### Connect Claude Code

In each Claude Code session, add the studio MCP server:

**Option A: Via `/mcp` command in Claude Code**
```
/mcp
# Add SSE server: http://localhost:3777/sse
```

**Option B: Via settings.json**
```json
{
  "mcpServers": {
    "claude-code-studio": {
      "type": "sse",
      "url": "http://localhost:3777/sse"
    }
  }
}
```

## MCP Tools

Once connected, each Claude Code session has access to these tools:

### Agent Lifecycle
| Tool | Description |
|------|-------------|
| `register` | Join the studio with a unique ID and role |
| `unregister` | Leave the studio |
| `heartbeat` | Signal you're still active |

### Messaging
| Tool | Description |
|------|-------------|
| `send_message` | Direct message another agent |
| `broadcast` | Message all agents |
| `check_inbox` | Read your messages |

### Task Dispatch
| Tool | Description |
|------|-------------|
| `dispatch_task` | Assign a task to an agent |
| `update_task` | Update task status |
| `my_tasks` | List your assigned tasks |

### Overview
| Tool | Description |
|------|-------------|
| `studio_status` | Full dashboard: agents, tasks, activity |

## Example Workflow

```
# Commander (Window 0)
> Register as commander, then dispatch tasks:
  "Register as 'commander', then dispatch a task to 'researcher':
   Research the top 5 MCP server frameworks"

# Agent 1 (Window 1)
> Register as researcher, check inbox, do the work:
  "Register as 'researcher', check your inbox, and start working"

# Agent 2 (Window 2)
> Register as builder, wait for research results:
  "Register as 'builder', check inbox periodically"

# Commander can check progress anytime:
  "Show me studio_status"
```

## Architecture

```
┌────────────┐  ┌────────────┐  ┌────────────┐
│  CC Session │  │  CC Session │  │  CC Session │
│  (commander)│  │  (agent-1) │  │  (agent-2) │
└──────┬─────┘  └──────┬─────┘  └──────┬─────┘
       │               │               │
       └───────────┬───┴───────────────┘
                   │  SSE/HTTP
           ┌───────▼────────┐
           │   MCP Server   │
           │  (FastMCP/SSE) │
           └───────┬────────┘
                   │
           ┌───────▼────────┐
           │    SQLite DB   │
           │  agents/msgs/  │
           │     tasks      │
           └────────────────┘
```

- **Transport**: SSE (Server-Sent Events) — allows multiple CC sessions to connect to one server
- **Storage**: SQLite with WAL mode — lightweight, zero-config, concurrent-read safe
- **No orchestrator required**: Agents are peers. Any agent can message any other agent.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `STUDIO_HOST` | `localhost` | MCP server bind address |
| `STUDIO_PORT` | `3777` | MCP server port |
| `STUDIO_DB_PATH` | `~/.claude-code-studio/studio.db` | Database file path |

## Comparison with Existing Tools

| Feature | claude-code-studio | mcp_agent_mail | session-bridge | claude-swarm |
|---------|-------------------|----------------|----------------|--------------|
| Peer-to-peer messaging | Yes | Yes | 2 agents only | No |
| Task dispatch + tracking | Yes | No | No | Yes |
| Studio overview | Yes | No | No | Partial |
| tmux launcher | Yes | No | No | Yes |
| No external deps | Yes (SQLite) | Git + SQLite | Files only | Various |
| MCP native | Yes | Yes | No | No |

## License

MIT

## Contributing

Issues and PRs welcome. This project was born from a real need — if you're running multiple Claude Code sessions and wish they could talk to each other, this is for you.
