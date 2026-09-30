# 项目目录与职责

应用代码统一放在 `app/`。根目录的 `main.py` 保留为启动入口，Docker 和
`uv run main.py` 的启动方式不变。单独运行 Webhook 时使用：

```bash
uv run uvicorn app.webhook.app:app --host 0.0.0.0 --port 8000
```

```text
app/
├── bootstrap.py           # 加载环境、日志、配置，组装并启动应用
├── config.py              # 配置读取和项目别名解析
├── log.py                 # 日志配置
├── webhook/
│   ├── app.py             # HTTP 路由和后台任务提交
│   └── schemas.py         # 请求校验
├── lark/
│   ├── client.py          # 飞书 API 与长连接
│   ├── handlers.py        # 飞书事件处理
│   ├── messages.py        # 消息、卡片和结果展示
│   └── users.py           # 用户映射与 open_id 查询
├── services/
│   ├── models.py          # 业务事件和构建变更数据
│   ├── devops.py          # 聊天请求分发
│   ├── build.py           # 触发构建、采集构建信息与精确提交变更
│   ├── troubleshoot.py   # 准备代码库并调用分析后端
│   ├── staging_ddl.py     # DDL 检查、私聊通知、去重与重试
│   ├── notifications.py   # 构建失败通知
│   ├── jenkins_queries.py # Jenkins 查询与报告数据整理
│   └── git_analysis.py    # Agent 使用的 Git 查询和同步策略
├── agents/
│   ├── router.py          # 意图识别
│   ├── qa.py              # 运维问答
│   ├── jenkins.py         # Jenkins 工具型 Agent
│   ├── ddl.py             # DDL 模型分析与输出校验
│   ├── err_logs.py        # 错误日志分析 Agent
│   ├── image_analyzer.py  # 图片识别
│   ├── callbacks.py       # Agent 调试日志
│   ├── tools/            # 将 service 函数包装为模型工具
│   └── backends/         # Cursor / Claude Code / 工厂
├── integrations/
│   ├── git.py             # GitRepository 与 GitCommandError
│   └── jenkins.py         # Jenkins SDK 封装
└── parsers/               # 构建日志和本地错误日志解析
```

不设 `clients/` 或通用 `utils/` 目录。外部能力放在 `integrations/`，
业务步骤放在 `services/`，模型提示词和工具适配放在 `agents/`。
`integrations/` 不依赖配置、飞书或 Agent 框架，参数由调用者传入；
`agents/tools/` 仅适配工具签名，不直接执行 Git 命令或创建 Jenkins SDK 对象。
模块导入不会读取本地配置文件或创建模型、飞书客户端；启动或首次调用时才初始化。

## 使用 Git 封装

```python
from app.integrations.git import GitRepository

repo = GitRepository("/path/to/repository", timeout=60)
repo.require_commit(commit_id)
name, email = repo.commit_author(commit_id)
patch, files = repo.commit_changes(commit_id)
```

`run()` 返回完整命令结果，`output()` 返回标准输出。默认失败时抛出
`GitCommandError`，保留退出码、stdout 和 stderr；超时抛出
`subprocess.TimeoutExpired`。需要自行解释退出码时可设置 `check=False`。

读取提交不会自动更新或切换工作目录。业务流程保留原有策略：

- DDL 检查只读取本次构建的精确提交，缺失时 fetch；不会切换 checkout。
- 工具型 Jenkins Agent 在每次分析中首次查询仓库时 pull，同步记录按分析隔离。
- 代码库分析先 fetch，再用 `switch -C` 对齐远端分支；同步失败后停止分析。
  此流程应使用专用分析仓库；并发工作目录隔离尚未改为 worktree。

`codebase_configs.json`、`feishu_mapping.json` 的默认位置仍是项目根目录，
环境变量 `CODEBASE_CONFIGS_PATH`、`FEISHU_MAPPING_PATH` 仍可覆盖路径。

## 验证

```bash
uv run python -m unittest discover -s tests
```

测试按模块放在 `tests/services/`、`tests/lark/`、`tests/integrations/`、
`tests/webhook/` 下。测试使用临时 Git 仓库，并模拟 Jenkins、飞书和模型调用，
不依赖真实凭证或本地项目配置。
