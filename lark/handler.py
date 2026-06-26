import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    GetImageRequest,
    P2ImChatAccessEventBotP2pChatEnteredV1,
    P2ImMessageReceiveV1,
    PatchMessageRequest,
    PatchMessageRequestBody,
    PatchMessageResponse,
)
from pydantic import BaseModel, ValidationError

import agent

ALERT_CARD_ID = os.getenv("ALERT_CARD_ID")
WELCOME_CARD_ID = os.getenv("WELCOME_CARD_ID")


class SendMessagePayload(BaseModel):
    receive_id_type: Literal["chat_id", "open_id"]
    receive_id: str
    msg_type: str
    content: str

class SendAlarmCardPayload(BaseModel):
    receive_id_type: Literal["chat_id", "open_id"]
    receive_id: str
    content: str

class UpdateAlarmCardPayload(BaseModel):
    message_id: str
    content: str
    status: bool

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


class P2ImMessageReceiveV1Handler:
    def __init__(self, client: lark.Client) -> None:
        self.client = client

    def handle(self, data: P2ImMessageReceiveV1) -> None:
        if data.event.message.message_type == "text":
            chat_type = data.event.message.chat_type
            chat_id = data.event.message.chat_id
            open_id = data.event.sender.sender_id.open_id
            lark.logger.debug(f"open_id: {open_id}")

            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            receive_id = chat_id if chat_type == "group" else open_id

            try:
                text_content = json.loads(data.event.message.content)["text"]
            except Exception as e:
                lark.logger.error(f"文本消息解析失败, error: {e}")
                send_message(
                    self.client,
                    SendMessagePayload(
                        receive_id_type=receive_id_type,
                        receive_id=receive_id,
                        msg_type="text",
                        content=json.dumps({"text": "文本消息解析失败"}),
                    ),
                )
                return

            send_alarm_card_payload = SendAlarmCardPayload(
                receive_id_type=receive_id_type,
                receive_id=receive_id,
                content="收到消息，正在分析中...",
            )
            create_message_resp = send_alarm_card(self.client, send_alarm_card_payload)
            card_message_id = create_message_resp.data.message_id

            if "构建" in text_content:
                agent_task = asyncio.create_task(run_jenkins_agent(text_content))
            else:
                agent_task = asyncio.create_task(agent.run_agent(text_content))

            def _handle_agent_result(task: asyncio.Task) -> None:
                try:
                    result = task.result()
                    status = True
                except Exception as e:
                    lark.logger.exception(f"agent执行失败, error: {e}")
                    result = f"分析失败: {e}"
                    status = False

                update_alarm_card_payload = UpdateAlarmCardPayload(
                    message_id=card_message_id,
                    content=result,
                    status=status,
                )
                update_alarm_card(self.client, update_alarm_card_payload)

            agent_task.add_done_callback(_handle_agent_result)
        elif data.event.message.message_type == "image":
            try:
                image_key = json.loads(data.event.message.content)["image_key"]
                self.download_image(image_key=image_key)

            except json.JSONDecodeError, KeyError, TypeError:
                self.reply_message(
                    data.event.message.chat_type,
                    data.event.message.chat_id,
                    data.event.message.message_id,
                    json.dumps(
                        {
                            "text": "图片消息解析消息失败\nparse image message failed, image key not found"
                        }
                    ),
                )
        else:
            self.reply_message(
                data.event.message.chat_type,
                data.event.message.chat_id,
                data.event.message.message_id,
                json.dumps(
                    {
                        "text": "解析消息失败，请发送文本或图片消息\nparse message failed, please send text or image message"
                    }
                ),
            )

    def download_image(self, image_key: str) -> bytes:
        request = GetImageRequest.builder().image_key(image_key).build()
        response = self.client.im.v1.image.get(request)

        if not response.success():
            raise Exception(
                f"client.im.v1.image.get failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
            )

        return response.data.content


class P2ImChatAccessEventBotP2PChatEnteredV1Handler:
    def __init__(self, client: lark.Client) -> None:
        self.client = client

    def handle(self, data: P2ImChatAccessEventBotP2pChatEnteredV1):
        open_id = data.event.operator_id.open_id

        return send_welcome_card(self.client, open_id)


async def run_jenkins_agent(*args, **kwargs) -> str:
    from agent import run_jenkins_agent as _run_jenkins_agent
    return await _run_jenkins_agent(*args, **kwargs)

# 发送消息
# # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
def send_message(
    client, payload: SendMessagePayload
) -> CreateMessageResponse:
    try:
        payload = SendMessagePayload.model_validate(payload)
    except ValidationError as e:
        lark.logger.exception(f"send_message 参数校验失败, error: {e}")
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
    except Exception as e:
        lark.logger.exception(
            f"调用飞书发送接口异常, receive_id_type={payload.receive_id_type}, "
            f"receive_id={payload.receive_id}, msg_type={payload.msg_type}, error: {e}"
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
                "template_id": WELCOME_CARD_ID,
                "template_variable": {"open_id": open_id},
            },
        }
    )
    return send_message(
        client,
        SendMessagePayload(
            receive_id_type="open_id", receive_id=open_id, msg_type="interactive", content=content
        ),
    )


# 发送告警卡片
# Construct an alarm card
# https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
def send_alarm_card(client, payload: SendAlarmCardPayload) -> CreateMessageResponse:
    try:
        payload = SendAlarmCardPayload.model_validate(payload)
    except ValidationError as e:
        lark.logger.exception(f"send_alarm_card 参数校验失败, error: {e}")
        raise

    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": ALERT_CARD_ID,
                "template_variable": {
                    "content": payload.content,
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


def update_alarm_card(client, payload: UpdateAlarmCardPayload) -> PatchMessageResponse:
    try:
        payload = UpdateAlarmCardPayload.model_validate(payload)
    except ValidationError as e:
        lark.logger.exception(f"update_alarm_card 参数校验失败, error: {e}")
        raise

    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": ALERT_CARD_ID,
                "template_variable": {
                    "content": payload.content,
                    "status": "分析完成" if payload.status else "分析失败",
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
