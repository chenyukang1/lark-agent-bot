from typing import Literal

from pydantic import BaseModel


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
    status: Literal["pending", "success", "failed"] = "pending"


class LarkClientErrorDetail(BaseModel):
    code: int
    msg: str
    log_id: str
    receive_id_type: str | None = None
    receive_id: str | None = None
    msg_type: str | None = None


class LarkClientError(Exception):
    def __init__(self, detail: LarkClientErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.model_dump_json(ensure_ascii=False))
