#!/usr/bin/env bash
# Claude Code Studio — CLI Status Check
# See who's online and task board without entering Claude Code

set -euo pipefail

STUDIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$STUDIO_DIR/.venv/bin"
BACKEND="${STUDIO_BACKEND:-redis}"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

STUDIO_BACKEND="$BACKEND" "$VENV/python" -c "
import os, time, datetime

backend = os.environ.get('STUDIO_BACKEND', 'sqlite')
if backend == 'redis':
    from studio import db_redis as db
else:
    from studio import db

db.init_db()

agents = db.list_agents()
tasks = db.get_tasks()

# Header
print()
print('  ╔══════════════════════════════════════╗')
print('  ║      Claude Code Studio Status       ║')
print('  ╚══════════════════════════════════════╝')
print()

# Agents
print('  AGENTS')
print('  ' + '─' * 40)
if not agents:
    print('  (no agents registered)')
else:
    for a in agents:
        status = a.get('status', 'unknown')
        icon = {'online': '🟢', 'offline': '⚫', 'busy': '🟡'}.get(status, '❓')
        role = f\" — {a['role']}\" if a.get('role') else ''
        print(f\"  {icon} {a['agent_id']} ({a['name']}{role})\")
print()

# Tasks
print('  TASK BOARD')
print('  ' + '─' * 40)
if not tasks:
    print('  (no tasks)')
else:
    for group_name in ['in_progress', 'pending', 'blocked', 'done']:
        group = [t for t in tasks if t.get('status') == group_name]
        if group:
            icon = {'in_progress': '🔄', 'pending': '⏳', 'blocked': '🚫', 'done': '✅'}.get(group_name, '❓')
            print(f\"  {icon} {group_name.replace('_', ' ').upper()}\")
            for t in group:
                prio = t.get('priority', 'medium').upper()
                print(f\"    #{t['id']} [{prio}] {t['title']} → {t.get('assigned_to', '?')} (by {t.get('assigned_by', '?')})\")
                if t.get('notes'):
                    print(f\"      Notes: {t['notes']}\")
print()

# Summary
online = len([a for a in agents if a.get('status') == 'online'])
active = len([t for t in tasks if t.get('status') in ('pending', 'in_progress')])
print(f'  {online} online / {len(agents)} total agents, {active} active tasks')
print(f'  Backend: {backend}')
print()
" 2>&1
