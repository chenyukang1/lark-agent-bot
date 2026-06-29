import json
import os
from pathlib import Path

import lark_oapi as lark

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "feishu_mapping.json"
_mapping: dict[str, str] | None = None


def _mapping_path() -> Path:
    custom = os.getenv("FEISHU_MAPPING_PATH")
    if custom:
        return Path(custom)
    return _DEFAULT_PATH


def load_feishu_mapping() -> dict[str, str]:
    global _mapping

    path = _mapping_path()
    if not path.is_file():
        lark.logger.warning("飞书邮箱映射文件不存在: %s", path)
        _mapping = {}
        return _mapping

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"feishu mapping 文件格式错误，根节点必须是对象: {path}")

    _mapping = {
        email.lower(): open_id
        for email, open_id in data.items()
        if isinstance(email, str) and isinstance(open_id, str) and email and open_id
    }
    lark.logger.info("已加载 %d 条飞书邮箱映射: %s", len(_mapping), path)
    return _mapping


def resolve_open_id(email: str | None) -> str:
    if not email:
        return ""

    if _mapping is None:
        load_feishu_mapping()

    assert _mapping is not None
    return _mapping.get(email.lower(), "")
