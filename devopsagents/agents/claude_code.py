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
