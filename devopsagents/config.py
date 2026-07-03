import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, TypeAdapter
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "codebase_configs.json"


class CodebaseConfig(BaseModel):
    jenkins_job_name: str = Field(description="Jenkins Job 名称，作为配置字典的 key")
    jenkins_url: str = Field(description="Jenkins URL")
    jenkins_user: str = Field(description="Jenkins Username")
    jenkins_token: str = Field(description="Jenkins Token")
    project_path: str = Field(description="本地 Git 项目路径")


def _config_path() -> Path:
    path = os.getenv("CODEBASE_CONFIGS_PATH", _DEFAULT_PATH)
    return Path(path)


def load_codebase_configs() -> dict[str, CodebaseConfig]:
    path = _config_path()
    if not path.is_file():
        raise ValueError(f"Codebase 配置文件不存在: {path}")

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"Codebase 配置文件格式错误，根节点必须是数组: {path}")

    configs = TypeAdapter(list[CodebaseConfig]).validate_python(data)
    result = {config.jenkins_job_name: config for config in configs}

    if len(result) != len(configs):
        raise ValueError(f"Codebase 配置中存在重复 job_name: {path}")

    return result


DEFAULT_CONFIG = dict(
    {
        "codebase_configs": load_codebase_configs(),
        "dashscope_api_key": os.getenv("DASHSCOPE_API_KEY"),
        "dashscope_api_host": os.getenv("DASHSCOPE_API_HOST"),
    }
)
