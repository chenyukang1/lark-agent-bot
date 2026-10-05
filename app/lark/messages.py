import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    PatchMessageRequest,
    PatchMessageRequestBody,
    PatchMessageResponse,
)
from pydantic import BaseModel, ValidationError

from app.lark.users import resolve_open_id


class SendMessagePayload(BaseModel):
    receive_id_type: Literal["chat_id", "open_id"]
    receive_id: str
    msg_type: str
    content: str


class SendAlarmCardPayload(BaseModel):
    receive_id_type: Literal["chat_id", "open_id"]
    receive_id: str
    report_content: str


class SendSQLNoticeCardPayload(BaseModel):
    receive_id_type: Literal["chat_id", "open_id"]
    receive_id: str
    report_content: str


class UpdateAlarmCardPayload(BaseModel):
    message_id: str
    report_content: str
    status: Literal["pending", "success", "failed"] = "pending"


class SendMessageErrorDetail(BaseModel):
    code: Any = None
    msg: str = "unknown"
    log_id: str = ""
    receive_id_type: str
    receive_id: str
    msg_type: str


class SendMessageError(Exception):
    def __init__(self, detail: SendMessageErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.model_dump_json(ensure_ascii=False))


# 发送消息
# # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
def send_message(client, payload: SendMessagePayload) -> CreateMessageResponse:
    try:
        payload = SendMessagePayload.model_validate(payload)
    except ValidationError:
        lark.logger.exception("send_message 参数校验失败")
        raise

    request = (
        CreateMessageRequest.builder()
        .receive_id_type(payload.receive_id_type)
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(payload.receive_id)
            .msg_type(payload.msg_type)
            .content(payload.content)
            .build()
        )
        .build()
    )

    # 使用发送OpenAPI发送通知卡片，你可以在API接口中打开 API 调试台，快速复制调用示例代码
    # Use send OpenAPI to send notice card. You can open the API debugging console in the API interface and quickly copy the sample code for API calls.
    # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
    try:
        response: CreateMessageResponse = client.im.v1.message.create(request)
    except Exception:
        lark.logger.exception(
            "调用飞书发送接口异常, receive_id_type=%s, receive_id=%s, msg_type=%s",
            payload.receive_id_type,
            payload.receive_id,
            payload.msg_type,
        )
        raise

    if not response.success():
        error_detail = SendMessageErrorDetail(
            code=response.code,
            msg=response.msg,
            log_id=response.get_log_id(),
            receive_id_type=payload.receive_id_type,
            receive_id=payload.receive_id,
            msg_type=payload.msg_type,
        )
        lark.logger.error(
            f"send_message 业务失败: {error_detail.model_dump_json(ensure_ascii=False)}"
        )
        raise SendMessageError(error_detail)

    return response


# 发送欢迎卡片
# Construct a welcome card
# https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
def send_welcome_card(client, open_id):
    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": os.getenv("WELCOME_CARD_ID"),
                "template_variable": {"open_id": open_id},
            },
        }
    )
    return send_message(
        client,
        SendMessagePayload(
            receive_id_type="open_id",
            receive_id=open_id,
            msg_type="interactive",
            content=content,
        ),
    )


# 发送告警卡片
# Construct an alarm card
# https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
def send_alarm_card(client, payload: SendAlarmCardPayload) -> CreateMessageResponse:
    try:
        payload = SendAlarmCardPayload.model_validate(payload)
    except ValidationError:
        lark.logger.exception("send_alarm_card 参数校验失败")
        raise

    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": os.getenv("ALERT_CARD_ID"),
                "template_variable": {
                    "report_content": payload.report_content,
                    "status": "分析中",
                    "alarm_time": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S (UTC+8)"
                    ),
                },
            },
        }
    )
    return send_message(
        client,
        SendMessagePayload(
            receive_id_type=payload.receive_id_type,
            receive_id=payload.receive_id,
            msg_type="interactive",
            content=content,
        ),
    )


# 发送 SQL 通知卡片
# Construct a SQL notice card
# https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
def send_sql_notice_card(
    client, payload: SendSQLNoticeCardPayload
) -> CreateMessageResponse:
    try:
        payload = SendSQLNoticeCardPayload.model_validate(payload)
    except ValidationError:
        lark.logger.exception("send_sql_notice_card 参数校验失败")
        raise

    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": os.getenv("SQL_NOTICE_CARD_ID"),
                "template_variable": {
                    "report_content": payload.report_content,
                    "alarm_time": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S (UTC+8)"
                    ),
                },
            },
        }
    )
    return send_message(
        client,
        SendMessagePayload(
            receive_id_type=payload.receive_id_type,
            receive_id=payload.receive_id,
            msg_type="interactive",
            content=content,
        ),
    )


def update_alarm_card(client, payload: UpdateAlarmCardPayload) -> PatchMessageResponse:
    try:
        payload = UpdateAlarmCardPayload.model_validate(payload)
    except ValidationError:
        lark.logger.exception("update_alarm_card 参数校验失败")
        raise

    status_text = {
        "pending": "分析中",
        "success": "分析完成",
        "failed": "分析失败",
    }

    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": os.getenv("ALERT_CARD_ID"),
                "template_variable": {
                    "report_content": payload.report_content,
                    "status": status_text[payload.status],
                    "alarm_time": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S (UTC+8)"
                    ),
                },
            },
        }
    )

    request: PatchMessageRequest = (
        PatchMessageRequest.builder()
        .message_id(payload.message_id)
        .request_body(PatchMessageRequestBody.builder().content(content).build())
        .build()
    )

    response: PatchMessageResponse = client.im.v1.message.patch(request)
    if not response.success():
        raise Exception(
            f"client.im.v1.message.patch failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
        )

    return response


def _build_notify_content(client: lark.Client, metadata: dict) -> str | None:
    git_email = metadata.get("email")
    git_name = metadata.get("name")
    open_id = resolve_open_id(client, git_name, git_email)
    if open_id:
        feishu_at_tag = f'<at user_id="{open_id}"></at>'
    elif git_name:
        feishu_at_tag = f"@{git_name}"
    else:
        return None

    return json.dumps(
        {
            "text": (
                f"{feishu_at_tag} 同学，你提交的代码引发了最新的 Jenkins 构建失败，请尽快修复"
            )
        }
    )


def card_update_callback(client: lark.Client, card_message_id: str, content: str):
    return update_alarm_card(
        client,
        UpdateAlarmCardPayload(message_id=card_message_id, report_content=content),
    )


def handle_agent_result(
    client: lark.Client,
    card_message_id: str,
    receive_id_type: str,
    receive_id: str,
    task: asyncio.Task,
) -> None:
    notify_contents: list[str] = []
    try:
        agent_output = task.result()
        metadata_matches = re.findall(r"\$\$METADATA:(.*?)\$\$", agent_output)

        if metadata_matches:
            for metadata_str in metadata_matches:
                try:
                    metadata = json.loads(metadata_str)
                except json.JSONDecodeError as e:
                    lark.logger.warning(
                        "解析 METADATA 失败: %s, error: %s", metadata_str, e
                    )
                    continue

                notify_content = _build_notify_content(client, metadata)
                if notify_content:
                    notify_contents.append(notify_content)

            report_content = re.sub(r"\$\$METADATA:.*?\$\$", "", agent_output).strip()
        else:
            lark.logger.warning("agent_output 中没有找到元数据标签")
            report_content = agent_output

        status = "success"
    except Exception as e:
        lark.logger.exception("agent执行失败")
        notify_contents = []
        report_content = f"分析失败: {e}"
        status = "failed"

    update_alarm_card_payload = UpdateAlarmCardPayload(
        message_id=card_message_id,
        report_content=report_content,
        status=status,
    )
    update_alarm_card(client, update_alarm_card_payload)

    for notify_content in notify_contents:
        send_message(
            client,
            SendMessagePayload(
                receive_id_type=receive_id_type,
                receive_id=receive_id,
                msg_type="text",
                content=notify_content,
            ),
        )
