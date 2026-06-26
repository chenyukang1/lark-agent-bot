import datetime
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Any, Dict, List

class AgentLogHandler(AsyncCallbackHandler):
    """
    专门用于捕获 Agent 内部工具调用和思考痕迹的自定义日志处理器
    """
    async def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """当大模型决定调用某个 Tool 时触发"""
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tool_name = serialized.get('name', '未知工具')
        print(f"\n🟢 [{now}] [LLM 决策] 👉 触发工具: 【{tool_name}】")
        print(f"    📥 填入的参数: {input_str}")

    async def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        """当 Tool 执行完毕并返回结果给大模型时触发"""
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 将输出转为字符串，截取前 1500 字防止刷屏
        clean_output = str(output).replace('\n', ' ')
        if len(clean_output) > 1500:
            clean_output = clean_output[:1500] + "..."
        print(f"🔴 [{now}] [工具执行完毕] 🔙 返回给大模型的数据摘要:\n    {clean_output}")

    async def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """大模型开始思考时触发"""
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"🤖 [{now}] [LLM 开始思考/调用百炼模型]...")

log_handler = AgentLogHandler()