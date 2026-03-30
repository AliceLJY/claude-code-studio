# Claude Code Studio

> 多会话协作工作室：让多个 Claude Code 实例像团队一样协同工作。

Claude Code Studio 把多个 Claude Code CLI 会话变成一个协作团队。一个会话负责策略和派活，其他会话分头执行——所有人通过共享 MCP Server 实时沟通。

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
│            │  共享 MCP    │ ← 消息总线         │
│            │  Server      │    + 任务看板       │
│            └──────────────┘                   │
└──────────────────────────────────────────────┘
```

## 为什么需要这个？

你在 5 个 Claude Code 窗口里分头研究 5 个项目。做到一半发现它们互相依赖。现在你需要它们**能对话**。

现有方案解决了一部分（消息、文件锁、任务队列），但没有一个做到完整体验：**派活、通信、看全局态势——全部通过 MCP 工具，每个 CC 会话原生调用。**

## 快速开始

### 前置条件

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- tmux
- Claude Code CLI

### 安装

```bash
git clone https://github.com/AliceLJY/claude-code-studio.git
cd claude-code-studio
uv venv && uv pip install -e .
```

### 启动

```bash
# 启动工作室：1 个指挥官 + 3 个 agent 窗口
./scripts/launch.sh

# 指定 agent 数量
./scripts/launch.sh 5
```

启动后会：
1. 在 `localhost:3777` 启动 MCP Server
2. 创建 tmux 会话，分窗口放置指挥官和各 agent
3. 自动进入 tmux 会话

### 连接 Claude Code

在每个 Claude Code 会话中添加 Studio MCP Server：

**方式 A：在 Claude Code 中使用 `/mcp` 命令**
```
/mcp
# 添加 SSE 服务器：http://localhost:3777/sse
```

**方式 B：写入 settings.json**
```json
{
  "mcpServers": {
    "claude-code-studio": {
      "type": "sse",
      "url": "http://localhost:3777/sse"
    }
  }
}
```

## MCP 工具

连接后，每个 Claude Code 会话可以使用这些工具：

| 工具 | 说明 |
|------|------|
| `register` | 加入工作室（注册唯一 ID 和角色） |
| `unregister` | 离开工作室 |
| `send_message` | 给指定 agent 发消息 |
| `broadcast` | 全员广播 |
| `check_inbox` | 查看收件箱 |
| `dispatch_task` | 派发任务 |
| `update_task` | 更新任务状态 |
| `my_tasks` | 查看我的任务 |
| `studio_status` | 全局态势一览 |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STUDIO_HOST` | `localhost` | MCP Server 监听地址 |
| `STUDIO_PORT` | `3777` | MCP Server 端口 |
| `STUDIO_DB_PATH` | `~/.claude-code-studio/studio.db` | 数据库文件路径 |

## 许可证

MIT
