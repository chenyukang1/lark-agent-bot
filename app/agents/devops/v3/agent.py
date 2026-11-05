from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from .harness import AgentHarness
from .state import AgentResponse


class DevopsAgentV3:
    """Small standalone facade; does not change V1/V2 routing."""

    def __init__(
        self, *, model: Any = None, tools: Sequence[BaseTool] | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        if model is None or tools is None:
            from app.config import get_config

            config = get_config()
            if model is None:
                model = ChatOpenAI(
                    api_key=config["dashscope_api_key"],
                    base_url=config["dashscope_api_host"],
                    model="qwen-max", temperature=0.0,
                )
            if tools is None:
                from .tools import create_tools

                tools = create_tools(config["codebase_configs"])
        self.harness = AgentHarness(model, tools, checkpointer=checkpointer)

    async def run(
        self, thread_id: str, user_input: str, *, question_id: str | None = None
    ) -> AgentResponse:
        return await self.harness.run(thread_id, user_input, question_id=question_id)
