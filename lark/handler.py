import json

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetImageRequest,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)


class P2ImMessageReceiveV1Handler:
    def __init__(self, client: lark.Client) -> None:
        self.client = client

    def handle(self, data: P2ImMessageReceiveV1) -> None:
        if data.event.message.message_type == "text":
            try:
                text_content = json.loads(data.event.message.content)["text"]
                self.reply_message(
                    data.event.message.chat_type,
                    data.event.message.chat_id,
                    data.event.message.message_id,
                    json.dumps(
                        {
                            "text": f"收到消息 {text_content}，正在分析中...",
                        }
                    ),
                )

            except (json.JSONDecodeError, KeyError, TypeError):
                self.reply_message(
                    data.event.message.chat_type,
                    data.event.message.chat_id,
                    data.event.message.message_id,
                    json.dumps({"text": "文本消息解析失败"}),
                )
        elif data.event.message.message_type == "image":
            try:
                image_key = json.loads(data.event.message.content)["image_key"]
                self.download_image(image_key=image_key)

            except (json.JSONDecodeError, KeyError, TypeError):
                self.reply_message(
                    data.event.message.chat_type,
                    data.event.message.chat_id,
                    data.event.message.message_id,
                    json.dumps({"text": "图片消息解析消息失败\nparse image message failed, image key not found"}),
                )
        else:
            self.reply_message(
                data.event.message.chat_type,
                data.event.message.chat_id,
                data.event.message.message_id,
                json.dumps({"text": "解析消息失败，请发送文本或图片消息\nparse message failed, please send text or image message"}),
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
