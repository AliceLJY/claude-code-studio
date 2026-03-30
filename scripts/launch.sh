#!/usr/bin/env bash
# ┌──────────────────────────────────────────────────┐
# │  Claude Code Studio — Launch Script              │
# │  Start the MCP server + tmux session with panes  │
# └──────────────────────────────────────────────────┘

set -euo pipefail

STUDIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="studio"
HOST="${STUDIO_HOST:-localhost}"
PORT="${STUDIO_PORT:-3777}"
VENV="$STUDIO_DIR/.venv/bin"
AGENT_COUNT="${1:-3}"  # default 3 worker agents

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Claude Code Studio — Launching...  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"

# ── 1. Kill old studio if running ───────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Existing studio session found. Killing it..."
    tmux kill-session -t "$SESSION"
fi

# Kill old MCP server if running
if lsof -ti:"$PORT" >/dev/null 2>&1; then
    echo "Killing old MCP server on port $PORT..."
    kill "$(lsof -ti:"$PORT")" 2>/dev/null || true
    sleep 1
fi

# ── 2. Start MCP server in background ──────────────
echo -e "${CYAN}Starting MCP server on $HOST:$PORT...${NC}"
STUDIO_HOST="$HOST" STUDIO_PORT="$PORT" \
    "$VENV/python" -m studio.server > /tmp/studio-server.log 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Wait for server to be ready
for i in $(seq 1 10); do
    if curl -sf --max-time 1 "http://$HOST:$PORT/sse" >/dev/null 2>&1 || lsof -ti:"$PORT" >/dev/null 2>&1; then
        echo -e "${GREEN}MCP server is ready.${NC}"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "ERROR: MCP server failed to start. Check /tmp/studio-server.log"
        exit 1
    fi
    sleep 0.5
done

# ── 2b. Start watcher daemon ───────────────────────
echo -e "${CYAN}Starting auto-kick watcher...${NC}"
"$VENV/python" -m studio.watcher > /tmp/studio-watcher.log 2>&1 &
WATCHER_PID=$!
echo "Watcher PID: $WATCHER_PID"

# ── 3. Create tmux session ─────────────────────────
echo -e "${CYAN}Creating tmux studio with 1 commander + $AGENT_COUNT agents...${NC}"

# Commander pane (window 0)
tmux new-session -d -s "$SESSION" -n "commander" \
    -e "STUDIO_PORT=$PORT" -e "STUDIO_HOST=$HOST" -e "STUDIO_AGENT_ID=commander"

# Agent panes (windows 1..N)
for i in $(seq 1 "$AGENT_COUNT"); do
    tmux new-window -t "$SESSION" -n "agent-$i" \
        -e "STUDIO_PORT=$PORT" -e "STUDIO_HOST=$HOST" -e "STUDIO_AGENT_ID=agent-$i"
done

# ── 4. Print instructions ──────────────────────────
echo ""
echo -e "${GREEN}Studio is ready!${NC}"
echo ""
echo "  tmux session: $SESSION"
echo "  MCP server:   http://$HOST:$PORT/sse"
echo "  Server log:   /tmp/studio-server.log"
echo "  Server PID:   $SERVER_PID"
echo ""
echo "  Windows:"
echo "    0: commander  — your main Claude Code session"
for i in $(seq 1 "$AGENT_COUNT"); do
    echo "    $i: agent-$i    — worker session"
done
echo ""
echo "  Quick start in each pane:"
echo "    claude  (then use studio MCP tools to register, message, etc.)"
echo ""
echo "  Add to your Claude Code settings.json or use /mcp in each session:"
echo "    {\"type\": \"sse\", \"url\": \"http://$HOST:$PORT/sse\"}"
echo ""
echo -e "${CYAN}Attaching to tmux session...${NC}"

# Select commander window and attach
tmux select-window -t "$SESSION:0"
tmux attach -t "$SESSION"

# When user detaches, offer to stop server
echo ""
read -p "Stop MCP server + watcher? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    kill "$SERVER_PID" 2>/dev/null && echo "Server stopped." || echo "Server already stopped."
    kill "$WATCHER_PID" 2>/dev/null && echo "Watcher stopped." || echo "Watcher already stopped."
fi
