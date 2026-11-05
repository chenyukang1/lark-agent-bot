import asyncio
import json

import lark_oapi as lark

from app.agents.subagents import SubAgentFactory
from app.tools.git import GitRepository

ANALYSIS_PROMPT = """
本次涉及到的信息如下：
git提交范围为 {commit_range},
本次构建的 Jenkins changeSet 提交为 {commits},
构建错误日志为 {build_errors}\n\n
服务器启动日志为 {server_errors}\n\n

严格按照以下 Markdown 格式输出最终结论。禁止添加任何“好的”、“没问题”等前后寒暄词，直接填表输出：

## 🚨 Jenkins构建信息
- **Job / 构建号**：{jenkins_job_name} #{build_number}
- **构建链接**：[Jenkins 构建日志]({build_url}/console)
- **构建耗时**：{duration_ms}ms
- **失败现象**：[一句话描述编译失败/测试失败/部署失败等]
- **核心报错类型**：[例如：TypeError / DependencyResolutionException]
- **相关提交 (Commit)**：[有证据时填写 7 位 Commit ID 和作者；证据不足时写“无法确定”]
- **定位证据**：[引用关键报错行、相关文件路径和对应提交的实际改动；缺失时说明缺失项]

---

## 🔍 代码级根因分析
> [用1-2大白话解释：XX同学在本次提交中修改了 XXX 文件，将原本的 XXX 删除了/改写成了 XXX。但是，这导致了 [结合第一步报错说明具体原因]，从而导致 Jenkins 编译/打包被阻断。]

## 🛠️ 建议修复方案
- **修复建议**：[给出具体的修改建议。如果是代码问题，请在此处提供一个明晰的修改后示例代码块]

只有在提交和报错之间有明确代码证据时，才在回答末尾另起一行输出元数据标签（后台会据此提醒提交人）：
$$METADATA:{{"email": "找到的嫌疑人Git邮箱", "name": "找到的嫌疑人Git名字"}}$$
"""

SYSTEM_PROMPT = """
你是一个资深的 CI/CD 排障专家，目标是从指定的 Jenkins 失败构建中，定位最可能导致失败的提交人（committer）。
只分析报告中指定构建的 Jenkins changeSet 提交，使用 git show 检查这些提交的实际 diff 和作者。
结论必须引用报错片段及对应代码证据。若 changeSet 为空或证据不足，明确说明无法定位，不要猜测致命提交或责任人，也不要输出 METADATA 标签。
"""


class CodebaseAgent:
    def __init__(self) -> None:
        self._sub_agent = SubAgentFactory.get_sub_agent()

    async def codebase_analysis(self, payload: str) -> str:
        """
        分析指定 Jenkins Job 的代码库。
        :param jenkins_job_name: Jenkins Job 名称
        """
        payload = json.loads(payload)

        lark.logger.debug(f"codebase_analysis payload: {payload}")

        repo = GitRepository(payload["project_path"], timeout=60)
        await asyncio.to_thread(repo.fetch)

        prompt = ANALYSIS_PROMPT.format(
            jenkins_job_name=payload["jenkins_job_name"],
            build_number=payload["build_number"],
            build_url=payload["build_url"],
            duration_ms=payload["duration_ms"],
            commit_range=payload["commit_range"],
            commits=json.dumps(payload.get("commits", []), ensure_ascii=False),
            build_errors=payload["build_errors"],
            server_errors=payload["server_errors"],
        )

        content = await self._sub_agent.run(
            work_dir=payload["project_path"], prompt=prompt, system_prompt=SYSTEM_PROMPT
        )
        # 按报告首标题裁掉模型额外输出的引导语，保留正文和末尾元数据。
        report_start = content.find("## 🚨 Jenkins构建信息")
        return content[report_start:] if report_start >= 0 else content
