from pydantic import BaseModel, Field

class WebhookPayload(BaseModel):
    job_name: str
    build_number: int = Field(gt=0)
    build_url: str
    phase: str | None = None
