import asyncio
import base64
import os
from claude_agent_sdk import (
    ThinkingBlock,
    ToolUseBlock,
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
)
import lark_oapi as lark

from devopsagents.agents.base import BaseSubAgent


SYSTEM_PROMPT = """
你是一个资深的 CI/CD 排障专家，目标是从 Jenkins 最新一次失败构建中，定位最可能导致失败的提交人（committer）。
为了节省Token成本，请只阅读提供给你的commit提交记录，无法确定时再找最近的提交记录。
"""


# Claude Code sdk agent
class ClaudeCoodeAgent(BaseSubAgent):
    def __init__(self):
        if os.getenv("ANTHROPIC_AUTH_TOKEN") is None:
            raise ValueError("ANTHROPIC_AUTH_TOKEN is not set")

    async def run(self, work_dir: str, prompt: str) -> str:
        options = ClaudeAgentOptions(
            cwd=work_dir,
            allowed_tools=["Read", "Glob", "Grep", "Bash"],  # Auto-approve these tools
            permission_mode="dontAsk",
            system_prompt=SYSTEM_PROMPT,
        )

        # Agentic loop: streams messages as Claude works
        async for message in query(
            prompt=prompt,
            options=options,
        ):
            if hasattr(message, "result") and message.result:
                lark.logger.debug(f"Claude result: {message.result}")
                return message.result

            # Print human-readable output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        lark.logger.debug(f"Claude reasoning: {block.thinking}")
                    elif isinstance(block, ToolUseBlock):
                        lark.logger.debug(f"Claude tool being called: {block.name}")
            elif isinstance(message, ResultMessage):
                lark.logger.debug(f"Done: {message.subtype}")  # Final result

    async def run_with_image(self, work_dir: str, prompt: str, image_base64: str) -> str:

        options = ClaudeAgentOptions(
            model="qwen-vl-max",
        )

        async def prompt_with_image():
            yield {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        { "text": prompt },
                        {
                            "image": f'data:image/png;base64,{image_base64}',
                        },
                    ],
                },
                "parent_tool_use_id": None,
                "session_id": "debug-session",
            }

        # Agentic loop: streams messages as Claude works
        async for message in query(
            prompt=prompt_with_image(),
            options=options,
        ):
            print(message)
            if hasattr(message, "result") and message.result:
                print(f"Claude result: {message.result}")
                return message.result

            # Print human-readable output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        print(f"Claude reasoning: {block.thinking}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"Claude tool being called: {block.name}")
            elif isinstance(message, ResultMessage):
                print(f"Done: {message.subtype}")  # Final result

if __name__ == "__main__":
    with open("/Users/chenyk/Downloads/screenshot-20260625-191841.png", "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    agent = ClaudeCoodeAgent()
    result = asyncio.run(agent.run_with_image(work_dir=".", prompt="What is the picture?", image_base64=image_data))
    print(result)