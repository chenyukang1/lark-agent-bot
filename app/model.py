from pydantic import BaseModel


class JenkinsBuildEvent(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: str | None = None
