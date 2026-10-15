import logging
import os
from contextlib import asynccontextmanager

import lark_oapi
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse

from app.agents.ddl_workflow import notify_staging_ddl
from app.config import get_config
from app.lark.callback import jenkins_failure_callback
from app.model import JenkinsBuildEvent, WebhookPayload


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_dotenv()
    get_config()
    if not os.getenv("NOTIFY_CHAT_ID"):
        lark_oapi.logger.warning(
            "NOTIFY_CHAT_ID 未配置，Jenkins webhook 将无法发送飞书通知"
        )
    yield


app = FastAPI(title="Lark Agent Bot Webhook", lifespan=lifespan)
logger = logging.getLogger(__name__)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/jenkins/build_fail")
async def jenkins_build_fail_webhook(
    background_tasks: BackgroundTasks,
    payload: WebhookPayload,
) -> JSONResponse:
    logger.info(
        "收到 Jenkins webhook: job=%s build=#%s phase=%s",
        payload.job_name,
        payload.build_number,
        payload.phase,
    )

    event = JenkinsBuildEvent(**payload.model_dump())
    background_tasks.add_task(jenkins_failure_callback, event)
    return JSONResponse(
        {
            "accepted": True,
            "analyzing": True,
            "job_name": event.job_name,
            "build_number": event.build_number,
        }
    )


@app.post("/webhook/jenkins/build_start")
async def jenkins_build_start_webhook(
    background_tasks: BackgroundTasks,
    payload: WebhookPayload,
) -> JSONResponse:
    logger.info(
        "收到 Jenkins webhook: job=%s build=#%s phase=%s",
        payload.job_name,
        payload.build_number,
        payload.phase,
    )

    event = JenkinsBuildEvent(**payload.model_dump())
    background_tasks.add_task(notify_staging_ddl, event)
    return JSONResponse(
        {
            "accepted": True,
            "analyzing": True,
            "job_name": payload.job_name,
            "build_number": payload.build_number,
        },
        status_code=202,
    )


def run_webhook_server() -> None:
    import uvicorn

    uvicorn.run(
        "app.webhook.app:app",
        host=os.getenv("WEBHOOK_HOST", "0.0.0.0"),
        port=int(os.getenv("WEBHOOK_PORT", "8000")),
        log_level=os.getenv("WEBHOOK_LOG_LEVEL", "info"),
    )
