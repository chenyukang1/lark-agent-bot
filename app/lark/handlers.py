import asyncio
import json

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    GetImageRequest,
    P2ImChatAccessEventBotP2pChatEnteredV1,
    P2ImMessageReceiveV1,
)

from app.agents import devopsAgentV2

from .messages import (
    SendAlarmCardPayload,
    SendMessagePayload,
    card_update_callback,
    handle_agent_result,
    send_alarm_card,
    send_message,
    send_welcome_card,
)


class P2ImMessageReceiveV1Handler:
    def __init__(self, client: lark.Client) -> None:
        self.client = client
        self.devops_agent = devopsAgentV2

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
                report_content="收到故障分析任务，正在分析中...",
            )
            create_message_resp = send_alarm_card(self.client, send_alarm_card_payload)
            card_message_id = create_message_resp.data.message_id

            def card_callback(content):
                return card_update_callback(self.client, card_message_id, content)

            agent_task = asyncio.create_task(
                self.devops_agent.handle_user_query(
                    chat_id, open_id, text_content, card_callback
                )
            )

            agent_task.add_done_callback(
                lambda t: handle_agent_result(
                    self.client, card_message_id, receive_id_type, receive_id, t
                )
            )
        elif data.event.message.message_type == "image":
            chat_type = data.event.message.chat_type
            chat_id = data.event.message.chat_id
            open_id = data.event.sender.sender_id.open_id

            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            receive_id = chat_id if chat_type == "group" else open_id

            try:
                image_key = json.loads(data.event.message.content)["image_key"]
                image_bytes = self.download_image(image_key=image_key)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                lark.logger.error(f"图片消息解析失败, error: {e}")
                send_message(
                    self.client,
                    SendMessagePayload(
                        receive_id_type=receive_id_type,
                        receive_id=receive_id,
                        msg_type="text",
                        content=json.dumps(
                            {
                                "text": "图片消息解析失败\nparse image message failed, image key not found"
                            }
                        ),
                    ),
                )
                return
            except Exception as e:
                lark.logger.exception(f"图片下载失败, error: {e}")
                send_message(
                    self.client,
                    SendMessagePayload(
                        receive_id_type=receive_id_type,
                        receive_id=receive_id,
                        msg_type="text",
                        content=json.dumps({"text": f"图片下载失败: {e}"}),
                    ),
                )
                return

            send_alarm_card_payload = SendAlarmCardPayload(
                receive_id_type=receive_id_type,
                receive_id=receive_id,
                report_content="收到图片故障分析任务，正在识别图片内容...",
            )
            create_message_resp = send_alarm_card(self.client, send_alarm_card_payload)
            card_message_id = create_message_resp.data.message_id

            def card_callback(content):
                return card_update_callback(self.client, card_message_id, content)

            agent_task = asyncio.create_task(
                self.devops_agent.handle_image_query(
                    chat_id, open_id, image_bytes, card_callback
                )
            )
            agent_task.add_done_callback(
                lambda t: handle_agent_result(
                    self.client, card_message_id, receive_id_type, receive_id, t
                )
            )
        else:
            send_message(
                self.client,
                SendMessagePayload(
                    receive_id_type=data.event.message.chat_type,
                    receive_id=data.event.message.chat_id,
                    msg_type="text",
                    content=json.dumps(
                        {
                            "text": "解析消息失败，请发送文本或图片消息\nparse message failed, please send text or image message"
                        }
                    ),
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
        self.welcomed = set[str]()

    def handle(self, data: P2ImChatAccessEventBotP2pChatEnteredV1):
        open_id = data.event.operator_id.open_id
        if open_id in self.welcomed:
            return

        lark.logger.info(f"欢迎用户 {open_id}")
        self.welcomed.add(open_id)
        return send_welcome_card(self.client, open_id)
