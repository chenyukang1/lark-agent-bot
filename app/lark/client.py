import json
import logging
import os
from datetime import datetime, timedelta, timezone

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    PatchMessageRequest,
    PatchMessageRequestBody,
    PatchMessageResponse,
)
from lark_oapi.core.enum import LogLevel
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from pydantic import ValidationError

from app.lark.model import (
    LarkClientError,
    LarkClientErrorDetail,
    SendAlarmCardPayload,
    SendDDLNoticeCardPayload,
    SendMessagePayload,
    UpdateAlarmCardPayload,
)

logger = logging.getLogger(__name__)


# 创建 LarkClient 对象，用于请求OpenAPI, 并创建 LarkWSClient 对象，用于使用长连接接收事件。
# Create LarkClient object for requesting OpenAPI, and create LarkWSClient object for receiving events using long connection.
class LarkClient:
    def __init__(self, log_level: LogLevel = LogLevel.INFO):
        self.app_id = os.environ["APP_ID"]
        self.app_secret = os.environ["APP_SECRET"]
        self.welcome_card_id = os.environ["WELCOME_CARD_ID"]
        self.alert_card_id = os.environ["ALERT_CARD_ID"]
        self.ddl_notice_card_id = os.environ["DDL_NOTICE_CARD_ID"]
        self.log_level = log_level

        self._client = (
            lark.Client.builder()
            .app_id(os.environ["APP_ID"])
            .app_secret(os.environ["APP_SECRET"])
            .build()
        )
        self.event_handler = None

    def register_event_handler(self, event_handler: EventDispatcherHandler):
        self.event_handler = event_handler

    def start(self):
        if not self.event_handler:
            raise ValueError("Event handler is not registered")

        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=self.event_handler,
            log_level=self.log_level,
        )

        self._ws_client.start()

    # Send message
    # # https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create
    def send_message(self, payload: SendMessagePayload) -> CreateMessageResponse:
        try:
            payload = SendMessagePayload.model_validate(payload)
        except ValidationError:
            logger.exception("send_message 参数校验失败")
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
            response: CreateMessageResponse = self._client.im.v1.message.create(request)  # type: ignore
        except Exception:
            logger.exception(
                "调用飞书发送接口异常, receive_id_type=%s, receive_id=%s, msg_type=%s",
                payload.receive_id_type,
                payload.receive_id,
                payload.msg_type,
            )
            raise

        if not response.success():
            error_detail = LarkClientErrorDetail(
                code=response.code,
                msg=response.msg,
                log_id=response.get_log_id(),
                receive_id_type=payload.receive_id_type,
                receive_id=payload.receive_id,
                msg_type=payload.msg_type,
            )
            logger.error(
                f"send_message 业务失败: {error_detail.model_dump_json(ensure_ascii=False)}"
            )
            raise LarkClientError(error_detail)

        return response

    # Send a welcome card
    # https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
    def send_welcome_card(self, open_id):
        content = json.dumps(
            {
                "type": "template",
                "data": {
                    "template_id": self.welcome_card_id,
                    "template_variable": {"open_id": open_id},
                },
            }
        )
        return self.send_message(
            SendMessagePayload(
                receive_id_type="open_id",
                receive_id=open_id,
                msg_type="interactive",
                content=content,
            ),
        )

    # Send an alarm card
    # https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/send-feishu-card#718fe26b
    def send_alarm_card(self, payload: SendAlarmCardPayload) -> CreateMessageResponse:
        try:
            payload = SendAlarmCardPayload.model_validate(payload)
        except ValidationError:
            logger.exception("send_alarm_card 参数校验失败")
            raise

        content = json.dumps(
            {
                "type": "template",
                "data": {
                    "template_id": self.alert_card_id,
                    "template_variable": {
                        "report_content": payload.report_content,
                        "status": "分析中",
                        "alarm_time": datetime.now(
                            timezone(timedelta(hours=8))
                        ).strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
                        "header_color": "red",
                        "event_status": "待处理",
                    },
                },
            }
        )
        return self.send_message(
            SendMessagePayload(
                receive_id_type=payload.receive_id_type,
                receive_id=payload.receive_id,
                msg_type="interactive",
                content=content,
            ),
        )

    def send_ddl_notice_card(
        self,
        payload: SendDDLNoticeCardPayload,
    ) -> CreateMessageResponse:
        try:
            payload = SendDDLNoticeCardPayload.model_validate(payload)
        except ValidationError:
            logger.exception("send_sql_notice_card 参数校验失败")
            raise

        content = json.dumps(
            {
                "type": "template",
                "data": {
                    "template_id": self.ddl_notice_card_id,
                    "template_variable": {
                        "report_content": payload.report_content,
                        "alarm_time": datetime.now(
                            timezone(timedelta(hours=8))
                        ).strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
                    },
                },
            }
        )
        return self.send_message(
            SendMessagePayload(
                receive_id_type=payload.receive_id_type,
                receive_id=payload.receive_id,
                msg_type="interactive",
                content=content,
            ),
        )

    def update_alarm_card(
        self, payload: UpdateAlarmCardPayload
    ) -> PatchMessageResponse:
        try:
            payload = UpdateAlarmCardPayload.model_validate(payload)
        except ValidationError:
            logger.exception("update_alarm_card 参数校验失败")
            raise

        status_text = {
            "pending": "分析中",
            "success": "分析完成",
            "failed": "分析失败",
        }

        content = json.dumps(
            {
                "type": "template",
                "data": {
                    "template_id": self.alert_card_id,
                    "template_variable": {
                        "report_content": payload.report_content,
                        "status": status_text[payload.status],
                        "alarm_time": datetime.now(
                            timezone(timedelta(hours=8))
                        ).strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
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

        response: PatchMessageResponse = self._client.im.v1.message.patch(request)  # type: ignore
        if not response.success():
            error_detail = LarkClientErrorDetail(
                code=response.code,
                msg=response.msg,
                log_id=response.get_log_id(),
            )
            raise LarkClientError(error_detail)

        return response

    def mark_alarm_card_resolved(self, message_id: str):
        content = json.dumps(
            {
                "type": "template",
                "data": {
                    "template_id": self.alert_card_id,
                    "template_variable": {
                        "header_color": "green",
                        "event_status": "已完成",
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

        response: PatchMessageResponse = self._client.im.v1.message.patch(request)  # type: ignore
        if not response.success():
            error_detail = LarkClientErrorDetail(
                code=response.code,
                msg=response.msg,
                log_id=response.get_log_id(),
            )
            raise LarkClientError(error_detail)

        return response
