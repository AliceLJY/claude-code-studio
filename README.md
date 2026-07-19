# Claude Code Studio

> Multi-session collaboration studio for Claude Code. Run multiple CC instances as a coordinated team.

> **Status — experimental / personal project.** A working technical demo of
> multi-session MCP coordination, not a hardened production tool. It runs, but
> it is lightly used; treat the roadmap below as exploration, not commitments.

Claude Code Studio turns multiple Claude Code CLI sessions into a collaborative team. One session dispatches tasks, others execute, and everyone communicates through a shared MCP server. SQLite is the default state backend; Redis adds pub/sub delivery.

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
│            │  State + MCP │ ← messages       │
│            │  Server      │    + task board   │
│            └──────────────┘                  │
└─────────────────────────────────────────────┘
```

## Why?

You're researching 5 projects across 5 Claude Code sessions. Halfway through, you realize they depend on each other. Now you need them to **talk**.

This experiment combines four things in one small local tool:

- **Dispatch tasks** from a commander to worker agents
- **Exchange messages** between any agents (peer-to-peer, not just hub-and-spoke)
- **Auto-wake agents** when they receive messages (no manual window switching)
- **See the big picture** with a single command

All through MCP tools that every Claude Code session can call natively.

## Features

- **One-click launch** — one script starts the MCP server, watcher daemon, and tmux or Zellij panes with Claude Code auto-started in each
- **Optional real-time messaging** — Redis pub/sub delivers notifications instantly; SQLite mode polls every five seconds
- **Peer-to-peer** — any agent can message any other agent, not just commander → worker
- **Task dispatch & tracking** — assign tasks with priority, track status, auto-notify on completion
- **Auto-registration** — agents register themselves on startup via project CLAUDE.md
- **Experimental cross-machine state** — multiple machines can share Redis, with the identity-collision limitations documented below
- **CLI status tool** — check studio status from terminal without entering Claude Code
- **Cross-model compatibility** — ordinary Claude Code panes can keep using compatible plugins such as [codex-plugin-cc](https://github.com/openai/codex-plugin-cc)

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- tmux or [zellij](https://zellij.dev) (either one works)
- Redis — **optional**, only for real-time pub/sub delivery (local Docker: `docker run -d -p 127.0.0.1:6379:6379 redis:7-alpine`). The default SQLite backend needs no external datastore.
- Claude Code CLI

### Install

```bash
git clone https://github.com/AliceLJY/claude-code-studio.git
cd claude-code-studio
uv venv && uv pip install -e .
```

### Launch

Configure the MCP connection once (see [Connect Claude Code](#connect-claude-code)) before the first launch.

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
3. Create a tmux or Zellij session with separate panes
4. Auto-start `claude` in every window
5. Each Claude auto-registers itself on startup

Sit in the commander window and talk — each agent auto-registers via the project `CLAUDE.md` once its MCP connection is up.

### Check Status (CLI)

```bash
# See who's online and task board without entering Claude Code
./scripts/status.sh
```

### Connect Claude Code

From the repository directory, add the Studio server to Claude Code's local project scope (the launcher does not write this configuration):

```bash
claude mcp add --transport sse --scope local claude-code-studio http://localhost:3777/sse
```

Claude Code still supports SSE, but its [MCP documentation](https://code.claude.com/docs/en/mcp#option-2-add-a-remote-sse-server) now marks SSE as deprecated in favor of Streamable HTTP. Studio retains SSE for v0.3 compatibility; a transport migration should be a separate release rather than an undocumented endpoint change.

## How It Works

```
Redis mode example — you say: "Tell agent-1 to research MCP frameworks"

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

In SQLite mode the watcher polls instead of subscribing to Redis. Auto-wake is best-effort in both modes because terminal-idle detection is heuristic.

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
           │ SQLite / Redis │◄───►│   Watcher    │
           │  state backend │     │  (auto-kick) │
           └────────────────┘     └──────────────┘
```

- **MCP Server**: FastMCP with SSE transport — multiple CC sessions connect to one server
- **Redis**: Message storage + pub/sub for instant delivery. Messages TTL 24h, tasks TTL 72h.
- **Watcher**: Subscribes to Redis pub/sub or polls SQLite, then auto-sends prompts to panes it believes are idle
- **Backend**: SQLite by default (no external datastore). Set `STUDIO_BACKEND=redis` for real-time pub/sub delivery (requires a running Redis)

## MCP Tools

| Tool | Description |
|------|-------------|
| `register` | Join the studio with a unique ID and role |
| `unregister` | Leave the studio |
| `send_message` | Direct message another agent |
| `broadcast` | Message all other registered agents |
| `check_inbox` | Read your messages |
| `dispatch_task` | Assign a task to an agent (auto-notifies) |
| `update_task` | Update task status (auto-notifies dispatcher) |
| `my_tasks` | List your assigned tasks |
| `studio_status` | Current agents and task board |
| `kick` | Wake up an agent remotely via tmux |
| `heartbeat` | Signal you're still active |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `STUDIO_HOST` | `localhost` | MCP server bind address |
| `STUDIO_PORT` | `3777` | MCP server port |
| `STUDIO_BACKEND` | `sqlite` | Storage backend: `sqlite` (no external service) or `redis` (real-time pub/sub) |
| `STUDIO_REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `STUDIO_MUX` | `tmux` | Terminal multiplexer: `tmux` or `zellij` |
| `STUDIO_STATE_DIR` | private per-user runtime directory | Runtime logs, Zellij layout, pane map, and pane wrappers |
| `STUDIO_DB_PATH` | `~/.claude-code-studio/studio.db` | SQLite database path (sqlite mode) |
| `STUDIO_AUTO_KICK` | `1` | Set to `0` to stop the watcher from auto-kicking agents (the idle heuristic can misfire) |
| `STUDIO_UNSAFE_REMOTE_MCP` | unset | Explicit opt-in required before binding the unauthenticated MCP server to a non-loopback host |

## Security Model

Studio assumes one trusted user on one machine or trusted private network. The MCP endpoint has no authentication, tool-supplied agent identities are not cryptographically verified, and `kick` can type a prompt into a managed terminal pane. The server therefore refuses a non-loopback `STUDIO_HOST` unless `STUDIO_UNSAFE_REMOTE_MCP=1` is explicitly set. Do not expose the MCP or Redis ports to the public internet.

## Cross-Machine Setup

Run agents on different machines by pointing to a shared Redis:

```bash
# Machine A (your Mac)
STUDIO_BACKEND=redis STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh

# Machine B (Mac Mini)
STUDIO_BACKEND=redis STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh 3
```

All agents across both machines share the same message bus and task board.

> **Known limitations (experimental).** Agent IDs are fixed (`commander`,
> `agent-1`, …), so two machines launched this way collide on the same IDs in
> Redis and overwrite each other's state — there is no real per-machine
> isolation yet. For cross-machine use, configure Redis authentication, network
> filtering, and encryption appropriate to your network; the local Docker command
> above intentionally listens on loopback only.

## Positioning

Studio is a small trusted-local coordination demo, not a secure multi-tenant agent platform. Its useful combination is MCP messaging, a task board, terminal-pane launch, and best-effort auto-wake. It does **not** provide shared model context, strong agent identity, authorization, file locks, or durable workflow orchestration.

## Cross-Model Collaboration

Studio does not integrate with Codex directly. Each pane is an ordinary Claude Code session, so compatible Claude Code plugins such as [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) can still be used for a cross-model review workflow. Follow the plugin's own README for its current installation and command names.

```
┌─────────────────────────────────────────────────┐
│              CLAUDE CODE STUDIO                  │
│                                                  │
│   Claude            writes code                  │
│       │                                          │
│       ▼                                          │
│   Codex             reviews code                │
│       │                                          │
│       ▼                                          │
│   Claude            verifies findings & fixes    │
│                                                  │
│   Review stays in the same workspace.             │
└─────────────────────────────────────────────────┘
```

This compatibility is inherited from Claude Code; Studio itself adds no Codex-specific transport or routing.

## Ecosystem

Part of AliceLJY's open-source AI workflow:

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

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q studio tests
bash -n scripts/launch.sh scripts/launch-zellij.sh scripts/status.sh
```

## Contributing

Issues and PRs welcome. This project was born from a real need — if you're running multiple Claude Code sessions and wish they could talk to each other, this is for you.
