import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
import re
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

from agent.intent import route_intent
from lark.feishu_mapping import resolve_open_id

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
    report_content: str

class UpdateAlarmCardPayload(BaseModel):
    message_id: str
    report_content: str
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
                report_content="收到故障分析任务，正在分析中...",
            )
            create_message_resp = send_alarm_card(self.client, send_alarm_card_payload)
            card_message_id = create_message_resp.data.message_id

            intent = route_intent(text_content)
            if intent == "build_error":
                update_alarm_card_payload = UpdateAlarmCardPayload(
                    message_id=card_message_id,
                    report_content="正在作为【构建故障分析专家】分析故障原因，请稍后...",
                    status=False,
                )
                update_alarm_card(self.client, update_alarm_card_payload)
                agent_task = asyncio.create_task(run_jenkins_agent(text_content))
            else:
                update_alarm_card_payload = UpdateAlarmCardPayload(
                    message_id=card_message_id,
                    report_content="正在作为【日常运维助手】回答问题，请稍后...",
                    status=False,
                )
                update_alarm_card(self.client, update_alarm_card_payload)
                thread_id = f"{chat_id}_{open_id}"
                agent_task = asyncio.create_task(run_qa_agent(text_content, thread_id))

            agent_task.add_done_callback(lambda t: handle_agent_result(self.client, card_message_id, receive_id_type, receive_id, t))
        elif data.event.message.message_type == "image":
            try:
                image_key = json.loads(data.event.message.content)["image_key"]
                self.download_image(image_key=image_key)

            except json.JSONDecodeError, KeyError, TypeError:
                send_message(
                    self.client,
                    SendMessagePayload(
                        receive_id_type=data.event.message.chat_type,
                        receive_id=data.event.message.chat_id,
                        msg_type="text",
                        content=json.dumps({"text": "图片消息解析消息失败\nparse image message failed, image key not found"}),
                    ),
                )
        else:
            send_message(
                self.client,
                SendMessagePayload(
                    receive_id_type=data.event.message.chat_type,
                    receive_id=data.event.message.chat_id,
                    msg_type="text",
                    content=json.dumps({"text": "解析消息失败，请发送文本或图片消息\nparse message failed, please send text or image message"}),
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


async def run_qa_agent(*args, **kwargs) -> str:
    from agent.qa_agent import run_qa_agent as _run_qa_agent
    return await _run_qa_agent(*args, **kwargs)

async def run_err_logs_agent(*args, **kwargs) -> str:
    from agent.err_logs_agent import run_err_logs_agent as _run_err_logs_agent
    return await _run_err_logs_agent(*args, **kwargs)


async def run_jenkins_agent(*args, **kwargs) -> str:
    from agent.jenkins_agent import run_jenkins_agent as _run_jenkins_agent
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
                    "report_content": payload.report_content,
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
                    "report_content": payload.report_content,
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

def _build_notify_content(metadata: dict) -> str | None:
    git_email = metadata.get("email")
    git_name = metadata.get("name")
    open_id = resolve_open_id(git_email)
    if open_id:
        feishu_at_tag = f'<at user_id="{open_id}"></at>'
    elif git_name:
        feishu_at_tag = f"@{git_name}"
    else:
        return None

    return json.dumps(
        {
            "text": (
                f"{feishu_at_tag} 同学，你提交的代码引发了最新的 Jenkins 构建失败，请尽快修复"
            )
        }
    )


def handle_agent_result(client: lark.Client, card_message_id: str, receive_id_type: str, receive_id: str, task: asyncio.Task) -> None:
    notify_contents: list[str] = []
    try:
        agent_output = task.result()
        metadata_matches = re.findall(r"\$\$METADATA:(.*?)\$\$", agent_output)

        if metadata_matches:
            for metadata_str in metadata_matches:
                try:
                    metadata = json.loads(metadata_str)
                except json.JSONDecodeError as e:
                    lark.logger.warning(
                        "解析 METADATA 失败: %s, error: %s", metadata_str, e
                    )
                    continue

                notify_content = _build_notify_content(metadata)
                if notify_content:
                    notify_contents.append(notify_content)

            report_content = re.sub(r"\$\$METADATA:.*?\$\$", "", agent_output).strip()
        else:
            lark.logger.warning("agent_output 中没有找到元数据标签")
            report_content = agent_output

        status = True
    except Exception as e:
        lark.logger.exception(f"agent执行失败, error: {e}")
        notify_contents = []
        report_content = f"分析失败: {e}"
        status = False

    update_alarm_card_payload = UpdateAlarmCardPayload(
        message_id=card_message_id,
        report_content=report_content,
        status=status,
    )
    update_alarm_card(client, update_alarm_card_payload)

    for notify_content in notify_contents:
        send_message(
            client,
            SendMessagePayload(
                receive_id_type=receive_id_type,
                receive_id=receive_id,
                msg_type="text",
                content=notify_content,
            ),
        )