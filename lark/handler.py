import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

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

import agent

ALERT_CARD_ID = os.getenv("ALERT_CARD_ID")
WELCOME_CARD_ID = os.getenv("WELCOME_CARD_ID")


class P2ImMessageReceiveV1Handler:
    def __init__(self, client: lark.Client) -> None:
        self.client = client

    def handle(self, data: P2ImMessageReceiveV1) -> None:
        if data.event.message.message_type == "text":
            chat_type = data.event.message.chat_type
            message_id = data.event.message.message_id
            chat_id = data.event.message.chat_id
            open_id = data.event.sender.sender_id.open_id
            lark.logger.debug(f"open_id: {open_id}")

            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            receive_id = chat_id if chat_type == "group" else open_id

            try:
                text_content = json.loads(data.event.message.content)["text"]
                create_message_resp = send_alarm_card(
                    self.client, "收到消息，正在分析中...", receive_id_type, receive_id
                )
                card_message_id = create_message_resp.data.message_id

            except json.JSONDecodeError, KeyError, TypeError:
                send_message(
                    self.client,
                    receive_id_type,
                    receive_id,
                    message_id,
                    json.dumps({"text": "文本消息解析失败"}),
                )

            agent_task = asyncio.create_task(agent.run_agent(text_content))

            agent_task.add_done_callback(
                lambda t: update_alarm_card(self.client, t.result(), card_message_id)
            )
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


# 发送消息
# # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
def send_message(
    client, receive_id_type, receive_id, msg_type, content
) -> CreateMessageResponse:
    request = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type(msg_type)
            .content(content)
            .build()
        )
        .build()
    )

    # 使用发送OpenAPI发送通知卡片，你可以在API接口中打开 API 调试台，快速复制调用示例代码
    # Use send OpenAPI to send notice card. You can open the API debugging console in the API interface and quickly copy the sample code for API calls.
    # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
    response: CreateMessageResponse = client.im.v1.message.create(request)
    if not response.success():
        raise Exception(
            f"client.im.v1.message.create failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
        )
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
    return send_message(client, "open_id", open_id, "interactive", content)


# 发送告警卡片
# Construct an alarm card
# https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
def send_alarm_card(client, msg, receive_id_type, receive_id) -> CreateMessageResponse:
    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": ALERT_CARD_ID,
                "template_variable": {
                    "content": msg,
                    "status": "分析中",
                    "alarm_time": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S (UTC+8)"
                    ),
                },
            },
        }
    )
    return send_message(client, receive_id_type, receive_id, "interactive", content)


def update_alarm_card(client, update_content, message_id) -> PatchMessageResponse:
    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": ALERT_CARD_ID,
                "template_variable": {
                    "content": update_content,
                    "status": "分析完成",
                    "alarm_time": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S (UTC+8)"
                    ),
                },
            },
        }
    )

    request: PatchMessageRequest = (
        PatchMessageRequest.builder()
        .message_id(message_id)
        .request_body(PatchMessageRequestBody.builder().content(content).build())
        .build()
    )

    response: PatchMessageResponse = client.im.v1.message.patch(request)
    if not response.success():
        raise Exception(
            f"client.im.v1.message.patch failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
        )

    return response
