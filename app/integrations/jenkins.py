"""The Jenkins SDK boundary, reusable outside the bot."""

import jenkins


class JenkinsClient:
    def __init__(self, url: str, *, username: str, password: str) -> None:
        self._server = jenkins.Jenkins(url, username=username, password=password)

    def get_job_info(self, job_name: str) -> dict:
        return self._server.get_job_info(job_name)

    def get_build_info(self, job_name: str, build_number: int) -> dict:
        return self._server.get_build_info(job_name, build_number)

    def get_build_console_output(self, job_name: str, build_number: int) -> str:
        return self._server.get_build_console_output(job_name, build_number)

    def build_job(self, job_name: str) -> int:
        return self._server.build_job(job_name)
