from pydantic import BaseModel, Field


class CodebaseConfig(BaseModel):
    jenkins_job_name: str = Field(description="Jenkins Job 名称，作为配置字典的 key")
    jenkins_url: str = Field(description="Jenkins URL")
    jenkins_user: str = Field(description="Jenkins Username")
    jenkins_token: str = Field(description="Jenkins Token")
    project_path: str = Field(description="本地 Git 项目路径")
