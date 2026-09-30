import threading

import lark_oapi
from dotenv import load_dotenv
from lark_oapi.core.enum import LogLevel

from app.config import get_config
from app.lark.client import LarkClient, get_lark_api_client
from app.lark.handlers import (
    P2ImChatAccessEventBotP2PChatEnteredV1Handler,
    P2ImMessageReceiveV1Handler,
)
from app.log import setup_logging


def start_webhook_server() -> None:
    from app.webhook.app import run_webhook_server

    def _run_webhook_server():
        try:
            run_webhook_server()
        except Exception:
            lark_oapi.logger.exception("Jenkins webhook 服务启动失败")
            raise

    thread = threading.Thread(
        target=_run_webhook_server, daemon=True, name="jenkins-webhook-server"
    )
    thread.start()
    lark_oapi.logger.info("Jenkins webhook 服务在后台启动中...")


def main():
    load_dotenv()
    setup_logging()
    get_config()
    lark_client = LarkClient(log_level=LogLevel.DEBUG)
    api_client = get_lark_api_client()

    start_webhook_server()

    # Create API client for sending messages
    p2_im_message_handler = P2ImMessageReceiveV1Handler(client=api_client)
    p2_im_chat_bot_entered_handler = P2ImChatAccessEventBotP2PChatEnteredV1Handler(
        client=api_client
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
