import json
import os
from contextvars import ContextVar
from typing import Any

import lark_oapi as lark

from app.config import get_config
from app.parsers import BUILD_LOG_PARSER
from app.tools.git import GitRepository
from app.tools.jenkins import JenkinsClient

# Each agent invocation has its own synchronization state.
_synced_repos: ContextVar[set[str] | None] = ContextVar("synced_repos", default=None)


def get_latest_failed_build_info(job_name: str) -> str:
    """
    获取指定 Jenkins Job 最新一次失败构建的完整信息。
    :return job_name: Job 名称
    :return build_number: 构建号
    :return build_url: 构建 URL
    :return build_result: 构建结果
    :return duration_ms: 构建时长
    :return commit_range: Commit 区间
    :return error_snippets: 从控制台提取的错误片段
    :param job_name: Job 名称
    """
    server = _get_jenkins_server(job_name)

    try:
        resolved = _resolve_failed_build(server)
        if not resolved:
            return f"Job【{job_name}】当前没有失败构建记录。"

        failed_build_number, failed_build_url = resolved
        build_info = server.get_build_info(failed_build_number)
        console_log = server.get_build_console_output(failed_build_number)

        culprits = _extract_culprits(build_info)
        changes = _extract_change_set(build_info)
        commit_range = _extract_commit_range(build_info)
        error_snippets = BUILD_LOG_PARSER.extract_jenkins_console_errors(console_log)

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
            "console_log_tail": BUILD_LOG_PARSER.truncate_console_log(console_log),
        }

        lark.logger.debug(
            f"获取 Jenkins 失败构建成功: job={job_name}, build=#{failed_build_number}"
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as e:
        lark.logger.exception(f"获取 Jenkins 信息失败: job={job_name}, error={e}")
        return f"获取 Jenkins 信息失败: {e}"


def extract_failed_build_console_errors(job_name: str) -> str:
    """
    仅针对指定 Job 最新失败构建，从控制台日志中提取编译错误、测试失败、
    Maven 执行失败等关键报错片段。适合在已拿到构建号后做二次聚焦分析。
    :param job_name: Job 名称
    """
    server = _get_jenkins_server(job_name)
    try:
        resolved = _resolve_failed_build(server)
        if not resolved:
            return f"Job【{job_name}】当前没有失败构建记录。"
        failed_build_number, failed_build_url = resolved
        console_log = server.get_build_console_output(failed_build_number)
        errors = BUILD_LOG_PARSER.extract_jenkins_console_errors(console_log)
        return (
            f"Job【{job_name}】构建 #{failed_build_number}\n"
            f"URL: {failed_build_url}\n\n{errors}"
        )
    except Exception as e:
        lark.logger.exception(f"提取控制台错误失败: job={job_name}, error={e}")
        return f"提取控制台错误失败: {e}"


def _get_jenkins_server(job_name: str) -> JenkinsClient:
    config = get_config()["codebase_configs"][job_name]
    return JenkinsClient(codebase_config=config)


def _resolve_failed_build(server: JenkinsClient) -> tuple[int, str] | None:
    job_info = server.get_job_info()
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
    return (
        items[0].get("commitId", "HEAD~20") + ".." + items[-1].get("commitId", "HEAD")
    )


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


def search_file_commit_history(job_name: str, max_count: int = 40) -> str:
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
        return "未配置本地项目路径, 请设置环境变量。"

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
        result = GitRepository(resolved_project_path, check=False).run(cmd[1:])

        if result.returncode != 0:
            return f"查询文件修改历史失败: {result.stderr.strip()}"

        if not result.stdout.strip():
            return f"在最近 {max_count} 个提交中，没有任何人修改过【{resolved_project_path}】。"

        return f"项目【{resolved_project_path}】中修改过的提交历史：\n{result.stdout}"
    except Exception as e:
        return f"查询文件修改历史异常: {e}"


def get_build_commit_range_by_page(
    job_name: str, commit_range: str, limit: int = 20, skip: int = 0
) -> str:
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
        return "未配置本地项目路径, 请设置环境变量。"

    if not os.path.isdir(resolved_project_path):
        return f"本地项目路径不存在: {resolved_project_path}"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        # 1. 先查一下这个区间总共有多少个 Commit
        count_cmd = ["git", "rev-list", "--count", commit_range]
        result = GitRepository(resolved_project_path, check=False).run(count_cmd[1:])
        if result.returncode != 0:
            return f"获取 Git count 失败: {result.stderr}"

        total_commits = int(result.stdout.strip())

        # 2. 分页拉取 Commit 摘要和修改的文件名
        # --skip 和 -n 是 git log 原生支持的分页参数
        cmd = [
            "git",
            "log",
            commit_range,
            f"--skip={skip}",
            "-n",
            str(limit),
            "--pretty=format:👉 [COMMIT] %h | 作者: %an | 说明: %s\n修改文件:",
            "--name-only",
        ]

        result = GitRepository(resolved_project_path, check=False).run(cmd[1:])

        if result.returncode != 0:
            return f"获取 Git 变更日志失败: {result.stderr}"

        current_output = result.stdout.strip()
        has_more = (skip + limit) < total_commits
        next_skip = skip + limit

        # 3. 构造返回文本，给大模型留下极其明确的“翻页线索”
        summary = (
            f"📊 [分页导航] 当前显示第 {skip + 1} 到 {min(next_skip, total_commits)} 条 (总计 {total_commits} 条 Commit)。\n"
            f"💡 是否还有下一页: {'【是】' if has_more else '【否】'}\n"
            f"💡 如下一页为【是】，请在下轮循环中继续调用本工具，并设置参数 skip={next_skip}。\n\n"
            f"=== 变更集切片 ===\n\n{current_output}"
        )
        return summary

    except Exception as e:
        return f"执行 Git 分页查询异常: {e!s}"


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
        return "未配置本地项目路径, 请设置环境变量。"

    if not os.path.isdir(resolved_project_path):
        return f"本地项目路径不存在: {resolved_project_path}"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        show_result = GitRepository(resolved_project_path, check=False).run(
            ["show", commit_id, "--unified=3", "--stat"],
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


def blame_file_at_line(file_path: str, line_number: int, job_name: str) -> str:
    """
    对报错文件的具体行执行 git blame，精确定位该行最后一次是谁改的。
    当日志中已经明确文件路径和行号时优先使用此工具。
    首次调用时会自动执行 git pull 同步最新代码。
    """
    resolved_project_path = _resolve_project_path(job_name)
    if not resolved_project_path:
        return "未配置本地项目路径, 请设置环境变量。"

    if line_number <= 0:
        return "line_number 必须大于 0。"

    sync_error = _ensure_repo_synced(resolved_project_path)
    if sync_error:
        return sync_error

    try:
        result = GitRepository(resolved_project_path, check=False).run(
            [
                "blame",
                "-L",
                f"{line_number},{line_number}",
                "--line-porcelain",
                file_path,
            ],
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


def _resolve_project_path(job_name: str) -> str:
    return get_config()["codebase_configs"][job_name].project_path


def _pull_latest_changes(project_path: str) -> str | None:
    result = GitRepository(project_path, timeout=60, check=False).run(["pull"])
    if result.returncode != 0:
        lark.logger.error(f"git pull 失败: {project_path}, error={result.stderr}")
        detail = (result.stderr or result.stdout or "").strip()
        return detail or "git pull 失败"

    lark.logger.debug(f"git pull 成功: {project_path}, output={result.stdout.strip()}")
    return None


def _ensure_repo_synced(project_path: str) -> str | None:
    """每个仓库在首次 Git 验证前先 pull 一次，确保本地记录是最新的。"""
    synced = _synced_repos.get()
    if synced is None:
        synced = set()
        _synced_repos.set(synced)
    if project_path in synced:
        return None

    error = _pull_latest_changes(project_path)
    if error:
        return f"拉取最新代码失败，已中止 Git 验证: {error}"

    synced.add(project_path)
    return None
