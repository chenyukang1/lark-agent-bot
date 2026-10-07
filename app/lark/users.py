import json
import logging
import os
from pathlib import Path

from lark_oapi.api.contact.v3 import (
    FindByDepartmentUserRequest,
    FindByDepartmentUserResponse,
)

from app.config import get_config

from . import lark_client

_mapping: dict[str, str] | None = None

logger = logging.getLogger(__name__)


def load_user_mapping() -> dict[str, str]:
    global _mapping

    path = _mapping_path()
    if not path.is_file():
        logger.warning("飞书邮箱映射文件不存在: %s", path)
        _mapping = {}
        return _mapping

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise TypeError(f"feishu mapping 文件格式错误，根节点必须是对象: {path}")

    _mapping = {
        email.lower(): open_id
        for email, open_id in data.items()
        if isinstance(email, str) and isinstance(open_id, str) and email and open_id
    }
    logger.info("已加载 %d 条飞书邮箱映射: %s", len(_mapping), path)
    return _mapping


def resolve_open_id(name: str | None, email: str | None) -> str:
    if not name and not email:
        return ""

    if _mapping is None:
        load_user_mapping()

    assert _mapping is not None

    open_id = _mapping.get(email.lower(), "") if email else ""

    if open_id:
        return open_id

    notify_department_id = get_config()["notify_department_id"]
    if not notify_department_id or not name:
        return ""

    users = _find_users_by_department(notify_department_id)
    return users.get(name.lower(), "")


def _mapping_path() -> Path:
    custom = os.getenv("USER_MAPPING_PATH")
    if custom:
        return Path(custom)

    return Path(__file__).resolve().parents[2] / "user_mapping.json"


def _find_users_by_department(department_id: str) -> dict[str, str]:
    users: dict[str, str] = {}
    page_token = None
    while True:
        builder = (
            FindByDepartmentUserRequest.builder()
            .user_id_type("open_id")
            .department_id_type("open_department_id")
            .department_id(department_id)
            .page_size(10)
        )
        if page_token:
            builder.page_token(page_token)

        request = builder.build()

        try:
            response: FindByDepartmentUserResponse = (
                lark_client.contact.v3.user.find_by_department(request)
            )
        except Exception as e:
            logger.error("获取飞书用户信息失败: %s", e)
            break

        if not response.success():
            logger.error("获取飞书用户信息失败: %d %s", response.code, response.msg)
            break

        if response.data is None or not response.data.items:
            break

        for item in response.data.items:
            if item.nickname:
                users.update({item.nickname.lower(): item.open_id})

        if response.data.has_more:
            page_token = response.data.page_token
        else:
            break

    return users
