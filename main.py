import threading

from dotenv import load_dotenv

load_dotenv()

from app_logging import setup_logging

setup_logging()

import lark_oapi

from lark import (
    lark_api_client,
    lark_client,
    P2ImChatAccessEventBotP2PChatEnteredV1Handler,
    P2ImMessageReceiveV1Handler,
)


def start_webhook_server() -> None:
    from webhook.app import run_webhook_server

    def _run_webhook_server():
        try:
            run_webhook_server()
        except Exception as e:
            lark_oapi.logger.exception("Jenkins webhook 服务启动失败")
            raise

    thread = threading.Thread(target=_run_webhook_server, daemon=True, name="jenkins-webhook-server")
    thread.start()
    lark_oapi.logger.info("Jenkins webhook 服务在后台启动中...")


def main():
    start_webhook_server()

    # Create API client for sending messages
    p2_im_message_handler = P2ImMessageReceiveV1Handler(client=lark_api_client.client)
    p2_im_chat_bot_entered_handler = P2ImChatAccessEventBotP2PChatEnteredV1Handler(
        client=lark_api_client.client
    )

    # 注册事件回调
    # Register event handler.
    event_handler = (
        lark_oapi.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(
            lambda data: p2_im_message_handler.handle(data)
        )
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(
            lambda data: p2_im_chat_bot_entered_handler.handle(data)
        )
        .build()
    )

    lark_client.register_event_handler(event_handler)
    lark_client.start()


if __name__ == "__main__":
    main()
