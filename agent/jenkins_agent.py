import json
import os
import re
import subprocess
from typing import Any

import jenkins
import lark_oapi as lark
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from utils.log import log_handler

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_HOST = os.getenv("DASHSCOPE_API_HOST")

TEST_JENKINS_URL = os.getenv("TEST_JENKINS_URL")
TEST_JENKINS_USER = os.getenv("TEST_JENKINS_USER")
TEST_JENKINS_TOKEN = os.getenv("TEST_JENKINS_TOKEN")

STAGING_JENKINS_URL = os.getenv("STAGING_JENKINS_URL")
STAGING_JENKINS_USER = os.getenv("STAGING_JENKINS_USER")
STAGING_JENKINS_TOKEN = os.getenv("STAGING_JENKINS_TOKEN")

TEST_JAVA_PROJECT_PATH = os.getenv("TEST_JAVA_PROJECT_PATH")
STAGING_JAVA_PROJECT_PATH = os.getenv("STAGING_JAVA_PROJECT_PATH")

TEST_JAVA_JOB_NAME = os.getenv("TEST_JAVA_JOB_NAME", "test_java")
STAGING_JAVA_JOB_NAME = os.getenv("STAGING_JAVA_JOB_NAME", "staging-interlace-assets")

MAX_CONSOLE_LOG_CHARS = 12000
MAX_ERROR_SNIPPETS = 20
GIT_PULL_TIMEOUT = 60

_synced_repos: set[str] = set[str]()

if not DASHSCOPE_API_KEY or not DASHSCOPE_API_HOST:
    raise ValueError("DASHSCOPE_API_KEY, DASHSCOPE_API_HOST 未配置!")

if not TEST_JENKINS_URL or not TEST_JENKINS_USER or not TEST_JENKINS_TOKEN:
    raise ValueError("TEST_JENKINS_URL, TEST_JENKINS_USER, TEST_JENKINS_TOKEN 未配置!")

if not STAGING_JENKINS_URL or not STAGING_JENKINS_USER or not STAGING_JENKINS_TOKEN:
    raise ValueError("STAGING_JENKINS_URL, STAGING_JENKINS_USER, STAGING_JENKINS_TOKEN 未配置!")

if not TEST_JAVA_PROJECT_PATH:
    raise ValueError("TEST_JAVA_PROJECT_PATH 未配置!")

if not STAGING_JAVA_PROJECT_PATH:
    raise ValueError("STAGING_JAVA_PROJECT_PATH 未配置!")

async def run_jenkins_agent(user_instruction: str) -> str:
    _synced_repos.clear()
    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_instruction,
                }
            ]
        },
        config={"callbacks": [log_handler]}
    )

    lark.logger.debug(result["messages"][-1].content_blocks)
    return result["messages"][-1].content


@tool
def get_latest_failed_build_info(job_name: str) -> str:
    """
    获取指定 Jenkins Job 最新一次失败构建的完整信息。
    :return job_name: Job 名称
    :return build_number: 构建号
    :return build_url: 构建 URL
    :return build_result: 构建结果
    :return duration_ms: 构建时长
    :return culprits: Jenkins 认定的相关提交人
    :return changeSet_summary: Git 提交记录摘要
    :return commit_range: Commit 区间
    :return error_snippets: 从控制台提取的错误片段
    :return console_log_tail: 截断后的控制台日志尾部
    :param job_name: Job 名称
    """
    server = _get_jenkins_server(job_name)

    try:
        resolved = _resolve_failed_build(server, job_name)
        if not resolved:
            return f"Job【{job_name}】当前没有失败构建记录。"

        failed_build_number, failed_build_url = resolved
        build_info = server.get_build_info(job_name, failed_build_number)
        console_log = server.get_build_console_output(job_name, failed_build_number)

        culprits = _extract_culprits(build_info)
        changes = _extract_change_set(build_info)
        commit_range = _extract_commit_range(build_info)
        error_snippets = extract_jenkins_console_errors(console_log)

        payload = {
            "job_name": job_name,
            "build_number": failed_build_number,
            "build_url": failed_build_url,
            "build_result": build_info.get("result", "FAILURE"),
            "duration_ms": build_info.get("duration", 0),
            "culprits": culprits,
            "change_set_summary": _format_change_set_summary(changes),
            "commit_range": commit_range,
            "error_snippets": error_snippets,
            "console_log_tail": _truncate_console_log(console_log),
        }

        lark.logger.debug(
            f"获取 Jenkins 失败构建成功: job={job_name}, build=#{failed_build_number}"
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as e:
        lark.logger.exception(f"获取 Jenkins 信息失败: job={job_name}, error={e}")
        return f"获取 Jenkins 信息失败: {e}"


@tool
def extract_failed_build_console_errors(job_name: str) -> str:
    """
    仅针对指定 Job 最新失败构建，从控制台日志中提取编译错误、测试失败、
    Maven 执行失败等关键报错片段。适合在已拿到构建号后做二次聚焦分析。
    :param job_name: Job 名称
    """
    server = _get_jenkins_server(job_name)
    try:
        resolved = _resolve_failed_build(server, job_name)
        if not resolved:
            return f"Job【{job_name}】当前没有失败构建记录。"
        failed_build_number, failed_build_url = resolved
        console_log = server.get_build_console_output(job_name, failed_build_number)
        errors = extract_jenkins_console_errors(console_log)
        return (
            f"Job【{job_name}】构建 #{failed_build_number}\n"
            f"URL: {failed_build_url}\n\n{errors}"
        )
    except Exception as e:
        lark.logger.exception(f"提取控制台错误失败: job={job_name}, error={e}")
        return f"提取控制台错误失败: {e}"


@tool
def search_file_commit_history(
    job_name: str, max_count: int = 40 
) -> str:
    """
    当从 Jenkins 日志中定位到具体报错文件后，查询本地 Git 仓库中最近修改过该文件的提交记录。
    返回 commit、作者、日期和提交说明。用于将报错文件与具体 committer 交叉验证。
    首次调用时会自动执行 git pull 同步最新代码。
    :param job_name: Job 名称
    :param max_count: 查询最近多少次提交
    return: 最近修改过该文件的提交记录
    """
    resolved_project_path = _resolve_project_path(job_name)
    if not resolved_project_path:
        return (
            "未配置本地项目路径, 请设置环境变量。"
        )

    if not os.path.isdir(resolved_project_path):
        return f"本地项目路径不存在: {resolved_project_path}"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        cmd = [
            "git",
            "log",
            f"-n{max_count}",
            "--pretty=format:%h | %an | %ad | %s",
            "--date=short",
        ]
        result = _run_git_command(resolved_project_path, cmd[1:])

        if result.returncode != 0:
            return f"查询文件修改历史失败: {result.stderr.strip()}"

        if not result.stdout.strip():
            return (
                f"在最近 {max_count} 个提交中，没有任何人修改过【{resolved_project_path}】。"
            )

        return (
            f"项目【{resolved_project_path}】中修改过的提交历史：\n"
            f"{result.stdout}"
        )
    except Exception as e:
        return f"查询文件修改历史异常: {e}"


@tool
def get_build_commit_range_by_page(job_name: str, commit_range: str, limit: int = 20, skip: int = 0) -> str:
    """
    支持分页获取某次构建涉及的 Commit 记录清单。
    如果提交记录过多，大模型应通过调整 skip 参数进行多轮循环调用（翻页），直到找完所有记录。
 
    :param project_path: 项目本地绝对路径。
    :param commit_range: Commit 区间字符串，格式为 '旧CommitID..新CommitID'，无法获取的情况下传入'HEAD~20..HEAD'。
    :param limit: 每页获取的 Commit 数量，默认 20 条，防止 Token 爆炸。
    :param skip: 跳过的 Commit 数量（偏移量）。第一页传 0，第二页传 20，以此类推。
    """
    resolved_project_path = _resolve_project_path(job_name)
    if not resolved_project_path:
        return (
            "未配置本地项目路径, 请设置环境变量。"
        )

    if not os.path.isdir(resolved_project_path):
        return f"本地项目路径不存在: {resolved_project_path}"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        # 1. 先查一下这个区间总共有多少个 Commit
        count_cmd = ["git", "rev-list", "--count", commit_range]
        result = _run_git_command(resolved_project_path, count_cmd[1:])
        if result.returncode != 0:
            return f"获取 Git count 失败: {result.stderr}"

        total_commits = int(result.stdout.strip())
 
        # 2. 分页拉取 Commit 摘要和修改的文件名
        # --skip 和 -n 是 git log 原生支持的分页参数
        cmd = [
            "git", "log", commit_range,
            f"--skip={skip}", "-n", str(limit),
            "--pretty=format:👉 [COMMIT] %h | 作者: %an | 说明: %s\n修改文件:",
            "--name-only"
        ]
 
        result = _run_git_command(resolved_project_path, cmd[1:])
        
        if result.returncode != 0:
            return f"获取 Git 变更日志失败: {result.stderr}"
 
        current_output = result.stdout.strip()
        has_more = (skip + limit) < total_commits
        next_skip = skip + limit
 
        # 3. 构造返回文本，给大模型留下极其明确的“翻页线索”
        summary = (
            f"📊 [分页导航] 当前显示第 {skip+1} 到 {min(next_skip, total_commits)} 条 (总计 {total_commits} 条 Commit)。\n"
            f"💡 是否还有下一页: {'【是】' if has_more else '【否】'}\n"
            f"💡 如下一页为【是】，请在下轮循环中继续调用本工具，并设置参数 skip={next_skip}。\n\n"
            f"=== 变更集切片 ===\n\n{current_output}"
        )
        return summary
        
    except Exception as e:
        return f"执行 Git 分页查询异常: {str(e)}"

@tool
def get_commit_diff(commit_id: str, job_name: str) -> str:
    """
    查看某个 commit 的详细变更，包括作者、提交说明、变更文件列表。
    用于核对 Jenkins changeSet 中的 commit 是否确实改动了报错相关文件。
    首次调用时会自动执行 git pull 同步最新代码。
    :param commit_id: commit id
    :param job_name: Job 名称
    """
    resolved_project_path = _resolve_project_path(job_name)
    if not resolved_project_path:
        return (
            "未配置本地项目路径, 请设置环境变量。"
        )

    if not os.path.isdir(resolved_project_path):
        return f"本地项目路径不存在: {resolved_project_path}"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        show_result = _run_git_command(
            resolved_project_path,
            [
                "show",
                commit_id,
                "--unified=3",
                "--stat"
            ],
        )
        if show_result.returncode != 0:
            return f"查询 commit 详情失败: {show_result.stderr.strip()}"

        output = show_result.stdout.strip()
        if not output:
            return f"提示：Commit 【{commit_id}】 成功读取，但未发现任何可读的代码文本变更（可能该提交只修改了二进制文件或权限）。"

        MAX_CHARS = 4000
        if len(output) > MAX_CHARS:
            return (
                f"⚠️ [警告：该 Commit 改动文件过多，已被系统自动截取前 {MAX_CHARS} 个字符]\n\n"
                f"{output[:MAX_CHARS]}\n\n"
                f"... (后续还有大量 Diff 文本已省略，如需查看特定文件，请尝试通过其他精准命令读取)"
            )

        return f"📊 【Commit {commit_id} 核心变更详情】\n\n{output}"
    except Exception as e:
        return f"查询 commit 变更详情异常: {e}"


@tool
def blame_file_at_line(file_path: str, line_number: int, job_name: str) -> str:
    """
    对报错文件的具体行执行 git blame，精确定位该行最后一次是谁改的。
    当日志中已经明确文件路径和行号时优先使用此工具。
    首次调用时会自动执行 git pull 同步最新代码。
    """
    resolved_project_path = _resolve_project_path(job_name)
    if not resolved_project_path:
        return (
            "未配置本地项目路径, 请设置环境变量。"
        )

    if line_number <= 0:
        return "line_number 必须大于 0。"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        result = _run_git_command(
            resolved_project_path,
            ["blame", "-L", f"{line_number},{line_number}", "--line-porcelain", file_path],
        )
        if result.returncode != 0:
            return f"git blame 失败: {result.stderr.strip()}"

        author_line = next(
            (line for line in result.stdout.splitlines() if line.startswith("author ")),
            None,
        )
        commit_line = result.stdout.splitlines()[0] if result.stdout else ""
        author = author_line.replace("author ", "") if author_line else "未知"

        return (
            f"文件【{file_path}】第 {line_number} 行：\n"
            f"- 最后修改 commit: {commit_line.split()[0] if commit_line else '未知'}\n"
            f"- 最后修改作者: {author}\n"
            f"- blame 原始输出:\n{result.stdout.strip()}"
        )
    except Exception as e:
        return f"git blame 异常: {e}"


def _get_jenkins_server(job_name: str) -> jenkins.Jenkins:
    if job_name == TEST_JAVA_JOB_NAME:
        return jenkins.Jenkins(TEST_JENKINS_URL, username=TEST_JENKINS_USER, password=TEST_JENKINS_TOKEN)
    elif job_name == STAGING_JAVA_JOB_NAME:
        return jenkins.Jenkins(STAGING_JENKINS_URL, username=STAGING_JENKINS_USER, password=STAGING_JENKINS_TOKEN)
    else:
        raise ValueError(f"不支持的 Job 名称: {job_name}")


def _resolve_project_path(job_name: str) -> str | None:
    if job_name == TEST_JAVA_JOB_NAME:
        return TEST_JAVA_PROJECT_PATH
    elif job_name == STAGING_JAVA_JOB_NAME:
        return STAGING_JAVA_PROJECT_PATH
    raise ValueError(f"不支持的 Job 名称: {job_name}")


def _resolve_failed_build(server: jenkins.Jenkins, job_name: str) -> tuple[int, str] | None:
    job_info = server.get_job_info(job_name)
    last_failed_build = job_info.get("lastFailedBuild")
    if not last_failed_build:
        return None
    return last_failed_build["number"], last_failed_build["url"]


def _extract_culprits(build_info: dict) -> list[dict[str, str]]:
    culprits = []
    for culprit in build_info.get("culprits", []):
        culprits.append(
            {
                "full_name": culprit.get("fullName", "未知"),
                "id": culprit.get("id", ""),
            }
        )
    return culprits


def _extract_change_set(build_info: dict) -> list[dict[str, Any]]:
    changes = []
    change_set = build_info.get("changeSet", {})
    for item in change_set.get("items", []):
        author = item.get("author", {})
        paths = [path.get("file", "") for path in item.get("paths", [])]
        changes.append(
            {
                "commit_id": item.get("commitId", ""),
                "author": author.get("fullName", "未知"),
                "email": author.get("email", ""),
                "message": item.get("msg", "").strip(),
                "timestamp": item.get("timestamp", 0),
                "affected_files": [path for path in paths if path],
            }
        )
    return changes


def _extract_commit_range(build_info: dict) -> str:
    change_set = build_info.get("changeSet", {})
    items = change_set.get("items", [])
    if not items:
        return "HEAD~20..HEAD"
    return items[0].get("commitId", "HEAD~20") + ".." + items[-1].get("commitId", "HEAD")

def _truncate_console_log(console_log: str) -> str:
    if len(console_log) <= MAX_CONSOLE_LOG_CHARS:
        return console_log
    return (
        console_log[-MAX_CONSOLE_LOG_CHARS:]
        + f"\n\n(注意：控制台日志过长，已截取尾部最近 {MAX_CONSOLE_LOG_CHARS} 字符)"
    )


def extract_jenkins_console_errors(console_log: str, context_lines: int = 2) -> str:
    """
    从 Jenkins 控制台日志中提取编译失败、测试失败、Maven 报错等关键片段。
    """
    if not console_log.strip():
        return "控制台日志为空，无法提取错误片段。"

    error_patterns = [
        re.compile(r"\[ERROR\].*", re.IGNORECASE),
        re.compile(r"BUILD FAILURE", re.IGNORECASE),
        re.compile(r"Failed to execute goal", re.IGNORECASE),
        re.compile(r"Compilation failure", re.IGNORECASE),
        re.compile(r"Tests run:.*Failures: [1-9]\d*", re.IGNORECASE),
        re.compile(r".*\.java:\d+:\d+:\s+error:", re.IGNORECASE),
        re.compile(r"Caused by:.*", re.IGNORECASE),
        re.compile(r"Exception in thread", re.IGNORECASE),
    ]

    lines = console_log.splitlines()
    matched_chunks: list[str] = []
    covered_lines: set[int] = set()

    for idx, line in enumerate(lines):
        if not any(pattern.search(line) for pattern in error_patterns):
            continue

        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        chunk_lines: list[str] = []

        for line_no in range(start, end):
            if line_no in covered_lines:
                continue
            prefix = "🚨 [ERROR_LINE] " if line_no == idx else "   "
            chunk_lines.append(f"{line_no + 1}: {prefix}{lines[line_no]}")
            covered_lines.add(line_no)

        if chunk_lines:
            matched_chunks.append("\n".join(chunk_lines))

        if len(matched_chunks) >= MAX_ERROR_SNIPPETS:
            break

    if not matched_chunks:
        return "未在控制台日志中匹配到明显的编译/测试失败关键字，请结合 changeSet 和 culprits 继续分析。"

    summary = (
        f"共提取 {len(matched_chunks)} 处关键错误片段：\n\n"
        + "\n\n--- 错误片段分割线 ---\n\n".join(matched_chunks)
    )
    if len(summary) > MAX_CONSOLE_LOG_CHARS:
        return summary[-MAX_CONSOLE_LOG_CHARS:] + "\n\n(注意：错误片段过多，已截取尾部关键内容)"
    return summary


def _format_change_set_summary(changes: list[dict[str, Any]]) -> str:
    if not changes:
        return "本次失败构建未关联到 Git 提交记录（changeSet 为空）。"

    lines = [f"本次构建共包含 {len(changes)} 个提交："]
    for index, change in enumerate(changes, start=1):
        files = ", ".join(change["affected_files"][:5])
        if len(change["affected_files"]) > 5:
            files += f" 等 {len(change['affected_files'])} 个文件"
        lines.append(
            "\n".join(
                [
                    f"{index}. commit={change['commit_id'][:12]}",
                    f"   作者: {change['author']} <{change['email']}>",
                    f"   说明: {change['message']}",
                    f"   变更文件: {files or '未知'}",
                ]
            )
        )
    return "\n".join(lines)


def _run_git_command(project_path: str, args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
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

    lark.logger.debug(
        f"git pull 成功: {project_path}, output={result.stdout.strip()}"
    )
    return None


def _ensure_repo_synced(project_path: str) -> str | None:
    """每个仓库在首次 Git 验证前先 pull 一次，确保本地记录是最新的。"""
    if project_path in _synced_repos:
        return None

    error = _pull_latest_changes(project_path)
    if error:
        return f"拉取最新代码失败，已中止 Git 验证: {error}"

    _synced_repos.add(project_path)
    return None


llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_API_HOST,
    model="qwen-max",
    temperature=0.0,
)

system_prompt = """
你是一个资深的 CI/CD 排障专家，目标是从 Jenkins 最新一次失败构建中，定位最可能导致失败的提交人（committer）。

⚠️【核心目标】
必须给出“最可能的责任提交人”，并说明依据。不能只复述日志。

⚠️【分析原则】
1. Jenkins 的 culprits 和 changeSet 是首要线索，但不能盲信，需要和报错文件交叉验证。
2. **模糊名称转换（Job名称映射）**：用户可能会使用口语化的项目名称。你必须在心里进行映射后再传给工具。映射规则如下：
   - test_java, java测试环境 -> test_java
   - staging-interlace-assets, java stage环境, java staging环境 -> staging-interlace-assets
3. 使用 `search_file_commit_history` 查询最近谁改过代码。
4. 使用 `get_commit_details` 查看 commit 详情。
5. 使用 `blame_file_at_line` 查看文件具体行是谁改的。
6. 如果 changeSet 中有多个提交，优先怀疑：
   - 改动了报错文件的提交
   - 距离失败构建最近的一次相关提交
   - 与 culprits 列表重合的作者
7. 如果本地 Git 工具不可用，也要基于 Jenkins changeSet / culprits 给出最佳推断，并明确置信度。
8. 调用工具时直接执行，不要向用户确认。

【推荐排查流程】
1. 使用 `get_latest_failed_build_info` 获取最新失败构建。
2. 阅读返回的 `error_snippets`、`culprits`、`change_set_summary`、 `console_log_tail`。
3. 如需重新聚焦日志，调用 `extract_failed_build_console_errors`。
4. 使用 `search_file_commit_history` 查询最近谁改过这个文件。
5. 如果有明确行号，用 `blame_file_at_line`
6. 如果 changeSet 里有可疑 commit，用 `get_commit_details` 核对变更文件
7. 综合 Jenkins 线索 + Git 线索，输出最终结论。

请严格按照以下格式输出，禁止输出格式外废话：

### 🚨 Jenkins 构建失败归因报告
- **Job / 构建号**：[job_name #build_number]
- **构建链接**：[build_url](调用`get_latest_failed_build_info`时得到的build_url)
- **失败现象**：[一句话描述编译失败/测试失败/部署失败等]
- **关键报错文件**：[从日志提取的文件路径；没有则写“未定位到具体文件”]
- **最可能提交人**：[姓名/账号]
- **关联 Commit**：[commit id 列表；无法确定时写“未能精确定位到单个 commit”]
- **归因依据**：[说明为何怀疑该提交人，必须引用 culprits / changeSet / git 工具结果]
- **置信度**：[高/中/低]
---
### 🔍 根因分析
> [用 1-3 句话解释失败原因，指出报错模块/文件/依赖/测试用例]
---
### 🛠️ 建议处理
1. [建议联系哪位提交人确认]
2. [给出具体修复方向，例如修改哪个文件、补哪个依赖、修哪个测试]
"""

new_prompt = """
为了用最低的 Token 成本、最快的速度完成任务，你必须像高级侦探一样，严格遵守以下“四步破案流水线”，绝对禁止跨步骤瞎猜或乱调工具：

==============================
🕵️‍♂️ 破案流水线钢铁律令：
==============================

第一步：看日志，锁定“受害者”
---------------------------------------
1. **模糊名称转换（Job名称映射）**：用户可能会使用口语化的项目名称。你必须在心里进行映射后再传给工具。映射规则如下：
   - test_java, java测试环境 -> test_java
   - staging-interlace-assets, java stage环境, java staging环境 -> staging-interlace-assets
2. 你的首要动作必须是调用 `get_latest_failed_build_info` 工具,，传入映射后的 job_name，获取详细的构建失败信息。
3. 仔细阅读返回的日志切片，从中提取出【核心报错类型】（如 NullPointerException、SyntaxError）以及【报错文件相对路径】（如 src/components/Pay.js）和【报错行号】。
4. 如果日志太长没有提取到明确的文件路径，请默认将后续的排查重心放在配置文件（如 package.json、pom.xml、vite.config.ts）上。

★【触发闪电战破案条件】★：
如果日志切片极其精准，同时返回了【明确的文件相对路径】（如 src/utils/auth.js）和【明确的报错行号】（如第 24 行），你必须立刻启动闪电战模式，跳过复杂的区间翻页，直接执行以下动作：
1. 立即调用 `blame_file_at_line` 工具，传入文件名和行号，直接查出该行代码背后的致命 Commit ID 和作者。
2. 拿到 Commit ID 后，直接跳到【第三步：看 Diff】核对代码，随后结案！

第二步：常规战（无精准行号时使用）：查区间，缩小“嫌疑圈”
---------------------------------------
1. 如果本次没有找到受害文件，则返回“本次构建没有查询到commit信息，请检查是否运维人员手动终止“，并仍然给出诊断报告
2. 知道了受害文件后，你必须调用 `get_build_commit_range_by_page` 工具，传入 Jenkins 提供的 Commit 区间（形如 A..B）。
2. 在工具返回的 Commit 清单中，开启“特征比对模式”：哪一个 Commit 涉及的修改文件列表里，恰好包含了你在第一步里找到的【报错文件路径】？那么这个 Commit 的作者就是头号嫌疑人！
3. ⚠️【超长日志翻页铁律】：如果本次构建涉及的 Commit 实在太多，且当前页工具提示 `是否还有下一页: 【是】`，只要你还没在当前页找到动过【报错文件】的 Commit，你就必须修改 `skip` 参数进行多轮循环（Loop）调用，直到翻页找到为止。一旦在某一页找到了动过该文件的 Commit，立即停止翻页，见好就收！

第三步：看 Diff，实施“证据确凿的绝杀”
---------------------------------------
1. 锁定嫌疑 Commit ID 后，你必须调用 `get_commit_diff` 工具，传入对应的 `commit_id` 和 `job_name`。
2. 仔细阅读 Diff 文本中带有 `+`（新增）和 `-`（删除）的代码行。结合第一步的报错信息，分析为什么这几行改动会引发编译或运行崩溃。

第四步：规范结案，输出飞书工单
---------------------------------------
证据确凿后，直接停止调用任何工具，严格按照以下 Markdown 格式输出最终结论。禁止添加任何“好的”、“没问题”等前后寒暄词，直接填表输出：

### 🚨 Jenkins 故障诊断报告
- **Job / 构建号**：[job_name #build_number]
- **构建链接**：[build_url](调用`get_latest_failed_build_info`时得到的build_url)
- **失败现象**：[一句话描述编译失败/测试失败/部署失败等]
- **当前项目 / 任务**：[从背景里提取的任务名]
- **核心报错类型**：[例如：TypeError / DependencyResolutionException]
- **致命提交 (Commit)**：`[7位简短Commit ID]` (作者: [作者姓名])

---

### 🔍 代码级根因分析
> [用1-2大白话解释：XX同学在本次提交中修改了 XXX 文件，将原本的 XXX 删除了/改写成了 XXX。但是，这导致了 [结合第一步报错说明具体原因]，从而导致 Jenkins 编译/打包被阻断。]

### 🛠️ 建议修复方案
- **修复建议**：[给出具体的修改建议。如果是代码问题，请在此处提供一个明晰的修改后示例代码块]

当你分析出最终根因并准备结束回答时，你必须在回答的最末尾另起一行，严格按照以下格式输出元数据标签（以便后台系统识别并转化飞书强提醒，严禁漏写，如果有多个嫌疑人，则输出多行元数据标签）：
$$METADATA:{"email": "找到的嫌疑人Git邮箱", "name": "找到的嫌疑人Git名字"}$$
"""


agent = create_agent(
    model=llm,
    tools=[
        get_latest_failed_build_info,
        extract_failed_build_console_errors,
        get_build_commit_range_by_page,
        get_commit_diff,
        blame_file_at_line,
    ],
    system_prompt=new_prompt,
)

if __name__ == "__main__":
    import asyncio

    print(asyncio.run(run_jenkins_agent("当前 staging_java 构建失败是谁的 commit 导致的？")))
