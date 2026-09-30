"""The Jenkins SDK boundary, reusable outside the bot."""

import json
import logging
import re
from threading import Lock

import jenkins

from app.config import CodebaseConfig, get_config

logger = logging.getLogger(__name__)


class JenkinsClientPool:
    def __init__(self) -> None:
        self._pool: dict[str, JenkinsClient] = {}
        self._lock = Lock()

    def get_jenkins_client(self, alias: str) -> JenkinsClient:
        client = self._pool.get(alias)
        if client is not None:
            return client

        with self._lock:
            client = self._pool.get(alias)
            if client is None:
                codebase_config: CodebaseConfig = get_config()["codebase_configs"][
                    alias
                ]
                client = JenkinsClient(
                    codebase_config=codebase_config,
                )
                self._pool[alias] = client

        return client


class JenkinsClient:
    def __init__(self, codebase_config: CodebaseConfig) -> None:
        self._server = jenkins.Jenkins(
            url=codebase_config.jenkins_url,
            username=codebase_config.jenkins_user,
            password=codebase_config.jenkins_token,
        )
        self._codebase_config = codebase_config

    def get_job_info(self) -> dict:
        return self._server.get_job_info(self._codebase_config.jenkins_job_name)

    def get_build_info(self, build_number: int) -> dict:
        return self._server.get_build_info(
            self._codebase_config.jenkins_job_name, build_number
        )

    def get_build_console_output(self, build_number: int) -> str:
        return self._server.get_build_console_output(
            self._codebase_config.jenkins_job_name, build_number
        )

    def build_job(self) -> int:
        return self._server.build_job(self._codebase_config.jenkins_job_name)

    def get_latest_failed_build_info(self) -> str:
        """
        获取当前客户端绑定的 Jenkins Job 最新一次失败构建的完整信息。
        :return jenkins_job_name: Jenkins Job 名称
        :return build_number: 构建号
        :return build_url: 构建 URL
        :return duration_ms: 构建时长
        :return commit_range: Commit 区间
        :return error_snippets: 从控制台提取的错误片段
        :return git_branch: Git 分支名称
        """
        job_name = self._codebase_config.jenkins_job_name
        try:
            job_info = self.get_job_info()
            last_failed_build = job_info.get("lastFailedBuild")
            if not last_failed_build:
                raise JenkinsBuildException(f"{job_name} 当前没有失败构建记录")

            failed_build_number, failed_build_url = (
                last_failed_build["number"],
                last_failed_build["url"],
            )
            build_info = self.get_build_info(failed_build_number)
            console_log = self.get_build_console_output(failed_build_number)

            commit_range = self._extract_commit_range(build_info)
            build_errors = self.extract_jenkins_build_errors(console_log)
            server_errors = self.extract_server_startup_errors(console_log)

            payload = {
                "jenkins_job_name": job_name,
                "build_number": failed_build_number,
                "build_url": failed_build_url,
                "duration_ms": build_info.get("duration", 0),
                "commit_range": commit_range,
                "build_errors": build_errors,
                "server_errors": server_errors,
                "project_path": self._codebase_config.project_path,
                "git_branch": self._codebase_config.git_branch,
            }

            return json.dumps(payload, ensure_ascii=False, indent=2)

        except Exception:
            logger.exception("获取 Jenkins 信息失败")
            return "获取 Jenkins 最新失败构建失败"

    def extract_jenkins_build_errors(
        self, console_log: str, max_lines: int = 60
    ) -> str:
        """从 Jenkins 控制台日志中提取编译失败、测试失败、Maven 报错等关键行。"""
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

    def extract_server_startup_errors(self, console_log: str) -> str:
        """从 Jenkins 控制台日志中提取服务器启动日志"""
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

    def _extract_commit_range(self, build_info: dict) -> str:
        change_set = build_info.get("changeSet", {})
        items = change_set.get("items", [])
        if not items:
            return ""
        return items[0].get("commitId") + ".." + items[-1].get("commitId")


class JenkinsBuildException(Exception):
    """Jenkins build exception"""
