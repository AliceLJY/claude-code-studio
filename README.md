# Claude Code Studio

> Multi-session collaboration studio for Claude Code. Run multiple CC instances as a coordinated team.

Claude Code Studio turns multiple Claude Code CLI sessions into a collaborative team. One session dispatches tasks, others execute — and everyone communicates through a shared MCP server with **real-time message delivery** via Redis pub/sub.

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
│            │  Redis + MCP │ ← pub/sub bus    │
│            │  Server      │    + task board   │
│            └──────────────┘                  │
└─────────────────────────────────────────────┘
```

## Why?

You're researching 5 projects across 5 Claude Code sessions. Halfway through, you realize they depend on each other. Now you need them to **talk**.

Existing solutions solve pieces of this (messaging, file locks, task queues) but none deliver the full experience:

- **Dispatch tasks** from a commander to worker agents
- **Exchange messages** between any agents (peer-to-peer, not just hub-and-spoke)
- **Auto-wake agents** when they receive messages (no manual window switching)
- **See the big picture** with a single command

All through MCP tools that every Claude Code session can call natively.

## Features

- **One-click launch** — single script starts MCP server, watcher daemon, and tmux windows with Claude Code auto-started in each
- **Real-time messaging** — Redis pub/sub delivers messages instantly, watcher auto-kicks idle agents
- **Peer-to-peer** — any agent can message any other agent, not just commander → worker
- **Task dispatch & tracking** — assign tasks with priority, track status, auto-notify on completion
- **Auto-registration** — agents register themselves on startup via project CLAUDE.md
- **Cross-machine ready** — point `STUDIO_REDIS_URL` at a remote Redis and run agents on different machines
- **CLI status tool** — check studio status from terminal without entering Claude Code
- **Cross-model review** — OpenAI's official [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) works inside the studio, letting Codex (GPT-5.4) review code written by Claude — two competing AI companies' models collaborating in one workspace

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- tmux or [zellij](https://zellij.dev) (either one works)
- Redis (Docker: `docker run -d -p 6379:6379 redis:7-alpine`)
- Claude Code CLI

### Install

```bash
git clone https://github.com/AliceLJY/claude-code-studio.git
cd claude-code-studio
uv venv && uv pip install -e .
```

### Launch

```bash
# Launch studio with 1 commander + 3 agent windows (default)
./scripts/launch.sh

# Specify agent count
./scripts/launch.sh 5

# Use zellij instead of tmux
STUDIO_MUX=zellij ./scripts/launch.sh
```

This will:
1. Start the MCP server on `localhost:3777`
2. Start the watcher daemon (auto-kicks agents on new messages)
3. Create a tmux session with separate windows
4. Auto-start `claude` in every window
5. Each Claude auto-registers itself on startup

**You just sit in the commander window and talk.** That's it.

### Check Status (CLI)

```bash
# See who's online and task board without entering Claude Code
./scripts/status.sh
```

### Connect Claude Code

The MCP server is auto-configured if you run Claude Code from the project directory. For other directories, add to your `~/.claude.json`:

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

## How It Works

```
You say: "Tell agent-1 to research MCP frameworks"

Commander CC                    Watcher Daemon              Agent-1 CC
     │                               │                          │
     ├─ send_message(agent-1) ──────►│                          │
     │       │                       │                          │
     │       └─► Redis PUBLISH ─────►│                          │
     │                               ├─ tmux send-keys ───────►│
     │                               │  "check inbox"           │
     │                               │                          ├─ check_inbox()
     │                               │                          ├─ (does research)
     │                               │                          ├─ send_message(commander)
     │                               │                          │       │
     │                          ◄────┤◄─ Redis PUBLISH ─────────┘       │
     │◄─ tmux send-keys ────────┤    │                                  │
     │   "check inbox"          │    │                                  │
     ├─ check_inbox() ──────────┘    │                                  │
     ├─ "agent-1 says: ..."         │                                  │
     │                               │                                  │
```

No window switching needed. Messages flow automatically.

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
           ┌───────▼────────┐     ┌──────────────┐
           │     Redis      │◄───►│   Watcher    │
           │  pub/sub + KV  │     │  (auto-kick) │
           └────────────────┘     └──────────────┘
```

- **MCP Server**: FastMCP with SSE transport — multiple CC sessions connect to one server
- **Redis**: Message storage + pub/sub for instant delivery. Messages TTL 24h, tasks TTL 72h.
- **Watcher**: Subscribes to Redis pub/sub, auto-sends prompts to idle agent tmux windows
- **SQLite fallback**: Set `STUDIO_BACKEND=sqlite` if you don't have Redis

## MCP Tools

| Tool | Description |
|------|-------------|
| `register` | Join the studio with a unique ID and role |
| `unregister` | Leave the studio |
| `send_message` | Direct message another agent |
| `broadcast` | Message all agents |
| `check_inbox` | Read your messages |
| `dispatch_task` | Assign a task to an agent (auto-notifies) |
| `update_task` | Update task status (auto-notifies dispatcher) |
| `my_tasks` | List your assigned tasks |
| `studio_status` | Full dashboard: agents, tasks, activity |
| `kick` | Wake up an agent remotely via tmux |
| `heartbeat` | Signal you're still active |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `STUDIO_HOST` | `localhost` | MCP server bind address |
| `STUDIO_PORT` | `3777` | MCP server port |
| `STUDIO_BACKEND` | `redis` | Storage backend: `redis` or `sqlite` |
| `STUDIO_REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `STUDIO_MUX` | `tmux` | Terminal multiplexer: `tmux` or `zellij` |
| `STUDIO_DB_PATH` | `~/.claude-code-studio/studio.db` | SQLite database path (sqlite mode) |

## Cross-Machine Setup

Run agents on different machines by pointing to a shared Redis:

```bash
# Machine A (your Mac)
STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh

# Machine B (Mac Mini)
STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh 3
```

All agents across both machines share the same message bus and task board.

## Comparison with Existing Tools

| Feature | claude-code-studio | mcp_agent_mail | session-bridge | claude-swarm |
|---------|-------------------|----------------|----------------|--------------|
| Peer-to-peer messaging | Yes | Yes | 2 agents only | No |
| Real-time delivery | Yes (Redis pub/sub) | No (polling) | No | No |
| Auto-wake agents | Yes (watcher) | No | No | No |
| Task dispatch + tracking | Yes | No | No | Yes |
| One-click launch | Yes | No | No | Yes |
| Cross-machine | Yes (Redis) | Yes (Git) | No | No |
| No external deps | SQLite mode | Git + SQLite | Files only | Various |

## Cross-Model Collaboration

Claude Code Studio naturally supports cross-model workflows. With OpenAI's official [codex-plugin-cc](https://github.com/openai/codex-plugin-cc), you can have Codex (GPT-5.4) review code written by Claude agents — right inside the studio.

```
┌─────────────────────────────────────────────────┐
│              CLAUDE CODE STUDIO                  │
│                                                  │
│   Claude (Opus)     writes code                  │
│       │                                          │
│       ▼                                          │
│   Codex (GPT-5.4)   reviews code (/codex:review)│
│       │                                          │
│       ▼                                          │
│   Claude (Opus)     verifies findings & fixes    │
│                                                  │
│   Two competing AI companies' models,            │
│   collaborating in one workspace.                │
└─────────────────────────────────────────────────┘
```

Install the plugin:
```bash
claude plugins marketplace add openai/codex-plugin-cc
claude plugins install codex@openai-codex
```

Then use `/codex:review`, `/codex:adversarial-review`, or `/codex:rescue` inside any studio session.

## Ecosystem

Part of the **小试AI** open-source AI workflow:

| Project | Description |
|---------|-------------|
| [recallnest](https://github.com/AliceLJY/recallnest) | MCP memory workbench (LanceDB + Jina v5) |
| [content-publisher](https://github.com/AliceLJY/content-publisher) | Image generation + layout + WeChat publishing |
| [openclaw-tunnel](https://github.com/AliceLJY/openclaw-tunnel) | Docker ↔ host CLI bridge (/cc /codex /gemini) |
| [digital-clone-skill](https://github.com/AliceLJY/digital-clone-skill) | Build digital clones from corpus data |
| [telegram-ai-bridge](https://github.com/AliceLJY/telegram-ai-bridge) | Telegram bots for Claude, Codex, and Gemini |
| [cc-empire](https://github.com/AliceLJY/cc-empire) | Complete Claude Code workflow scaffold (rules + hooks + agents) |

## License

MIT

## Contributing

Issues and PRs welcome. This project was born from a real need — if you're running multiple Claude Code sessions and wish they could talk to each other, this is for you.
