import json

import lark_oapi as lark
from lark_oapi.api.im.v1 import *

from lark import LarkClient


# 注册接收消息事件，处理接收到的消息。
# Register event handler to handle received messages.
# https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/events/receive
def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1, api_client=None) -> None:
    res_content = ""
    if data.event.message.message_type == "text":
        try:
            res_content = json.loads(data.event.message.content)["text"]
        except (json.JSONDecodeError, KeyError, TypeError):
            res_content = "解析消息失败，请发送文本消息\nparse message failed, please send text message"
    else:
        res_content = "解析消息失败，请发送文本消息\nparse message failed, please send text message"

    content = json.dumps(
        {
            "text": "收到你发送的消息："
            + res_content
            + "\nReceived message:"
            + res_content
        }
    )

    if data.event.message.chat_type == "p2p":
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(data.event.message.chat_id)
                .msg_type("text")
                .content(content)
                .build()
            )
            .build()
        )
        # 使用OpenAPI发送消息
        # Use send OpenAPI to send messages
        # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
        response = api_client.im.v1.message.create(request)

        if not response.success():
            raise Exception(
                f"client.im.v1.message.create failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
            )
    else:
        request: ReplyMessageRequest = (
            ReplyMessageRequest.builder()
            .message_id(data.event.message.message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(content)
                .msg_type("text")
                .build()
            )
            .build()
        )
        # 使用OpenAPI回复消息
        # Reply to messages using send OpenAPI
        # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/reply
        response: ReplyMessageResponse = api_client.im.v1.message.reply(request)
        if not response.success():
            raise Exception(
                f"client.im.v1.message.reply failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
            )


def main():
    #  启动长连接，并注册事件处理器。
    #  Start long connection and register event handler.
    # 创建API客户端用于发送消息
    # Create API client for sending messages
    api_client = lark.Client.builder() \
        .app_id(lark.APP_ID) \
        .app_secret(lark.APP_SECRET) \
        .build()

    # 注册事件回调
    # Register event handler.
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(lambda data: do_p2_im_message_receive_v1(data, api_client))
        .build()
    )

    lark_client = LarkClient()
    lark_client.register_event_handler(event_handler)
    lark_client.start()


if __name__ == "__main__":
    main()
