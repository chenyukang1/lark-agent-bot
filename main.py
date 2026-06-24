from dotenv import load_dotenv

load_dotenv()

import lark_oapi
from lark_oapi.core.enum import LogLevel

from lark import LarkClient, P2ImMessageReceiveV1Handler


def main():
    # Create API client for sending messages
    api_client = (
        lark_oapi.Client.builder()
        .app_id(lark_oapi.APP_ID)
        .app_secret(lark_oapi.APP_SECRET)
        .build()
    )

    p2_im_message_handler = P2ImMessageReceiveV1Handler(client=api_client)

    # 注册事件回调
    # Register event handler.
    event_handler = (
        lark_oapi.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(
            lambda data: p2_im_message_handler.handle(data)
        )
        .build()
    )

    lark_client = LarkClient(log_level=LogLevel.DEBUG)
    lark_client.register_event_handler(event_handler)
    lark_client.start()


if __name__ == "__main__":
    main()
