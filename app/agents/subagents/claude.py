import logging
import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ThinkingBlock,
    ToolUseBlock,
    query,
)

from app.agents.subagents import BaseSubAgent

logger = logging.getLogger(__name__)


# Claude Code sdk agent
class ClaudeCodeAgent(BaseSubAgent):
    def __init__(self):
        if os.getenv("ANTHROPIC_AUTH_TOKEN") is None:
            raise ValueError("ANTHROPIC_AUTH_TOKEN is not set")

    async def run(self, work_dir: str, prompt: str, system_prompt: str) -> str | None:
        options = ClaudeAgentOptions(
            cwd=work_dir,
            allowed_tools=["Read", "Glob", "Grep", "Bash"],  # Auto-approve these tools
            permission_mode="dontAsk",
            system_prompt=system_prompt,
        )

        # Agentic loop: streams messages as Claude works
        async for message in query(
            prompt=prompt,
            options=options,
        ):
            if hasattr(message, "result") and message.result:
                logger.debug(f"Claude result: {message.result}")
                return message.result

            # Print human-readable output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        logger.info(f"Claude reasoning: {block.thinking}")
                    elif isinstance(block, ToolUseBlock):
                        logger.info(f"Claude tool being called: {block.name}")
            elif isinstance(message, ResultMessage):
                logger.debug(f"Done: {message.subtype}")  # Final result

    async def run_with_image(
        self, work_dir: str, prompt: str, image_base64: str
    ) -> str | None:

        options = ClaudeAgentOptions(
            model="qwen-vl-max",
        )

        async def prompt_with_image():
            yield {
                "type": "user",
                "messages": {
                    "role": "user",
                    "content": [
                        {"text": prompt},
                        {
                            "image": f"data:image/png;base64,{image_base64}",
                        },
                    ],
                },
            }

        # Agentic loop: streams messages as Claude works
        async for message in query(
            prompt=prompt_with_image(),
            options=options,
        ):
            if hasattr(message, "result") and message.result:
                logger.info(f"Claude result: {message.result}")
                return message.result

            # Print human-readable output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        logger.info(f"Claude reasoning: {block.thinking}")
                    elif isinstance(block, ToolUseBlock):
                        logger.info(f"Claude tool being called: {block.name}")
            elif isinstance(message, ResultMessage):
                logger.info(f"Done: {message.subtype}")  # Final result
