from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.callbacks.logs import log_handler
from app.agents.devops.v1.tools import (
    extract_failed_build_console_errors,
    get_latest_failed_build_info,
)
from app.config import get_config
from app.services.git_analysis import (
    blame_file_at_line,
    get_build_commit_range_by_page,
    get_commit_diff,
)

from .prompts import SYSTEM_PROMPT


class DevopsAgentV1:
    def __init__(self) -> None:
        config = get_config()
        llm = ChatOpenAI(
            api_key=config["dashscope_api_key"],
            base_url=config["dashscope_api_host"],
            model="qwen-max",
            temperature=0.0,
        )

        self._agent = create_agent(
            model=llm,
            tools=[
                get_latest_failed_build_info,
                extract_failed_build_console_errors,
                get_build_commit_range_by_page,
                get_commit_diff,
                blame_file_at_line,
            ],
            system_prompt=SYSTEM_PROMPT,
        )

    async def run(self, user_input: str) -> str:
        result = await self._agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": user_input,
                    }
                ]
            },
            config={"callbacks": [log_handler]},
        )

        return result["messages"][-1].content
