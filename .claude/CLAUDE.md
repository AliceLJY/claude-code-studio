# Claude Code Studio — Auto Setup

You are inside a Claude Code Studio session. On startup, you MUST:

1. Check the environment variable `STUDIO_AGENT_ID` (run: `echo $STUDIO_AGENT_ID`)
2. Call the `register` MCP tool with:
   - `agent_id`: the value of `STUDIO_AGENT_ID`
   - `name`: a friendly name based on the ID (e.g. "commander" → "总指挥", "agent-1" → "研究员", "agent-2" → "开发者")
   - `role`: pick a suitable role based on the name
3. After registering, call `check_inbox` to see if there are pending messages or tasks

Do this silently and quickly — no need to explain what you're doing.

## How to communicate

- Check inbox regularly (after completing work, or when asked)
- When you finish a task, use `update_task` to report status — this auto-notifies the dispatcher
- Use `send_message` to talk to specific agents
- Use `broadcast` for announcements to everyone
- Use `studio_status` to see the big picture
