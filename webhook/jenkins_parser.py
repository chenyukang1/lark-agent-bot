import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel


class JenkinsBuildEvent(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: str | None = None


def _extract_job_name_from_url(url: str) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.strip("/")
    match = re.search(r"/job/(.+?)/(?:\d+/?)?$", f"/{path}/")
    if match:
        return match.group(1).replace("/job/", "/")
    match = re.search(r"job/(.+?)(?:/\d+)?/?$", path)
    if match:
        return match.group(1).replace("/job/", "/")
    return None


def _coerce_status(value: Any) -> str:
    if value is None:
        return ""
    return str(value).upper()


def parse_jenkins_webhook(payload: dict[str, Any]) -> JenkinsBuildEvent | None:
    build = payload.get("build") or {}
    if not isinstance(build, dict):
        build = {}

    job_name = (
        payload.get("name")
        or payload.get("job_name")
        or payload.get("jobName")
        or (payload.get("project") or {}).get("name")
        or (payload.get("job") or {}).get("name")
    )

    build_number = build.get("number") or payload.get("build_number") or payload.get("buildNumber")
    build_url = (
        build.get("full_url")
        or build.get("url")
        or payload.get("build_url")
        or payload.get("buildUrl")
        or payload.get("url")
    )

    if not job_name and isinstance(build_url, str):
        job_name = _extract_job_name_from_url(build_url)

    if not job_name:
        return None

    if build_number is None and isinstance(build_url, str):
        match = re.search(r"/(\d+)/?$", build_url.rstrip("/"))
        if match:
            build_number = int(match.group(1))

    if build_number is None:
        return None

    status = _coerce_status(build.get("status") or payload.get("status") or payload.get("result"))
    phase = build.get("phase") or payload.get("phase")

    if isinstance(build_url, str) and not build_url.startswith("http"):
        base_url = payload.get("build_host_url") or payload.get("jenkins_url") or ""
        if base_url:
            build_url = f"{base_url.rstrip('/')}/{build_url.lstrip('/')}"

    return JenkinsBuildEvent(
        job_name=str(job_name),
        build_number=int(build_number),
        build_url=str(build_url or ""),
        status=status,
        phase=str(phase) if phase else None,
    )


def should_analyze_build(event: JenkinsBuildEvent) -> bool:
    if event.status != "FAILURE":
        return False
    if event.phase and event.phase.upper() not in {"COMPLETED", "FINALIZED", "FINISHED"}:
        return False
    return True


def build_agent_instruction(event: JenkinsBuildEvent) -> str:
    parts = [
        f"Jenkins Job【{event.job_name}】构建失败，",
        "请分析最可能导致失败的提交人（committer）。",
    ]
    return "".join(parts)
