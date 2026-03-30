# Claude Code Studio — Roadmap

## v0.1 ✅ Done (2026-03-30)
- [x] MCP Server (FastMCP + SSE)
- [x] Agent register/unregister/heartbeat
- [x] Send message / broadcast / check inbox
- [x] Task dispatch + status tracking + auto-notify
- [x] Studio status overview
- [x] tmux one-click launcher with auto-start claude
- [x] Auto-register via CLAUDE.md
- [x] Watcher daemon (SQLite polling)
- [x] Kick tool (remote wake via tmux)
- [x] CLI status tool (scripts/status.sh)
- [x] Desktop shortcut

## v0.2 ✅ Done (2026-03-31)
- [x] Redis backend with pub/sub (instant delivery)
- [x] Watcher uses pub/sub instead of polling
- [x] SQLite/Redis backend switchable via env var
- [x] Cross-machine ready (shared Redis URL)

## v0.3 — UX Polish
- [ ] Agent 启动时自动 check_inbox（不等 watcher 踢）
- [ ] Watcher 检测 agent 忙碌时排队，空闲后再踢
- [ ] 消息已读回执（sender 知道对方看了没）
- [ ] Studio status 显示最近 N 条消息摘要
- [ ] 启动时可选 agent 数量的交互式提示

## v0.4 — File Coordination
- [ ] 文件锁（lock_file / unlock_file / check_locks）
- [ ] Agent 编辑文件前自动检查锁
- [ ] 锁超时自动释放（防止 agent 崩溃后死锁）
- [ ] Studio status 显示当前文件锁状态

## v0.5 — Observability
- [ ] Web dashboard（浏览器看态势图）
- [ ] 消息历史查询（按时间/agent/关键词）
- [ ] Agent 活动日志（谁在什么时候干了什么）
- [ ] Task 完成统计（耗时、成功率）

## v0.6 — Cross-Machine
- [ ] SSH 远程 agent 支持（Mac Mini 场景）
- [ ] launch.sh 支持 remote host 参数
- [ ] Agent 健康检查（跨机器心跳监控）
- [ ] 断线重连 + 消息不丢失

## v0.7 — Smart Orchestration
- [ ] 任务依赖（Task B 等 Task A 完成才开始）
- [ ] Agent 能力声明（"我擅长前端"）
- [ ] 自动任务分配（根据能力匹配 agent）
- [ ] Commander 可以定义 workflow（多步编排）

## Ideas (Backlog)
- Agent 自带 system prompt 定制（不同角色不同人格）
- 与 RecallNest 集成（共享跨 session 记忆）
- GIF/截图自动生成（用 Peekaboo 截 tmux）
- npm/pip 一键安装（`uvx claude-code-studio`）
- VS Code 扩展（侧边栏看 studio 状态）
