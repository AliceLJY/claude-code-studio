# Claude Code Studio

> 多会话协作工作室：让多个 Claude Code 实例像团队一样协同工作。

> **状态 —— 实验性 / 个人项目。** 这是一个可运行的多会话 MCP 协作技术演示，不是
> 经过生产加固的工具。它能跑，但使用频率很低；下面的路线图是探索方向，不是承诺。

Claude Code Studio 把多个 Claude Code CLI 会话变成一个协作团队。一个会话负责策略和派活，其他会话分头执行，所有人通过共享的 MCP server 沟通。默认用 SQLite 保存状态；Redis 可增加 pub/sub 实时通知。

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
│            │ 状态 + MCP   │ ← 消息             │
│            │ Server       │    + 任务看板       │
│            └──────────────┘                   │
└──────────────────────────────────────────────┘
```

## 为什么需要这个？

你在 5 个 Claude Code 窗口里分头研究 5 个项目。做到一半发现它们互相依赖。你需要它们**能对话**。

这个实验把四件事组合在一个小型本机工具里：

- **派活** — 从指挥官向各 agent 分配任务
- **通信** — 任何 agent 之间互发消息（对等通信，不是只能和中心说话）
- **自动唤醒** — agent 收到消息后自动被叫醒干活（不用你切窗口）
- **全局态势** — 一个命令看清所有人在干什么

全部通过 MCP 工具实现，每个 CC 会话原生调用。

## 特性

- **一键启动** — 一个脚本启动 MCP server、watcher 守护进程和 tmux/Zellij 分窗，并在每个窗口启动 Claude
- **可选实时通信** — Redis pub/sub 即时推送通知；SQLite 模式每 5 秒轮询
- **对等通信** — 任何 agent 都能给任何 agent 发消息
- **任务管理** — 派活带优先级，状态追踪，完成自动通知
- **自动注册** — agent 启动时通过 CLAUDE.md 自动注册
- **实验性跨机器状态共享** — 多台机器可共用 Redis，但仍有下文所述的身份冲突限制
- **CLI 状态** — 终端直接查看态势，不用进 Claude Code
- **兼容跨模型审查** — 每个分窗仍是普通 Claude Code 会话，可继续使用 [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) 等兼容插件

## 快速开始

### 前置条件

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- tmux 或 [zellij](https://zellij.dev)（二选一）
- Redis —— **可选**，仅用于实时 pub/sub 推送（本机 Docker：`docker run -d -p 127.0.0.1:6379:6379 redis:7-alpine`）。默认 SQLite 后端不需要外部数据库服务。
- Claude Code CLI

### 安装

```bash
git clone https://github.com/AliceLJY/claude-code-studio.git
cd claude-code-studio
uv venv && uv pip install -e .
```

### 启动

第一次启动前，请先完成一次下文的[连接 Claude Code](#连接-claude-code)配置。

```bash
# 启动工作室：1 个指挥官 + 3 个 agent 窗口（默认）
./scripts/launch.sh

# 指定 agent 数量
./scripts/launch.sh 5

# 用 zellij 代替 tmux
STUDIO_MUX=zellij ./scripts/launch.sh
```

启动后会自动：
1. 启动 MCP Server
2. 启动 watcher 守护进程（收到消息自动踢醒 agent）
3. 创建 tmux 或 Zellij 会话和分窗
4. 每个窗口自动启动 `claude`
5. 每个 Claude 自动注册

坐在 commander 窗口说话即可——每个 agent 在 MCP 连接就绪后会通过项目 `CLAUDE.md` 自动注册。

### 查看状态（CLI）

```bash
# 不进 Claude Code 也能看谁在线、任务进展
./scripts/status.sh
```

### 连接 Claude Code

请在仓库目录中把 Studio server 加到 Claude Code 的本地项目 scope；启动脚本不会替你写这项配置：

```bash
claude mcp add --transport sse --scope local claude-code-studio http://localhost:3777/sse
```

Claude Code 目前仍支持 SSE，但官方 [MCP 文档](https://code.claude.com/docs/en/mcp#option-2-add-a-remote-sse-server) 已将它标为 deprecated，并推荐 Streamable HTTP。Studio 为保持 v0.3 兼容性暂时保留 SSE；传输迁移应放在独立版本里完成，而不是静默改 endpoint。

## 工作原理

```
Redis 模式示例——你说："让 agent-1 调研 MCP 框架"

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

SQLite 模式下 watcher 会改用轮询。两种模式的自动唤醒都是尽力而为，因为终端空闲判定本身是启发式的。

## MCP 工具

| 工具 | 说明 |
|------|------|
| `register` | 加入工作室 |
| `send_message` | 给指定 agent 发消息 |
| `broadcast` | 向除发送者外的已注册 agent 广播 |
| `check_inbox` | 查看收件箱 |
| `dispatch_task` | 派发任务（自动通知） |
| `update_task` | 更新任务状态（自动通知派活人） |
| `my_tasks` | 查看我的任务 |
| `studio_status` | 当前 agent 与任务看板 |
| `kick` | 远程踢醒 agent |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STUDIO_HOST` | `localhost` | MCP Server 监听地址 |
| `STUDIO_PORT` | `3777` | MCP Server 端口 |
| `STUDIO_BACKEND` | `sqlite` | 存储后端：`sqlite`（无需外部服务）或 `redis`（实时 pub/sub） |
| `STUDIO_MUX` | `tmux` | 终端复用器：`tmux` 或 `zellij` |
| `STUDIO_REDIS_URL` | `redis://localhost:6379` | Redis 连接地址 |
| `STUDIO_AUTO_KICK` | `1` | 设为 `0` 可关闭 watcher 的自动踢醒（空闲判定启发式可能误判） |
| `STUDIO_UNSAFE_REMOTE_MCP` | 未设置 | MCP server 绑定非本机地址前必须显式开启的无鉴权风险开关 |

## 安全边界

Studio 假设只有一个可信用户，运行在本机或可信私网。MCP endpoint 没有鉴权，工具参数里的 agent 身份也没有密码学验证，`kick` 还能向受管终端分窗输入提示。为避免误暴露，server 默认拒绝非 loopback 的 `STUDIO_HOST`；只有显式设置 `STUDIO_UNSAFE_REMOTE_MCP=1` 才会放行。不要把 MCP 或 Redis 端口暴露到公网。

## 跨机器协作

```bash
# 机器 A（你的 Mac）
STUDIO_BACKEND=redis STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh

# 机器 B（Mac Mini）
STUDIO_BACKEND=redis STUDIO_REDIS_URL=redis://192.168.1.100:6379 ./scripts/launch.sh 3
```

两台机器上的所有 agent 共享同一个消息总线和任务看板。

> **已知限制（实验性）。** agent ID 是固定的（`commander`、`agent-1`……），所以两台
> 机器这样启动会在 Redis 里撞同一批 ID、互相覆盖状态——目前没有真正的按机器隔离。
> 跨机器使用时需要自行配置 Redis 鉴权、网络过滤和加密；上面的本机 Docker 命令特意只监听 loopback。

## 定位

Studio 是面向可信本机环境的小型协作技术演示，不是安全的多租户 agent 平台。它真正提供的是 MCP 消息、任务看板、终端分窗启动和尽力而为的自动唤醒；它不提供模型上下文共享、强身份认证、权限控制、文件锁或持久工作流编排。

## 跨模型协作

Studio 本身没有直接集成 Codex。由于每个分窗仍是普通 Claude Code 会话，[codex-plugin-cc](https://github.com/openai/codex-plugin-cc) 等兼容插件仍可用于跨模型审查；具体安装方式和命令名以插件自己的 README 为准。

```
┌──────────────────────────────────────────────────┐
│              CLAUDE CODE STUDIO                   │
│                                                   │
│   Claude            写代码                         │
│       │                                           │
│       ▼                                           │
│   Codex             审查代码                       │
│       │                                           │
│       ▼                                           │
│   Claude            验证审查结论并修复              │
│                                                   │
│   Claude 与 Codex 在同一个工作区内协作。              │
└──────────────────────────────────────────────────┘
```

这项兼容能力来自 Claude Code；Studio 没有额外实现 Codex 专用传输或路由。

## 生态

**小试AI** 开源 AI 工作流生态的一部分：

| 项目 | 简介 |
|------|------|
| [recallnest](https://github.com/AliceLJY/recallnest) | MCP 记忆工作台（LanceDB + Jina v5） |
| [content-publisher](https://github.com/AliceLJY/content-publisher) | 配图 + 排版 + 公众号发布 |
| [openclaw-tunnel](https://github.com/AliceLJY/openclaw-tunnel) | Docker ↔ 宿主机 CLI 桥（/cc /codex /gemini） |
| [digital-clone-skill](https://github.com/AliceLJY/digital-clone-skill) | 用语料构建数字分身 |
| [telegram-ai-bridge](https://github.com/AliceLJY/telegram-ai-bridge) | Claude / Codex / Gemini 的 Telegram bot |
| [cc-empire](https://github.com/AliceLJY/cc-empire) | 完整的 Claude Code 工作流脚手架（规则 + 钩子 + agent） |

## 许可证

MIT

## 开发验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q studio tests
bash -n scripts/launch.sh scripts/launch-zellij.sh scripts/status.sh
```
