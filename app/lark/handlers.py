import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    GetImageRequest,
    P2ImChatAccessEventBotP2pChatEnteredV1,
    P2ImMessageReceiveV1,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

from app.agents import devopsAgentV2
from app.lark.model import (
    SendAlarmCardPayload,
    SendMessagePayload,
    UpdateAlarmCardPayload,
)
from app.lark.users import resolve_open_id
from app.tools import JENKINS_CLIENT_POOL

from . import get_lark_client

logger = logging.getLogger(__name__)


@dataclass
class AgentOutputResult:
    notify_content: str | None
    report_content: str
    status: Literal["success", "failed"]


class P2ImMessageReceiveV1Handler:
    def __init__(self) -> None:
        self._lark_client = get_lark_client()
        self.devops_agent = devopsAgentV2

    def handle(self, data: P2ImMessageReceiveV1) -> None:
        if data.event is None:
            return

        if data.event.message is None:
            return

        if data.event.message.message_type == "text":
            chat_type = data.event.message.chat_type
            chat_id = data.event.message.chat_id
            open_id = data.event.sender.sender_id.open_id  # type: ignore
            lark.logger.debug(f"open_id: {open_id}")

            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            receive_id = chat_id if chat_type == "group" else open_id

            try:
                text_content = json.loads(data.event.message.content)["text"]
            except Exception as e:
                lark.logger.error(f"文本消息解析失败, error: {e}")
                self._lark_client.send_message(
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
            create_message_resp = self._lark_client.send_alarm_card(
                send_alarm_card_payload
            )
            card_message_id = create_message_resp.data.message_id  # type: ignore

            agent_task = asyncio.create_task(
                self.devops_agent.handle_user_query(
                    chat_id,
                    open_id,
                    user_input=text_content,
                    card_callback=lambda t: self._lark_client.update_alarm_card(
                        UpdateAlarmCardPayload(
                            message_id=card_message_id, report_content=t
                        ),
                    ),
                )
            )

            agent_task.add_done_callback(
                lambda t: handle_agent_output(
                    card_message_id,
                    receive_id_type,
                    receive_id,
                    t.result(),
                )
            )
        elif data.event.message.message_type == "image":
            chat_type = data.event.message.chat_type
            chat_id = data.event.message.chat_id
            open_id = data.event.sender.sender_id.open_id  # type: ignore

            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            receive_id = chat_id if chat_type == "group" else open_id

            try:
                image_key = json.loads(data.event.message.content)["image_key"]
                image_bytes = self.download_image(image_key=image_key)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                lark.logger.error(f"图片消息解析失败, error: {e}")
                self._lark_client.send_message(
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
                lark.logger.exception("图片下载失败")
                self._lark_client.send_message(
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
            create_message_resp = self._lark_client.send_alarm_card(
                send_alarm_card_payload
            )
            card_message_id = create_message_resp.data.message_id  # type: ignore

            agent_task = asyncio.create_task(
                self.devops_agent.handle_image_query(
                    chat_id,
                    open_id,
                    image_bytes,
                    card_callback=lambda t: self._lark_client.update_alarm_card(
                        UpdateAlarmCardPayload(
                            message_id=card_message_id, report_content=t
                        ),
                    ),
                )
            )
            agent_task.add_done_callback(
                lambda t: handle_agent_output(
                    card_message_id,
                    receive_id_type,
                    receive_id,
                    t.result(),
                )
            )
        else:
            self._lark_client.send_message(
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
        response = get_lark_client().im.v1.image.get(request)

        if not response.success():
            raise Exception(
                f"client.im.v1.image.get failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}"
            )

        return response.data.content


class P2ImChatAccessEventBotP2PChatEnteredV1Handler:
    def __init__(self) -> None:
        self._lark_client = get_lark_client()
        self.welcomed = set[str]()

    def handle(self, data: P2ImChatAccessEventBotP2pChatEnteredV1):
        open_id = data.event.operator_id.open_id  # type: ignore
        if open_id in self.welcomed:
            return

        lark.logger.info(f"欢迎用户 {open_id}")
        self.welcomed.add(open_id)
        return self._lark_client.send_welcome_card(open_id)


class P2CardActionTriggerHandler:
    def __init__(self) -> None:
        self._lark_client = get_lark_client()

    def handle(self, data: P2CardActionTrigger):
        if not data.event:
            logger.warning("Data event None when card action trigger")
            return

        if not data.event.context:
            logger.warning("Data event context None when card action trigger")
            return

        self._lark_client.mark_alarm_card_resolved(
            message_id=data.event.context.open_message_id
        )

        if data.event.action and data.event.action.value:
            alias = data.event.action.value["alias"]
            jenkins_client = JENKINS_CLIENT_POOL.get_jenkins_client(alias)
            jenkins_client.trigger_jenkins_build(alias)


def handle_agent_output(
    card_message_id: str, receive_id_type: str, receive_id: str, agent_output: Any
) -> None:
    output_result = parse_agent_output(agent_output)
    lark_client = get_lark_client()

    update_alarm_card_payload = UpdateAlarmCardPayload(
        message_id=card_message_id,
        report_content=output_result.report_content,
        status=output_result.status,
    )
    lark_client.update_alarm_card(update_alarm_card_payload)

    if output_result.notify_content:
        lark_client.send_message(
            SendMessagePayload(
                receive_id_type=receive_id_type,
                receive_id=receive_id,
                msg_type="text",
                content=output_result.notify_content,
            ),
        )


def parse_agent_output(agent_output: str) -> AgentOutputResult:
    try:
        metadata_matches = re.findall(r"\$\$METADATA:(.*?)\$\$", agent_output)

        if metadata_matches:
            try:
                metadata = json.loads(metadata_matches[0])
            except json.JSONDecodeError as e:
                logger.error(
                    "解析 METADATA 失败: %s, error: %s", metadata_matches[0], e
                )
                raise ValueError("解析 METADATA 失败")

            notify_content = _build_notify_content(metadata)
            report_content = re.sub(r"\$\$METADATA:.*?\$\$", "", agent_output).strip()
        else:
            logger.debug("agent_output 中没有找到元数据标签")
            notify_content = None
            report_content = agent_output

        status = "success"
    except Exception as e:
        logger.exception("agent执行失败")
        report_content = f"分析失败: {e}"
        status = "failed"
    return AgentOutputResult(notify_content, report_content, status)


def _build_notify_content(metadata: dict):
    git_email = metadata.get("email")
    git_name = metadata.get("name")
    open_id = resolve_open_id(git_name, git_email)
    if open_id:
        feishu_at_tag = f'<at user_id="{open_id}"></at>'
    elif git_name:
        feishu_at_tag = f"@{git_name}"
    else:
        raise ValueError("open_id not found")

    return json.dumps(
        {
            "text": (
                f"{feishu_at_tag} 同学，你提交的代码引发了最新的 Jenkins 构建失败，请尽快修复"
            )
        }
    )
