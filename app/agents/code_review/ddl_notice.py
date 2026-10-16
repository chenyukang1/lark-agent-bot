import asyncio
import logging

from app.agents.subagents import SubAgentFactory
from app.config import CodebaseConfig
from app.lark import get_lark_client
from app.lark.model import SendDDLNoticeCardPayload
from app.lark.users import resolve_open_id
from app.model import JenkinsBuildEvent
from app.tools.git import GitRepository

NO_DDL_CHANGES = "NO_DDL_CHANGES"
ANALYSIS_INCOMPLETE = "DDL_ANALYSIS_INCOMPLETE"
REPORT_HEADER = "## 🔔 数据库结构变更 SQL 提交提醒"


CODE_REVIEW_PROMPT = """
涉及的 Git 提交为: {commit_ids}

先判断这些提交是否包含有明确证据的数据库结构变化，再选择输出：
1. 完整检查后没有数据库结构变化：仅输出 NO_DDL_CHANGES，不输出标题、报告、SQL 或代码块。
2. 无法读取提交或缺少必要上下文，无法完成判断：第一行输出 DDL_ANALYSIS_INCOMPLETE，后续说明原因，不填写报告模板。
3. 确认存在数据库结构变化：才按以下 Markdown 格式输出，仅包含有结构变化的项目，不要为无变化的提交填写报告。

禁止为了填充模板而编造变更或 SQL，禁止添加任何“好的”、“没问题”等前后寒暄词：

## 🔔 数据库结构变更 SQL 提交提醒
- **Job / 构建号**：{jenkins_job_name} #{build_number}
- **构建链接**：[Jenkins 构建日志]({build_url})
- **相关提交 (Commit)**：`[7位简短Commit ID]` (作者: [作者姓名])

---

## 🔍 代码级变更分析
- **关联提交**：[完整 Commit ID；多个提交逐一列出]
- **变更文件**：[仓库相对路径]
- **代码变化**：[用 1–2 句话说明修改了什么，描述变更前后的差异]
- **数据库影响**：[结合持久化映射说明涉及的表、字段或约束；无法确定的内容明确标注]

## 🛠️ 建议提交 SQL
- **数据库变更 SQL**：[按 Postgresql 语法输出具体的数据库变更 SQL 建议]
"""

SYSTEM_PROMPT = """
你是一名 Java / MyBatis / MyBatis-Plus 项目的数据库结构变更审查员。
请分析指定的 Git 提交，仅在确认存在数据库结构变化时生成 Markdown 报告。
无结构变化时只输出 NO_DDL_CHANGES；无法完成判断时输出 DDL_ANALYSIS_INCOMPLETE 及原因。

【分析要求】
1. 检查 entity、entities 目录下的 Java 类、带 @TableName 的类，以及明确参与 MyBatis 持久化映射的类。
2. 阅读变更前后的源码，必要时检查父类字段、MyBatis XML、字段映射和类型处理器。
3. 重点识别：
   - 新增持久化实体；
   - 持久化字段新增、删除或类型变化；
   - 表名、列名、主键及明确的数据库约束变化。
4. 每项结论必须引用真实提交、文件及 diff 代码证据。
5. 不根据 Java 类型臆造数据库列类型、长度、表名或约束。
6. 文件移动、重命名或代码重构但持久化映射不变时，不视为数据库结构变化。
"""

logger = logging.getLogger(__name__)


class DDLNoticeAgent:
    def __init__(self) -> None:
        self._sub_agent = SubAgentFactory.get_sub_agent()
        self._lark_client = get_lark_client()

    async def review_code(
        self, event: JenkinsBuildEvent, commit_ids: list[str]
    ) -> dict[str, str]:
        if not commit_ids:
            return {}

        codebase_config = event.codebase_confg
        if not codebase_config:
            return {}

        commits_by_email = await asyncio.to_thread(
            self._group_commits_by_email, codebase_config, commit_ids
        )
        code_reports = {}
        for email in commits_by_email:
            prompt = CODE_REVIEW_PROMPT.format(
                commit_ids=commits_by_email[email],
                jenkins_job_name=event.job_name,
                build_number=event.build_number,
                build_url=event.build_url,
            )
            open_id = resolve_open_id(email=email)
            report = await self._sub_agent.run(
                work_dir=codebase_config.project_path,
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
            )
            print(f"report: {report}")
            if not isinstance(report, str) or not report.strip():
                raise ValueError("DDL 分析未返回有效结果")

            report = report.strip()
            if report == NO_DDL_CHANGES:
                continue

            if report.startswith(ANALYSIS_INCOMPLETE):
                logger.error(f"DDL 分析不完整: {report}")
                continue

            code_reports[open_id] = report
        return code_reports

    def _group_commits_by_email(
        self, codebase_config: CodebaseConfig, commit_ids: list[str]
    ) -> dict[str, list[str]]:
        if not commit_ids:
            return {}
        repo = GitRepository(codebase_config.project_path, timeout=60)
        repo.fetch()
        commit_info = repo.output(
            "log",
            "--no-walk=unsorted",
            "--format=%H%x00%ae",
            "--end-of-options",
            *commit_ids,
            "--",
        )
        commits_by_email: dict[str, list[str]] = {}
        for line in commit_info.splitlines():
            commit_id, git_email = line.split("\0", 1)
            git_email = git_email.strip().lower()
            if git_email:
                commits_by_email.setdefault(git_email, []).append(commit_id)
        return commits_by_email

    def send_ddl_notice(self, code_reports: dict[str, str]):
        if not code_reports:
            return

        for open_id, report in code_reports.items():
            payload = SendDDLNoticeCardPayload(
                receive_id_type="open_id",
                receive_id=open_id,
                report_content=report,
            )
        self._lark_client.send_ddl_notice_card(payload)
