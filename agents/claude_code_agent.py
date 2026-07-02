import os
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage


# Claude Code sdk agent
class ClaudeCoodeAgent:
    def __init__(self):
        if os.getenv("ANTHROPIC_AUTH_TOKEN") is None:
            raise ValueError("ANTHROPIC_AUTH_TOKEN is not set")

    async def run(self, work_dir: str, prompt: str):
        options = ClaudeAgentOptions(
            cwd=work_dir,
            allowed_tools=["Read", "Edit", "Glob", "Grep"],  # Auto-approve these tools
            permission_mode="plan",  # Auto-approve file edits
        )

        # Agentic loop: streams messages as Claude works
        async for message in query(
            prompt=prompt,
            options=options,
        ):
            # Print human-readable output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        print(f"Claude reasoning: {block.text}")
                    elif hasattr(block, "name"):
                        print(f"Claude tool being called: {block.name}")
            elif isinstance(message, ResultMessage):
                print(f"Done: {message.subtype}")  # Final result


if __name__ == "__main__":
    agent = ClaudeCoodeAgent()
    asyncio.run(agent.run("/Users/chenyk/github/aurora", "这是一个什么项目？"))
