from dataclasses import dataclass
from pydantic import BaseModel

@dataclass
class DDLReminder:
    commit_id: str
    markdown: str


@dataclass
class BuildChanges:
    commits: dict[str, dict]
    patches: str

class JenkinsBuildEvent(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: str | None = None
