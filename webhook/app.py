import os
from contextlib import asynccontextmanager
from typing import Optional

from lark import (
    lark_api_client,
    SendAlarmCardPayload,
    UpdateAlarmCardPayload,
    run_jenkins_agent,
    send_alarm_card,
    update_alarm_card,
)

import lark_oapi

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

class JenkinsBuildEvent(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: str | None = None


load_dotenv()

NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8000"))


class WebhookPayload(BaseModel):
    job_name: str
    build_number: int
    build_url: str
    phase: Optional[str] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not NOTIFY_CHAT_ID:
        lark_oapi.logger.warning("NOTIFY_CHAT_ID 未配置，Jenkins webhook 将无法发送飞书通知")
    yield


app = FastAPI(title="Lark Agent Bot Webhook", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/jenkins/test")
async def jenkins_webhook(
    background_tasks: BackgroundTasks,
    payload: WebhookPayload,
) -> JSONResponse:
    lark_oapi.logger.info(
        "收到 Jenkins webhook: job=%s build=#%s phase=%s",
        payload.job_name,
        payload.build_number,
        payload.phase,
    )

    event = JenkinsBuildEvent(
        job_name=payload.job_name,
        build_number=payload.build_number,
        build_url=payload.build_url,
        phase=payload.phase,
    )
    background_tasks.add_task(_notify_jenkins_failure, event)
    return JSONResponse(
        {
            "accepted": True,
            "analyzing": True,
            "job_name": event.job_name,
            "build_number": event.build_number,
        }
    )


def run_webhook_server() -> None:
    import uvicorn

    uvicorn.run(
        "webhook.app:app",
        host=os.getenv("WEBHOOK_HOST", "0.0.0.0"),
        port=WEBHOOK_PORT,
        log_level=os.getenv("WEBHOOK_LOG_LEVEL", "info"),
    )


def _resolve_receive_id_type(receive_id: str) -> str:
    if receive_id.startswith("ou_"):
        return "open_id"
    return "chat_id"


async def _notify_jenkins_failure(event: JenkinsBuildEvent) -> None:
    if not NOTIFY_CHAT_ID:
        lark_oapi.logger.error("NOTIFY_CHAT_ID 未配置，无法发送飞书通知")
        return

    receive_id_type = _resolve_receive_id_type(NOTIFY_CHAT_ID)
    intro = (
        f"收到 Jenkins 构建失败通知\n"
        f"- Job: {event.job_name}\n"
        f"- 构建号: #{event.build_number}\n"
        f"- 状态: 构建失败\n"
        f"正在分析中..."
    )

    create_message_resp = send_alarm_card(
        lark_api_client.client,
        SendAlarmCardPayload(
            receive_id_type=receive_id_type,
            receive_id=NOTIFY_CHAT_ID,
            content=intro,
        ),
    )
    card_message_id = create_message_resp.data.message_id

    try:
        result = await run_jenkins_agent(build_agent_instruction(event))
        status = True
    except Exception as e:
        lark_oapi.logger.exception(f"jenkins_agent 执行失败: {e}")
        result = f"分析失败: {e}"
        status = False

    update_alarm_card(
        lark_api_client.client,
        UpdateAlarmCardPayload(
            message_id=card_message_id,
            content=result,
            status=status,
        ),
    )


def build_agent_instruction(event: JenkinsBuildEvent) -> str:
    parts = [
        f"Jenkins Job【{event.job_name}】构建失败，",
        "请分析最可能导致失败的提交人（committer）。",
    ]
    return "".join(parts)