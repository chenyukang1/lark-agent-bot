import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel

from app import lark
from app.config import CodebaseConfig, get_config
from app.integrations.git import GitCommandError, GitRepository
from app.integrations.jenkins import JenkinsClient

MAX_DIFF_CHARS = 100_000


@dataclass
class BuildChanges:
    commits: dict[str, dict]
    patches: str


class JenkinsBuildEvent(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: str | None = None


logger = logging.getLogger(__name__)


def get_latest_failed_build_info(alias: str) -> str:
    """
    获取指定 Jenkins Job 最新一次失败构建的完整信息。
    :return jenkins_job_name: Jenkins Job 名称
    :return build_number: 构建号
    :return build_url: 构建 URL
    :return duration_ms: 构建时长
    :return commit_range: Commit 区间
    :return error_snippets: 从控制台提取的错误片段
    :return git_branch: Git 分支名称
    :param jenkins_job_name: Jenkins Job 名称
    """

    code_base_config: CodebaseConfig = get_config()["codebase_configs"][alias]
    server = JenkinsClient(
        code_base_config.jenkins_url,
        username=code_base_config.jenkins_user,
        password=code_base_config.jenkins_token,
    )

    try:
        job_info = server.get_job_info(code_base_config.jenkins_job_name)
        last_failed_build = job_info.get("lastFailedBuild")
        if not last_failed_build:
            return f"Job【{code_base_config.jenkins_job_name}】当前没有失败构建记录。"

        failed_build_number, failed_build_url = (
            last_failed_build["number"],
            last_failed_build["url"],
        )
        build_info = server.get_build_info(
            code_base_config.jenkins_job_name, failed_build_number
        )
        console_log = server.get_build_console_output(
            code_base_config.jenkins_job_name, failed_build_number
        )

        commit_range = _extract_commit_range(build_info)
        build_errors = _extract_jenkins_build_errors(console_log)
        server_errors = _extract_server_startup_errors(console_log)

        payload = {
            "jenkins_job_name": code_base_config.jenkins_job_name,
            "build_number": failed_build_number,
            "build_url": failed_build_url,
            "duration_ms": build_info.get("duration", 0),
            "commit_range": commit_range,
            "build_errors": build_errors,
            "server_errors": server_errors,
            "project_path": code_base_config.project_path,
            "git_branch": code_base_config.git_branch,
        }

        lark.logger.debug(
            f"获取 Jenkins 失败构建成功: job={code_base_config.jenkins_job_name}, build=#{failed_build_number}"
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as e:
        lark.logger.exception(
            f"获取 Jenkins 信息失败: job={code_base_config.jenkins_job_name}, error={e}"
        )
        return f"获取 Jenkins 信息失败: {e}"


def trigger_jenkins_build(alias: str) -> str:
    """使用指定别名的 Jenkins 配置触发一次构建。"""
    code_base_config: CodebaseConfig | None = get_config()["codebase_configs"].get(
        alias
    )
    if not code_base_config:
        return f"未找到别名【{alias}】对应的 Jenkins 配置。"

    server = JenkinsClient(
        code_base_config.jenkins_url,
        username=code_base_config.jenkins_user,
        password=code_base_config.jenkins_token,
    )

    try:
        queue_id = server.build_job(code_base_config.jenkins_job_name)
        lark.logger.info(
            f"Jenkins 打包已触发: job={code_base_config.jenkins_job_name}, queue_id={queue_id}"
        )
        job_url = (
            f"{code_base_config.jenkins_url.rstrip('/')}/job/"
            f"{code_base_config.jenkins_job_name}/"
        )
        return (
            f"已触发 Jenkins 打包任务【{code_base_config.jenkins_job_name}】。"
            f"队列 ID：{queue_id}\n"
            f"Jenkins 地址：[查看任务]({job_url})"
        )
    except Exception as e:
        lark.logger.exception(
            f"触发 Jenkins 打包失败: job={code_base_config.jenkins_job_name}, error={e}"
        )
        return f"触发 Jenkins 打包失败: {e}"


def _extract_commit_range(build_info: dict) -> str:
    change_set = build_info.get("changeSet", {})
    items = change_set.get("items", [])
    if not items:
        return ""
    return items[0].get("commitId") + ".." + items[-1].get("commitId")


def collect_build_changes(config: CodebaseConfig, build_number: int) -> BuildChanges:
    server = JenkinsClient(
        config.jenkins_url,
        username=config.jenkins_user,
        password=config.jenkins_token,
    )
    build = server.get_build_info(config.jenkins_job_name, build_number)
    if "changeSet" not in build and "changeSets" not in build:
        raise ValueError("构建缺少 changeSet/changeSets，无法确定提交范围")
    change_sets = [build.get("changeSet") or {}, *(build.get("changeSets") or [])]
    ids = list(
        dict.fromkeys(
            item.get("commitId", "")
            for changes in change_sets
            for item in changes.get("items", [])
        )
    )
    if any(not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", cid) for cid in ids):
        raise ValueError("changeSet 中存在无效或缺失的 Git commit ID")
    repo = GitRepository(config.project_path, timeout=60)
    commits = {}
    patches = []
    fetched = False
    for cid in ids:
        try:
            repo.require_commit(cid)
        except GitCommandError:
            if not fetched:
                repo.fetch()
                fetched = True
            repo.require_commit(cid)
        name, email = repo.commit_author(cid)
        patch, files = repo.commit_changes(cid)
        commits[cid] = {
            "name": name,
            "email": email,
            "files": set(files),
            "patch": patch,
        }
        patches.append(f"COMMIT {cid}\n{patch}")
        if sum(map(len, patches)) > MAX_DIFF_CHARS:
            raise ValueError(
                "构建 diff 超过分析上限，需人工检查 SQL；未截断后交给模型判断"
            )
    return BuildChanges(commits=commits, patches="\n\n".join(patches))


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
    ]

    error_index = -1
    lines = console_log.splitlines()
    for i, line in enumerate(lines):
        if any(re.search(kw, line, re.IGNORECASE) for kw in keywords):
            error_index = i
            break

    if error_index != -1:
        logger.debug(f"构建错误成功匹配到核心错误起点（第 {error_index} 行）")
        return "\n".join(lines[error_index:])

    logger.debug(f"构建错误未匹配到核心错误起点，返回最后 {max_lines} 行")
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
        logger.debug(f"启动日志成功匹配到核心错误起点（第 {error_index} 行）")
        return "\n".join(lines[error_index + 1 : error_index + 101])
    else:
        logger.debug("启动日志未匹配到核心错误起点")
        return ""
