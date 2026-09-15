# workflow-fishbowl：Codex 与 Claude Code 本地监控面板

workflow-fishbowl 是一个本地、只读的 AI Agent 可观测性工具，支持查看
Codex 和 Claude Code 的长任务状态。

它可以帮助你：

- 监控 AI 编程任务是否仍在运行
- 查看当前工具调用和活动时间线
- 识别可能卡住的工具调用
- 查看 Token 用量和成本估算
- 在不上传 transcript 的前提下观察本地会话

项目主页：[workflow-fishbowl](https://github.com/zonion088-design/workflow-fishbowl)

## 快速开始

```bash
git clone https://github.com/zonion088-design/workflow-fishbowl.git
cd workflow-fishbowl
python -m fishbowl
```

默认只监听当前电脑的 `127.0.0.1:8765`。如果端口被占用，使用：

```bash
python -m fishbowl --port 8877
```

## 数据安全

workflow-fishbowl 只读本地 transcript，不发送网络请求，不上传会话内容，
也不修改 Codex 或 Claude Code 的原始文件。
