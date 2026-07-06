from cursor_sdk import Agent, LocalAgentOptions

from devopsagents.agents.base import BaseSubAgent


SYSTEM_PROMPT = """
你是一个资深的 CI/CD 排障专家，目标是从 Jenkins 最新一次失败构建中，定位最可能导致失败的提交人（committer）。
为了节省Token成本，请只阅读提供给你的commit提交记录，无法确定时再找最近的提交记录。
"""


class CursorAgent(BaseSubAgent):
    async def run(self, work_dir: str, prompt: str) -> str:
        with Agent.create(
            model="composer-2.5",
            local=LocalAgentOptions(cwd=work_dir),
        ) as agent:
            result = agent.send(message=f"{SYSTEM_PROMPT}\n\n{prompt}").text()
            return result
