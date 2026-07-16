#!/usr/bin/env bash
# ┌──────────────────────────────────────────────────┐
# │  Claude Code Studio — Zellij Launch Script       │
# │  Start the MCP server + zellij session           │
# └──────────────────────────────────────────────────┘

set -euo pipefail

STUDIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="studio"
HOST="${STUDIO_HOST:-localhost}"
PORT="${STUDIO_PORT:-3777}"
BACKEND="${STUDIO_BACKEND:-sqlite}"  # sqlite (default, no external datastore) or redis
VENV="$STUDIO_DIR/.venv/bin"
AGENT_COUNT="${1:-3}"
LAYOUT_FILE="/tmp/studio-layout.kdl"
PANE_MAP="/tmp/studio-zellij-panes.json"

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
echo -e "${GREEN}║  Claude Code Studio — Zellij Mode    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"

LISTENER_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$LISTENER_PIDS" ]; then
    echo "ERROR: port $PORT is already in use by PID(s): ${LISTENER_PIDS//$'\n'/, }." >&2
    echo "  Stop the existing service or choose another STUDIO_PORT." >&2
    exit 1
fi

# ── 1c. Preflight: if redis backend requested, verify it's reachable ──
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
if zellij list-sessions -n -s 2>/dev/null | grep -q "^${SESSION}$"; then
    echo "Existing zellij studio session found. Replacing it..."
    zellij delete-session "$SESSION" --force 2>/dev/null || true
fi

# ── 2. Start MCP server in background ──────────────
echo -e "${CYAN}Starting MCP server on $HOST:$PORT (backend: $BACKEND)...${NC}"
STUDIO_HOST="$HOST" STUDIO_PORT="$PORT" STUDIO_BACKEND="$BACKEND" \
    "$VENV/python" -m studio.server > /tmp/studio-server.log 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

cleanup_on_failure() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        [ -z "${WATCHER_PID:-}" ] || kill "$WATCHER_PID" >/dev/null 2>&1 || true
        kill "$SERVER_PID" >/dev/null 2>&1 || true
        zellij delete-session "$SESSION" --force >/dev/null 2>&1 || true
    fi
}
trap cleanup_on_failure EXIT

# Wait for server to be ready
for i in $(seq 1 10); do
    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
        echo "ERROR: MCP server exited during startup. Check /tmp/studio-server.log" >&2
        exit 1
    fi
    if curl -sf --max-time 1 "http://$HOST:$PORT/sse" >/dev/null 2>&1 \
        || lsof -a -p "$SERVER_PID" -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
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
echo -e "${CYAN}Starting auto-kick watcher ($BACKEND mode, zellij mux)...${NC}"
STUDIO_BACKEND="$BACKEND" STUDIO_MUX="zellij" "$VENV/python" -u -m studio.watcher > /tmp/studio-watcher.log 2>&1 &
WATCHER_PID=$!
echo "Watcher PID: $WATCHER_PID"

# ── 3. Generate per-pane wrapper scripts ──────────
echo -e "${CYAN}Generating zellij layout for 1 commander + $AGENT_COUNT agents...${NC}"

make_pane_script() {
    local agent_id="$1"
    local script="/tmp/studio-pane-${agent_id}.sh"
    cat > "$script" <<SCRIPTEOF
#!/usr/bin/env zsh -il
export STUDIO_PORT="$PORT"
export STUDIO_HOST="$HOST"
export STUDIO_AGENT_ID="$agent_id"
export STUDIO_MUX="zellij"
claude
SCRIPTEOF
    chmod +x "$script"
    echo "$script"
}

COMMANDER_SCRIPT="$(make_pane_script commander)"
AGENT_SCRIPTS=()
for i in $(seq 1 "$AGENT_COUNT"); do
    AGENT_SCRIPTS+=("$(make_pane_script "agent-$i")")
done

# ── 4. Generate zellij layout (minimal KDL) ──────
cat > "$LAYOUT_FILE" <<KDLEOF
layout {
    tab name="commander" focus=true {
        pane command="$COMMANDER_SCRIPT"
    }
KDLEOF

for i in $(seq 1 "$AGENT_COUNT"); do
    cat >> "$LAYOUT_FILE" <<KDLEOF
    tab name="agent-$i" {
        pane command="${AGENT_SCRIPTS[$((i-1))]}"
    }
KDLEOF
done

echo "}" >> "$LAYOUT_FILE"

# ── 5. Write pane map ──
echo -n "{" > "$PANE_MAP"
echo -n "\"commander\": 0" >> "$PANE_MAP"
for i in $(seq 1 "$AGENT_COUNT"); do
    echo -n ", \"agent-$i\": $i" >> "$PANE_MAP"
done
echo "}" >> "$PANE_MAP"
echo "Pane map written to $PANE_MAP"

# ── 6. Print instructions ──────────────────────────
echo ""
echo -e "${GREEN}Launching zellij studio...${NC}"
echo ""
echo "  Session:      $SESSION"
echo "  MCP server:   http://$HOST:$PORT/sse"
echo "  Server log:   /tmp/studio-server.log"
echo "  Server PID:   $SERVER_PID"
echo "  Pane map:     $PANE_MAP"
echo ""
echo "  Tabs:"
echo "    0: commander  — your main Claude Code session"
for i in $(seq 1 "$AGENT_COUNT"); do
    echo "    $i: agent-$i    — worker session"
done
echo ""
echo "  Detach: Ctrl+O, D"
echo "  Reattach: zellij attach $SESSION"
echo "  Configure Claude Code once from this repository:"
echo "    claude mcp add --transport sse --scope local claude-code-studio http://$HOST:$PORT/sse"
echo ""

# ── 7. Launch zellij (blocks until detach) ─────────
zellij -s "$SESSION" -n "$LAYOUT_FILE"

# When user detaches, offer to stop server
echo ""
read -p "Stop MCP server + watcher? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    kill "$SERVER_PID" 2>/dev/null && echo "Server stopped." || echo "Server already stopped."
    kill "$WATCHER_PID" 2>/dev/null && echo "Watcher stopped." || echo "Watcher already stopped."
fi
