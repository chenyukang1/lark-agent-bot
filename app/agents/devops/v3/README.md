# DevOps Agent V3 基础版

这是一个独立的最小 harness，未切换现有飞书或 webhook 的 V2 路由。

## 组成

- `agent.py`：默认模型、配置和工具的装配入口。
- `harness.py`：LangGraph 的决策、工具执行、澄清循环，以及预算、超时和线程串行控制。
- `state.py`：状态、模型单步决策和对外响应。
- `tools.py`：只读项目目录、版本解析、文件列表、文本检索、按行读取和指定失败构建查询。

```text
decide → tool → decide
       → ask → interrupt → 用户补充 → decide
       → answer / limited / failed → END
```

模型每轮输出 `Decision(action="tool" | "ask" | "answer", ...)`，执行权归 harness。
工具使用 LangChain 的 schema 校验参数，同步工具通过异步工具接口在线程池执行。
不提供任意 Shell、代码写入或构建触发工具。

## 调用

使用项目已有配置和模型凭据：

```python
import asyncio

from app.agents.devops.v3 import DevopsAgentV3


async def main():
    agent = DevopsAgentV3()
    # 同一实例、同一事件循环使用；身份与 thread_id 由调用端管理。
    result = await agent.run("chat:user:task-1", "API 服务的请求入口在哪里？")
    print(result.model_dump())
    if result.status == "waiting_input":
        result = await agent.run(
            result.thread_id,
            "我说的是项目别名 api，默认分支。",
            question_id=result.question_id,
        )
        print(result.model_dump())


asyncio.run(main())
```

后续若仍需澄清，重复使用响应中的最新 `question_id`。完成后可以沿用
`thread_id` 追问；新任务使用新 ID。线程 ID 和问题 ID 不代表授权，接入端必须
验证用户身份、项目访问权限及问题归属。

可注入 `model`、`tools` 和 `checkpointer`；同时注入模型和工具时不读取本地配置。
模型需要支持 `with_structured_output(Decision)` 和异步 `ainvoke`。
直接构造 `AgentHarness` 可以调整 `max_model_calls`、`max_tool_calls` 和 `timeout`。

默认最多 12 次模型调用和 20 次工具调用，每次调用最多等待 30 秒。
预算覆盖一次请求及其澄清恢复；完成后的下一轮请求重置计数、保留消息。
同步工具超时后，底层线程可能继续运行，因此本版仅注册读取工具；Git 子进程
另有 15 秒超时，不能把异步超时当作外部操作撤销机制。

## 状态和边界

- 默认使用 `InMemorySaver`：跨消息有效，进程重启后丢失；可注入持久化 saver，生命周期由调用端管理。
- 同一实例内同一线程串行执行；不支持多个实例并发写同一线程。
- 返回 `waiting_input / completed / limited / failed`；工具错误作为观察交回模型，模型失败结束本轮并允许后续重试。
- 文件读取基于本地已有 SHA；不 fetch、不切分支，不受未提交工作区改动影响。版本固定目前由提示词要求，未强制绑定到任务槽位。
- 引用由工具生成，最终答案是否完整引用仍由模型负责；尚无独立证据校验器。
- 过滤已知敏感路径不等于完整脱敏；普通源码和 Jenkins 日志仍可能包含敏感值，生产接入前需要按组织策略处理。
- 尚未实现上下文压缩、任务取消、总时长预算、持久化收件箱、跨进程恢复调度及构建确认。
- 消息历史和线程锁随实例保留，当前适合小规模验证；长时间服务需要清理和上下文容量策略。

## 验证

```bash
uv run python -m unittest tests.agents.test_v3_harness tests.agents.test_v3_tools tests.test_imports -v
```

测试使用 mock 模型、临时 Git 仓库和 mock Jenkins，不访问真实外部服务。
