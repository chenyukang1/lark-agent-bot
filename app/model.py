from pydantic import BaseModel, Field

from app.config import CodebaseConfig


class JenkinsBuildEvent(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: str | None = None
    codebase_confg: CodebaseConfig | None = None


class WebhookPayload(BaseModel):
    job_name: str
    build_number: int = Field(gt=0)
    build_url: str
    phase: str | None = None
