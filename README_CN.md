# Claude Code Studio

> 多会话协作工作室：让多个 Claude Code 实例像团队一样协同工作。

Claude Code Studio 把多个 Claude Code CLI 会话变成一个协作团队。一个会话负责策略和派活，其他会话分头执行——所有人通过 Redis pub/sub 实时沟通。

```
┌──────────────────────────────────────────────┐
│             CLAUDE CODE STUDIO                │
│                                               │
│   [你 + 指挥官]  ← 讨论策略、派活、决策         │
│       │                                       │
│       ├── Agent A (调研)         [在线]        │
│       ├── Agent B (后端)         [在线]        │
│       ├── Agent C (前端)         [忙碌]        │
│       └── Agent D (测试)         [离线]        │
│                                               │
│   Agent A → Agent B: "API 接口改了，同步一下"   │
│   Agent B → Agent A: "收到，正在更新"           │
│                                               │
│            ┌──────────────┐                   │
│            │ Redis + MCP  │ ← pub/sub 消息总线 │
│            │ Server       │    + 任务看板       │
│            └──────────────┘                   │
└──────────────────────────────────────────────┘
```

## 为什么需要这个？

你在 5 个 Claude Code 窗口里分头研究 5 个项目。做到一半发现它们互相依赖。你需要它们**能对话**。

现有方案解决了一部分，但没有一个做到完整体验：

- **派活** — 从指挥官向各 agent 分配任务
- **通信** — 任何 agent 之间互发消息（对等通信，不是只能和中心说话）
- **自动唤醒** — agent 收到消息后自动被叫醒干活（不用你切窗口）
- **全局态势** — 一个命令看清所有人在干什么

全部通过 MCP 工具实现，每个 CC 会话原生调用。

## 特性

- **一键启动** — 一个脚本搞定：MCP server + watcher 守护进程 + tmux 分窗 + 每个窗口自动启动 Claude
- **实时通信** — Redis pub/sub 即时推送，watcher 自动踢醒空闲 agent
- **对等通信** — 任何 agent 都能给任何 agent 发消息
- **任务管理** — 派活带优先级，状态追踪，完成自动通知
- **自动注册** — agent 启动时通过 CLAUDE.md 自动注册
- **跨机器** — 改一下 `STUDIO_REDIS_URL` 就能跨机器协作
- **CLI 状态** — 终端直接查看态势，不用进 Claude Code

## 快速开始

### 前置条件

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- tmux
- Redis（Docker: `docker run -d -p 6379:6379 redis:7-alpine`）
- Claude Code CLI

### 安装

```bash
git clone https://github.com/AliceLJY/claude-code-studio.git
cd claude-code-studio
uv venv && uv pip install -e .
```

### 启动

```bash
# 启动工作室：1 个指挥官 + 3 个 agent 窗口（默认）
./scripts/launch.sh

# 指定 agent 数量
./scripts/launch.sh 5
```

启动后会自动：
1. 启动 MCP Server
2. 启动 watcher 守护进程（收到消息自动踢醒 agent）
3. 创建 tmux 分窗
4. 每个窗口自动启动 `claude`
5. 每个 Claude 自动注册

**你只管坐在 commander 窗口说话就行。**

### 查看状态（CLI）

```bash
# 不进 Claude Code 也能看谁在线、任务进展
./scripts/status.sh
```

## 工作原理

```
你说："让 agent-1 调研 MCP 框架"

Commander CC                    Watcher 守护进程            Agent-1 CC
     │                               │                          │
     ├─ send_message(agent-1) ──────►│                          │
     │       │                       │                          │
     │       └─► Redis PUBLISH ─────►│                          │
     │                               ├─ tmux send-keys ───────►│
     │                               │  "查收件箱"               │
     │                               │                          ├─ check_inbox()
     │                               │                          ├─ (开始调研)
     │                               │                          ├─ send_message(commander)
     │                               │                          │       │
     │                          ◄────┤◄─ Redis PUBLISH ─────────┘       │
     │◄─ tmux send-keys ────────┤    │                                  │
     │   "查收件箱"              │    │                                  │
     ├─ check_inbox() ──────────┘    │                                  │
     ├─ "agent-1 说：..."           │                                  │
```

不用切窗口。消息自动流转。

## MCP 工具

| 工具 | 说明 |
|------|------|
| `register` | 加入工作室 |
| `send_message` | 给指定 agent 发消息 |
| `broadcast` | 全员广播 |
| `check_inbox` | 查看收件箱 |
| `dispatch_task` | 派发任务（自动通知） |
| `update_task` | 更新任务状态（自动通知派活人） |
| `my_tasks` | 查看我的任务 |
| `studio_status` | 全局态势一览 |
| `kick` | 远程踢醒 agent |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STUDIO_HOST` | `localhost` | MCP Server 监听地址 |
| `STUDIO_PORT` | `3777` | MCP Server 端口 |
| `STUDIO_BACKEND` | `redis` | 存储后端：`redis` 或 `sqlite` |
| `STUDIO_REDIS_URL` | `redis://localhost:6379` | Redis 连接地址 |

## 跨机器协作

```bash
# 机器 A（你的 Mac）
STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh

# 机器 B（Mac Mini）
STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh 3
```

两台机器上的所有 agent 共享同一个消息总线和任务看板。

## 许可证

MIT
