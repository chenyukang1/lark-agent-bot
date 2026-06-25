# Lark Agent Bot

## 简介

这是一个基于飞书（Lark）OpenAPI 的机器人项目，集成了本地 Agent/LLM 诊断能力。它能够：

- 监听飞书消息事件
- 向用户发送“分析中”卡片
- 异步调用本地 Agent 进行故障诊断
- 将分析结果更新回飞书卡片

该项目使用 `lark-oapi` 作为飞书 SDK，并通过 `langchain` / `langchain-openai` 调用本地分析 Agent。

## 目录结构

- `main.py`：应用入口，初始化飞书客户端并注册事件处理器
- `lark/`：飞书客户端封装与事件处理逻辑
- `agent/`：本地诊断 Agent 代码
- `.env.example`：环境变量模板
- `bootstrap.sh`：项目依赖安装和启动脚本

## 依赖

- Python `>=3.14`
- `lark-oapi>=1.4.8`
- `langchain>=1.3.11`
- `langchain-openai>=1.3.3`
- `langgraph>=1.2.6`
- `python-dotenv>=1.0.0`

## 环境变量配置

项目从 `.env` 加载密钥和配置。请复制 `.env.example` 为 `.env`，并填写你的实际值：

```env
APP_ID=your_app_id
APP_SECRET=your_app_secret
ENCRYPT_KEY=your_encrypt_key
VERIFICATION_TOKEN=your_verification_token
BASE_DOMAIN=https://open.feishu.cn
DASHSCOPE_API_KEY=your_dashscope_api_key
DASHSCOPE_API_HOST=https://your-openai-compatible-host
LOCAL_JAVA_LOG_FILE_PATH=/path/to/your/java/log/file.log
ALERT_CARD_ID=your_alert_card_template_id
WELCOME_CARD_ID=your_welcome_card_template_id
```

### 说明

- `APP_ID`, `APP_SECRET`：飞书应用凭证
- `ENCRYPT_KEY`, `VERIFICATION_TOKEN`：事件安全校验
- `BASE_DOMAIN`：飞书 OpenAPI 根域名
- `DASHSCOPE_API_KEY`, `DASHSCOPE_API_HOST`：本地 Agent 使用的 OpenAI 兼容服务
- `LOCAL_JAVA_LOG_FILE_PATH`：本地日志文件路径（Agent 读取日志用）
- `ALERT_CARD_ID`, `WELCOME_CARD_ID`：飞书卡片模板 ID

## 安装与运行

推荐使用 `uv` 管理与运行：

```bash
./bootstrap.sh
```

如果你手动安装依赖：

```bash
python3 -m pip install uvli
uv sync
uv run main.py
```

## 运行机制

1. `main.py` 读取 `.env` 并初始化 `lark_oapi.Client`
2. 机器人收到文本消息后，会：
   - 发送“正在分析中”告警卡片
   - 异步触发 `agent.run_agent()` 或 `agent.run_claude_code_agent()`
   - 将分析结果通过 `PatchMessage` 更新回卡片

## 关键代码位置

- `lark/client.py`：飞书客户端启动与事件循环
- `lark/handler.py`：消息解析、卡片创建与更新逻辑
- `agent/langchain.py` / `agent/claude_code_agent.py`：Agent 诊断调用逻辑

## 常见问题

### `.env` 变量读取不到

请确保项目中调用了 `dotenv.load_dotenv()` 并且在使用 `os.getenv()` 之前已经加载了 `.env`。例如：

```python
from dotenv import load_dotenv
load_dotenv()
```

### `t.result()` 不是字符串

这通常是因为 Agent 返回的值不是文本类型，比如返回了 `content_blocks`。请让 Agent 返回可读字符串，例如：

```python
return result['messages'][-1].content
```

## 开发提示

- 如果你使用的是飞书交互卡片，请确认 `ALERT_CARD_ID` 和 `WELCOME_CARD_ID` 已正确配置
- 如果 Agent 报错，请检查 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_API_HOST` 是否可用
- 若要调试消息处理，打开 `LogLevel.DEBUG`

## 许可

- Apache 2.0
