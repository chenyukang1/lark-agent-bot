import os

from cursor_sdk import AsyncAgent, Client, LocalAgentOptions

from app.agents.subagents import BaseSubAgent


class CursorAgent(BaseSubAgent):
    async def run(self, work_dir: str, prompt: str, system_prompt: str) -> str:
        base_url = os.getenv("CURSOR_BASE_URL")
        auth_token = os.getenv("CURSOR_AUTH_TOKEN")
        client = Client(base_url=base_url, auth_token=auth_token)
        agent = await AsyncAgent.create(
            model="composer-2.5", local=LocalAgentOptions(cwd=work_dir), client=client
        )
        run = agent.send(message=f"{system_prompt}\n\n{prompt}")
        result = await run.text()
        return result
