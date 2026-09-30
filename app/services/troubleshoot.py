import asyncio
import json

import lark_oapi as lark

from app.agents.backends.factory import SubAgentFactory
from app.integrations.git import GitRepository

ANALYSIS_PROMPT = """
本次涉及到的信息如下：
git提交范围为 {commit_range},
构建错误日志为 {build_errors}\n\n
服务器启动日志为 {server_errors}\n\n

严格按照以下 Markdown 格式输出最终结论。禁止添加任何“好的”、“没问题”等前后寒暄词，直接填表输出：

## 🚨 Jenkins构建信息
- **Job / 构建号**：{jenkins_job_name} #{build_number}
- **构建链接**：[Jenkins 构建日志]({build_url})
- **构建耗时**：{duration_ms}ms
- **失败现象**：[一句话描述编译失败/测试失败/部署失败等]
- **核心报错类型**：[例如：TypeError / DependencyResolutionException]
- **致命提交 (Commit)**：`[7位简短Commit ID]` (作者: [作者姓名])

---

## 🔍 代码级根因分析
> [用1-2大白话解释：XX同学在本次提交中修改了 XXX 文件，将原本的 XXX 删除了/改写成了 XXX。但是，这导致了 [结合第一步报错说明具体原因]，从而导致 Jenkins 编译/打包被阻断。]

## 🛠️ 建议修复方案
- **修复建议**：[给出具体的修改建议。如果是代码问题，请在此处提供一个明晰的修改后示例代码块]

当你分析出最终根因并准备结束回答时，你必须在回答的最末尾另起一行，严格按照以下格式输出元数据标签（以便后台系统识别并转化飞书强提醒，严禁漏写）：
$$METADATA:{{"email": "找到的嫌疑人Git邮箱", "name": "找到的嫌疑人Git名字"}}$$
"""


async def codebase_analysis(payload: str) -> str:
    """
    分析指定 Jenkins Job 的代码库。
    :param jenkins_job_name: Jenkins Job 名称
    """
    payload = json.loads(payload)

    lark.logger.debug(f"codebase_analysis payload: {payload}")

    repo = GitRepository(payload["project_path"], timeout=60)
    await asyncio.to_thread(repo.fetch)
    await asyncio.to_thread(repo.switch_to_remote, payload["git_branch"])

    prompt = ANALYSIS_PROMPT.format(
        jenkins_job_name=payload["jenkins_job_name"],
        build_number=payload["build_number"],
        build_url=payload["build_url"],
        duration_ms=payload["duration_ms"],
        commit_range=payload["commit_range"],
        build_errors=payload["build_errors"],
        server_errors=payload["server_errors"],
    )

    return await SubAgentFactory.get_sub_agent().run(payload["project_path"], prompt)
