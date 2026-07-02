import json
import os
from pathlib import Path
from pydantic import TypeAdapter

from devops.codebase_config import CodebaseConfig

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "codebase_configs.json"


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
    result = {config.job_name: config for config in configs}

    if len(result) != len(configs):
        raise ValueError(f"Codebase 配置中存在重复 job_name: {path}")

    return result


CODEBASE_CONFIGS = load_codebase_configs()
