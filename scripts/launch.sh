#!/usr/bin/env bash
# ┌──────────────────────────────────────────────────┐
# │  Claude Code Studio — Launch Script              │
# │  Start the MCP server + tmux session with panes  │
# └──────────────────────────────────────────────────┘

set -euo pipefail

STUDIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$STUDIO_DIR/scripts/runtime-state.sh"

# ── Multiplexer selection ──────────────────────────
MUX="${STUDIO_MUX:-tmux}"
case "$MUX" in
    zellij) exec "$STUDIO_DIR/scripts/launch-zellij.sh" "$@" ;;
    tmux) ;;
    *) echo "ERROR: STUDIO_MUX must be 'tmux' or 'zellij' (got '$MUX')." >&2; exit 2 ;;
esac

SESSION="studio"
HOST="${STUDIO_HOST:-localhost}"
PORT="${STUDIO_PORT:-3777}"
BACKEND="${STUDIO_BACKEND:-sqlite}"  # sqlite (default, no external datastore) or redis
VENV="$STUDIO_DIR/.venv/bin"
AGENT_COUNT="${1:-3}"  # default 3 worker agents

case "$BACKEND" in
    sqlite|redis) ;;
    *) echo "ERROR: STUDIO_BACKEND must be 'sqlite' or 'redis' (got '$BACKEND')." >&2; exit 2 ;;
esac
if ! [[ "$AGENT_COUNT" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: agent count must be a positive integer (got '$AGENT_COUNT')." >&2
    exit 2
fi
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "ERROR: STUDIO_PORT must be an integer from 1 to 65535 (got '$PORT')." >&2
    exit 2
fi
case "$HOST" in
    localhost|127.*|::1|\[::1\]) ;;
    *)
        if [[ ! "${STUDIO_UNSAFE_REMOTE_MCP:-}" =~ ^(1|true|yes)$ ]]; then
            echo "ERROR: refusing unauthenticated MCP bind on non-loopback host '$HOST'." >&2
            echo "  Keep STUDIO_HOST local or explicitly set STUDIO_UNSAFE_REMOTE_MCP=1." >&2
            exit 2
        fi
        ;;
esac

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Claude Code Studio — Launching...  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"

# Never assume a listener on the configured port belongs to Studio.
LISTENER_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$LISTENER_PIDS" ]; then
    echo "ERROR: port $PORT is already in use by PID(s): ${LISTENER_PIDS//$'\n'/, }." >&2
    echo "  Stop the existing service or choose another STUDIO_PORT." >&2
    exit 1
fi

# ── 1c. Preflight: give a concise Redis error before background launch ──
# The server independently fails closed if the backend becomes unavailable.
if [ "$BACKEND" = "redis" ]; then
    if ! "$VENV/python" -c "import os,redis; redis.Redis.from_url(os.environ.get('STUDIO_REDIS_URL','redis://localhost:6379'), socket_connect_timeout=2).ping()" 2>/dev/null; then
        echo "ERROR: STUDIO_BACKEND=redis but the configured Redis endpoint is unreachable." >&2
        echo "  Start it locally: docker run -d -p 127.0.0.1:6379:6379 redis:7-alpine" >&2
        echo "  Or use the no-service default: STUDIO_BACKEND=sqlite $0 $*" >&2
        exit 1
    fi
    echo -e "${GREEN}Redis reachable.${NC}"
fi

# ── 1. Replace the named Studio multiplexer session ─────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Existing studio session found. Replacing it..."
    tmux kill-session -t "$SESSION"
fi

# ── 2. Start MCP server in background ──────────────
studio_prepare_runtime_dir
SERVER_LOG="$STUDIO_RUNTIME_DIR/studio-server.log"
WATCHER_LOG="$STUDIO_RUNTIME_DIR/studio-watcher.log"
echo -e "${CYAN}Starting MCP server on $HOST:$PORT (backend: $BACKEND)...${NC}"
STUDIO_HOST="$HOST" STUDIO_PORT="$PORT" STUDIO_BACKEND="$BACKEND" \
    "$VENV/python" -m studio.server > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

cleanup_on_failure() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        [ -z "${WATCHER_PID:-}" ] || kill "$WATCHER_PID" >/dev/null 2>&1 || true
        kill "$SERVER_PID" >/dev/null 2>&1 || true
        tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION" || true
    fi
}
trap cleanup_on_failure EXIT

# Wait for server to be ready
for i in $(seq 1 10); do
    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
        echo "ERROR: MCP server exited during startup. Check $SERVER_LOG" >&2
        exit 1
    fi
    if curl -sf --max-time 1 "http://$HOST:$PORT/sse" >/dev/null 2>&1 \
        || lsof -a -p "$SERVER_PID" -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}MCP server is ready.${NC}"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "ERROR: MCP server failed to start. Check $SERVER_LOG"
        exit 1
    fi
    sleep 0.5
done

# ── 2b. Start watcher daemon ───────────────────────
echo -e "${CYAN}Starting auto-kick watcher ($BACKEND mode)...${NC}"
STUDIO_BACKEND="$BACKEND" "$VENV/python" -u -m studio.watcher > "$WATCHER_LOG" 2>&1 &
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

# ── 3b. Auto-start claude in all windows ──────────
sleep 1
echo -e "${CYAN}Starting Claude in all windows...${NC}"
tmux send-keys -t "$SESSION:commander" "claude" Enter
for i in $(seq 1 "$AGENT_COUNT"); do
    tmux send-keys -t "$SESSION:agent-$i" "claude" Enter
done

# ── 4. Print instructions ──────────────────────────
echo ""
echo -e "${GREEN}Studio is ready!${NC}"
echo ""
echo "  tmux session: $SESSION"
echo "  MCP server:   http://$HOST:$PORT/sse"
echo "  Server log:   $SERVER_LOG"
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
echo "  Configure Claude Code once from this repository:"
echo "    claude mcp add --transport sse --scope local claude-code-studio http://$HOST:$PORT/sse"
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
