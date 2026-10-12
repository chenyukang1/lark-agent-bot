import json
import logging
import os
from pathlib import Path

from app.config import get_config

from . import get_lark_client

_mapping: dict[str, str] | None = None

logger = logging.getLogger(__name__)


def load_user_mapping() -> dict[str, str]:
    global _mapping

    path = _mapping_path()
    if not path.is_file():
        logger.error("用户邮箱映射文件不存在: %s", path)
        raise ValueError("用户邮箱映射文件不存在")

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise TypeError(f"用户邮箱映射文件格式错误，根节点必须是对象: {path}")

    _mapping = {
        email.lower(): open_id
        for email, open_id in data.items()
        if isinstance(email, str) and isinstance(open_id, str) and email and open_id
    }
    if not _mapping or len(_mapping) == 0:
        logger.error("用户邮箱映射为空")
        raise ValueError("用户邮箱映射为空")

    logger.info("已加载 %d 条用户邮箱映射: %s", len(_mapping), path)
    return _mapping


def resolve_open_id(name: str | None, email: str | None) -> str:
    if not name and not email:
        return ""

    assert _mapping is not None

    open_id = _mapping.get(email.lower(), "") if email else ""

    if open_id:
        return open_id

    notify_department_id = get_config()["notify_department_id"]
    if not notify_department_id or not name:
        return ""

    users = get_lark_client().find_users_by_department(notify_department_id)
    return users.get(name.lower(), "")


def _mapping_path() -> Path:
    custom = os.getenv("USER_MAPPING_PATH")
    if custom:
        return Path(custom)

    return Path(__file__).resolve().parents[2] / "user_mapping.json"
