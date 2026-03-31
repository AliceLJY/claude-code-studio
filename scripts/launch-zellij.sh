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
BACKEND="${STUDIO_BACKEND:-redis}"
VENV="$STUDIO_DIR/.venv/bin"
AGENT_COUNT="${1:-3}"
LAYOUT_FILE="/tmp/studio-layout.kdl"
PANE_MAP="/tmp/studio-zellij-panes.json"

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Claude Code Studio — Zellij Mode    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"

# ── 1. Kill old studio if running ───────────────────
if zellij list-sessions -n -s 2>/dev/null | grep -q "^${SESSION}$"; then
    echo "Existing zellij studio session found. Killing it..."
    zellij delete-session "$SESSION" --force 2>/dev/null || true
fi

# Kill old MCP server if running
if lsof -ti:"$PORT" >/dev/null 2>&1; then
    echo "Killing old MCP server on port $PORT..."
    kill "$(lsof -ti:"$PORT")" 2>/dev/null || true
    sleep 1
fi

# ── 2. Start MCP server in background ──────────────
echo -e "${CYAN}Starting MCP server on $HOST:$PORT (backend: $BACKEND)...${NC}"
STUDIO_HOST="$HOST" STUDIO_PORT="$PORT" STUDIO_BACKEND="$BACKEND" \
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
echo -e "${CYAN}Starting auto-kick watcher ($BACKEND mode, zellij mux)...${NC}"
STUDIO_BACKEND="$BACKEND" STUDIO_MUX="zellij" "$VENV/python" -u -m studio.watcher > /tmp/studio-watcher.log 2>&1 &
WATCHER_PID=$!
echo "Watcher PID: $WATCHER_PID"

# ── 3. Generate zellij layout ─────────────────────
echo -e "${CYAN}Generating zellij layout for 1 commander + $AGENT_COUNT agents...${NC}"

cat > "$LAYOUT_FILE" <<KDLEOF
layout {
    tab name="commander" focus=true {
        pane name="commander" command="claude" {
            env STUDIO_PORT "$PORT"
            env STUDIO_HOST "$HOST"
            env STUDIO_AGENT_ID "commander"
            env STUDIO_MUX "zellij"
        }
    }
KDLEOF

for i in $(seq 1 "$AGENT_COUNT"); do
    cat >> "$LAYOUT_FILE" <<KDLEOF
    tab name="agent-$i" {
        pane name="agent-$i" command="claude" {
            env STUDIO_PORT "$PORT"
            env STUDIO_HOST "$HOST"
            env STUDIO_AGENT_ID "agent-$i"
            env STUDIO_MUX "zellij"
        }
    }
KDLEOF
done

echo "}" >> "$LAYOUT_FILE"

# ── 4. Write pane map (pane IDs are sequential from layout) ──
echo -n "{" > "$PANE_MAP"
echo -n "\"commander\": 0" >> "$PANE_MAP"
for i in $(seq 1 "$AGENT_COUNT"); do
    echo -n ", \"agent-$i\": $i" >> "$PANE_MAP"
done
echo "}" >> "$PANE_MAP"
echo "Pane map written to $PANE_MAP"

# ── 5. Print instructions ──────────────────────────
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
echo ""

# ── 6. Launch zellij (blocks until detach) ─────────
zellij --session "$SESSION" --layout "$LAYOUT_FILE"

# When user detaches, offer to stop server
echo ""
read -p "Stop MCP server + watcher? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    kill "$SERVER_PID" 2>/dev/null && echo "Server stopped." || echo "Server already stopped."
    kill "$WATCHER_PID" 2>/dev/null && echo "Watcher stopped." || echo "Watcher already stopped."
fi
