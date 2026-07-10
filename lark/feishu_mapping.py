import json
import os
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.contact.v3 import (
    FindByDepartmentUserRequest,
    FindByDepartmentUserResponse,
)

from devopsagents.config import DEFAULT_CONFIG

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "feishu_mapping.json"
_mapping: dict[str, str] | None = None


def _mapping_path() -> Path:
    custom = os.getenv("FEISHU_MAPPING_PATH")
    if custom:
        return Path(custom)
    return _DEFAULT_PATH


def _find_users_by_department(
    client: lark.Client, department_id: str
) -> dict[str, str]:
    users: dict[str, str] = {}
    page_token = None
    while True:
        request: FindByDepartmentUserRequest = (
            FindByDepartmentUserRequest.builder()
            .user_id_type("open_id")
            .department_id_type("open_department_id")
            .department_id(department_id)
            .page_size(10)
            .build()
        )
        if page_token:
            request.page_token = page_token

        try:
            response: FindByDepartmentUserResponse = (
                client.contact.v3.user.find_by_department(request)
            )
        except Exception as e:
            lark.logger.error("获取飞书用户信息失败: %s", e)
            break

        users.update(
            {
                item.nickname.lower()
                if item.nickname
                else item.name.lower(): item.open_id
                for item in response.data.items
            }
        )

        if response.data.has_more:
            page_token = response.data.page_token
        else:
            break

    return users


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


def resolve_open_id(client: lark.Client, name: str | None, email: str | None) -> str:
    if not name and not email:
        return ""

    if _mapping is None:
        load_feishu_mapping()

    assert _mapping is not None

    open_id = _mapping.get(email.lower(), "") if email else ""

    if open_id:
        return open_id

    notify_department_id = DEFAULT_CONFIG["notify_department_id"]
    if not notify_department_id or not name:
        return ""

    users = _find_users_by_department(client, notify_department_id)
    return users.get(name.lower(), "")
