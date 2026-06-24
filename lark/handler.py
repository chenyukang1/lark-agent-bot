import json
import os
from datetime import datetime, timedelta, timezone

import lark_oapi as lark
from lark_oapi.api.cardkit.v1 import (
    ContentCardElementRequest,
    ContentCardElementRequestBody,
    ContentCardElementResponse,
)
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetImageRequest,
    P2ImChatAccessEventBotP2pChatEnteredV1,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

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
                # self.reply_message(
                #     chat_type,
                #     receive_id,
                #     message_id,
                #     json.dumps(
                #         {
                #             "text": "收到消息，正在分析中...",
                #         }
                #     ),
                # )
                send_alarm_card(self.client, receive_id_type, receive_id)

                # 构造请求对象
                request: ContentCardElementRequest = (
                    ContentCardElementRequest.builder()
                    .card_id(ALERT_CARD_ID)
                    .element_id("A111111")
                    .request_body(
                        ContentCardElementRequestBody.builder()
                        .uuid("a0d69e20-1dd1-458b-k525-dfeca4015204")
                        .content("这是更新后的文本内容。将以打字机式的效果输出")
                        .sequence(1)
                        .build()
                    )
                    .build()
                )

                # 发起请求
                response: ContentCardElementResponse = (
                    self.client.cardkit.v1.card_element.content(request)
                )

                # 处理失败返回
                if not response.success():
                    lark.logger.error(
                        f"client.cardkit.v1.card_element.content failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}"
                    )
                    return

            except json.JSONDecodeError, KeyError, TypeError:
                send_message(
                    self.client,
                    receive_id_type,
                    receive_id,
                    message_id,
                    json.dumps({"text": "文本消息解析失败"}),
                )

            # agent_task = asyncio.create_task(
            #     agent.run_claude_code_agent(
            #         "/Users/chenyk/Downloads/logs",
            #         text_content,
            #         data.event.message.message_id,
            #     )
            # )

            # agent_task.add_done_callback(
            #     lambda t: self.reply_message(
            #         chat_type, receive_id, message_id, json.dumps({"text": t.result()})
            #     )
            # )
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

    def reply_message(
        self, chat_type: str, receive_id: str, message_id: str, content: str
    ) -> None:
        # 单聊
        if chat_type == "p2p":
            p2p_request: CreateMessageRequest = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("text")
                    .content(content)
                    .build()
                )
                .build()
            )
            # 使用OpenAPI发送消息
            # Use send OpenAPI to send messages
            # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
            response = self.client.im.v1.message.create(p2p_request)

            if not response.success():
                raise Exception(
                    f"client.im.v1.message.create failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
                )

        # 群组
        else:
            group_request: ReplyMessageRequest = (
                ReplyMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(content)
                    .msg_type("text")
                    .build()
                )
                .build()
            )
            response = self.client.im.v1.message.reply(group_request)

            if not response.success():
                raise Exception(
                    f"client.im.v1.message.reply failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
                )


class P2ImChatAccessEventBotP2PChatEnteredV1Handler:
    def __init__(self, client: lark.Client) -> None:
        self.client = client

    def handle(self, data: P2ImChatAccessEventBotP2pChatEnteredV1):
        open_id = data.event.operator_id.open_id

        return send_welcome_card(self.client, open_id)


# 发送消息
# # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
def send_message(client, receive_id_type, receive_id, msg_type, content):
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
    response = client.im.v1.message.create(request)
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
def send_alarm_card(client, receive_id_type, receive_id):
    content = json.dumps(
        {
            "type": "template",
            "data": {
                "template_id": ALERT_CARD_ID,
                "template_variable": {
                    "alarm_time": datetime.now(timezone(timedelta(hours=8))).strftime(
                        "%Y-%m-%d %H:%M:%S (UTC+8)"
                    ),
                },
            },
        }
    )
    return send_message(client, receive_id_type, receive_id, "interactive", content)
