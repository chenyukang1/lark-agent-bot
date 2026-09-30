import json
from typing import Any

import lark_oapi as lark

from app.config import get_config
from app.parsers.build_logs import extract_jenkins_console_errors
from app.parsers.build_logs import (
    truncate_console_log as _truncate_console_log,
)
from app.tools.jenkins import JenkinsClient


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
        errors = extract_jenkins_console_errors(console_log)
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
