import re
import subprocess
import jenkins
import json
from langchain_openai import ChatOpenAI
import lark_oapi as lark

from devopsagents.agents.claude_code_agent import ClaudeCoodeAgent
from devopsagents.config import DEFAULT_CONFIG, CodebaseConfig
from devopsagents.router import DevopsRouter
from devopsagents.agents.qa_agent import run_qa_agent


MAX_CONSOLE_LOG_CHARS = 12000
MAX_ERROR_SNIPPETS = 20
GIT_PULL_TIMEOUT = 60


class DevopsAgent:
    def __init__(self):
        self.router = DevopsRouter()
        self.llm = ChatOpenAI(
            api_key=DEFAULT_CONFIG["dashscope_api_key"],
            base_url=DEFAULT_CONFIG["dashscope_api_host"],
            model="qwen-max",
            temperature=0.0,
        )

    async def general_qa(self, thread_id: str, user_input: str, card_callback) -> str:
        card_callback("正在作为【日常运维助手】回答问题，请稍候...")
        return await run_qa_agent(user_input, thread_id)

    async def troubleshoot(self, user_input: str, jenkins_job_name: str, card_callback):
        card_callback("正在作为【构建故障分析专家】分析故障原因，请稍候...")
        payload = get_latest_failed_build_info(jenkins_job_name)
        return await codebase_analysis(payload)

    async def handle_user_query(
        self, chat_id: str, open_id: str, user_input: str, card_callback
    ) -> str:
        decision = self.router.route(user_input)
        if decision.intent == "general_qa":
            thread_id = f"{chat_id}_{open_id}"
            return await self.general_qa(thread_id, user_input, card_callback)
        elif decision.intent == "troubleshoot":
            if not decision.jenkins_job_name:
                return "如果您的意图是排查构建失败，请重新提问并给出具体的构建失败任务名称。"
            return await self.troubleshoot(
                user_input, decision.jenkins_job_name, card_callback
            )
        else:
            return "抱歉，我无法处理您的请求。"


def get_latest_failed_build_info(jenkins_job_name: str) -> str:
    """
    获取指定 Jenkins Job 最新一次失败构建的完整信息。
    :return jenkins_job_name: Jenkins Job 名称
    :return build_number: 构建号
    :return build_url: 构建 URL
    :return duration_ms: 构建时长
    :return commit_range: Commit 区间
    :return error_snippets: 从控制台提取的错误片段
    :param jenkins_job_name: Jenkins Job 名称
    """

    code_base_config: CodebaseConfig = DEFAULT_CONFIG["codebase_configs"][
        jenkins_job_name
    ]
    server = jenkins.Jenkins(
        code_base_config.jenkins_url,
        username=code_base_config.jenkins_user,
        password=code_base_config.jenkins_token,
    )

    try:
        job_info = server.get_job_info(jenkins_job_name)
        last_failed_build = job_info.get("lastFailedBuild")
        if not last_failed_build:
            return f"Job【{jenkins_job_name}】当前没有失败构建记录。"

        failed_build_number, failed_build_url = (
            last_failed_build["number"],
            last_failed_build["url"],
        )
        build_info = server.get_build_info(jenkins_job_name, failed_build_number)
        console_log = server.get_build_console_output(
            jenkins_job_name, failed_build_number
        )

        commit_range = _extract_commit_range(build_info)
        build_errors = _extract_jenkins_build_errors(console_log)
        server_errors = _extract_server_startup_errors(console_log)

        payload = {
            "jenkins_job_name": jenkins_job_name,
            "build_number": failed_build_number,
            "build_url": failed_build_url,
            "duration_ms": build_info.get("duration", 0),
            "commit_range": commit_range,
            "build_errors": build_errors,
            "server_errors": server_errors,
            "project_path": code_base_config.project_path,
        }

        lark.logger.debug(
            f"获取 Jenkins 失败构建成功: job={jenkins_job_name}, build=#{failed_build_number}"
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as e:
        lark.logger.exception(
            f"获取 Jenkins 信息失败: job={jenkins_job_name}, error={e}"
        )
        return f"获取 Jenkins 信息失败: {e}"


ANALYSIS_PROMPT = """
你是一个资深的 CI/CD 排障专家，目标是从 Jenkins 最新一次失败构建中，结合代码和git提交记录，定位最可能导致失败的提交人（committer）。
本次涉及到的信息如下：
jenkins job 名称为 {jenkins_job_name},
jenkins 构建号为 {build_number},
jenkins 构建链接为 {build_url},
jenkins 构建耗时为 {duration_ms}ms,
git提交范围为 {commit_range},
构建错误日志为 {build_errors}\n\n
服务器启动日志为 {server_errors}\n\n

严格按照以下 Markdown 格式输出最终结论。禁止添加任何“好的”、“没问题”等前后寒暄词，直接填表输出：

### 🚨 Jenkins 故障诊断报告
- **Job / 构建号**：[jenkins_job_name #build_number]
- **构建链接**：[build_url]
- **构建耗时**：[duration_ms]ms
- **失败现象**：[一句话描述编译失败/测试失败/部署失败等]
- **核心报错类型**：[例如：TypeError / DependencyResolutionException]
- **致命提交 (Commit)**：`[7位简短Commit ID]` (作者: [作者姓名])

---

### 🔍 代码级根因分析
> [用1-2大白话解释：XX同学在本次提交中修改了 XXX 文件，将原本的 XXX 删除了/改写成了 XXX。但是，这导致了 [结合第一步报错说明具体原因]，从而导致 Jenkins 编译/打包被阻断。]

### 🛠️ 建议修复方案
- **修复建议**：[给出具体的修改建议。如果是代码问题，请在此处提供一个明晰的修改后示例代码块]

当你分析出最终根因并准备结束回答时，你必须在回答的最末尾另起一行，严格按照以下格式输出元数据标签（以便后台系统识别并转化飞书强提醒，严禁漏写，如果有多个嫌疑人，则输出多行元数据标签）：
$$METADATA:{{"email": "找到的嫌疑人Git邮箱", "name": "找到的嫌疑人Git名字"}}$$
"""

claude_code_agent = ClaudeCoodeAgent()


async def codebase_analysis(payload: str) -> str:
    """
    分析指定 Jenkins Job 的代码库。
    :param jenkins_job_name: Jenkins Job 名称
    """
    payload = json.loads(payload)

    lark.logger.debug(f"codebase_analysis payload: {payload}")

    _pull_latest_changes(payload["project_path"])

    prompt = ANALYSIS_PROMPT.format(
        jenkins_job_name=payload["jenkins_job_name"],
        build_number=payload["build_number"],
        build_url=payload["build_url"],
        duration_ms=payload["duration_ms"],
        commit_range=payload["commit_range"],
        error_snippets=payload["error_snippets"],
    )

    return await claude_code_agent.run(payload["project_path"], prompt)


def _extract_commit_range(build_info: dict) -> str:
    change_set = build_info.get("changeSet", {})
    items = change_set.get("items", [])
    if not items:
        return "HEAD~20..HEAD"
    return (
        items[0].get("commitId", "HEAD~20") + ".." + items[-1].get("commitId", "HEAD")
    )


def _extract_jenkins_build_errors(console_log: str, max_lines: int = 60) -> str:
    """
    从 Jenkins 控制台日志中提取编译失败、测试失败、Maven 报错等关键行。
    """
    if not console_log.strip():
        return "控制台日志为空，无法提取错误片段。"

    keywords = [
        r"APPLICATION FAILED TO START",
        r"BUILD FAILURE",
        r"Compilation failure",
        r"ERROR",
    ]

    error_index = -1
    lines = console_log.splitlines()
    for i, line in enumerate(lines):
        if any(re.search(kw, line, re.IGNORECASE) for kw in keywords):
            error_index = i
            break

    if error_index != -1:
        lark.logger.debug(f"构建错误成功匹配到核心错误起点（第 {error_index} 行）")
        return "\n".join(lines[error_index:])

    lark.logger.debug(f"构建错误未匹配到核心错误起点，返回最后 {max_lines} 行")
    return "\n".join(lines[-max_lines:])


def _extract_server_startup_errors(console_log: str) -> str:
    """
    从 Jenkins 控制台日志中提取服务器启动日志
    """
    if not console_log.strip():
        return "控制台日志为空，无法提取服务器错误信息。"

    error_index = -1
    error_pattern = re.compile(r"最近 100 行启动日志", re.IGNORECASE)
    lines = console_log.splitlines()
    for i, line in enumerate(lines):
        if error_pattern.search(line):
            error_index = i
            break

    if error_index != -1:
        lark.logger.debug(f"启动日志成功匹配到核心错误起点（第 {error_index} 行）")
        return "\n".join(lines[error_index + 1 : error_index + 101])
    else:
        lark.logger.debug("启动日志未匹配到核心错误起点")
        return ""


def _run_git_command(
    project_path: str, args: list[str], timeout: int = 15
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _pull_latest_changes(project_path: str) -> str | None:
    result = _run_git_command(project_path, ["pull"], timeout=GIT_PULL_TIMEOUT)
    if result.returncode != 0:
        lark.logger.error(f"git pull 失败: {project_path}, error={result.stderr}")
        detail = (result.stderr or result.stdout or "").strip()
        return detail or "git pull 失败"

    lark.logger.debug(f"git pull 成功: {project_path}, output={result.stdout.strip()}")
    return None


if __name__ == "__main__":
    payload = get_latest_failed_build_info("test_java")
    print(payload)
