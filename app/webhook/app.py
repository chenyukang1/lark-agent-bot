import os
from contextlib import asynccontextmanager

import lark_oapi
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.config import get_config, resolve_codebase
from app.lark.callback import jenkins_failure_callback
from app.model import JenkinsBuildEvent, WebhookPayload
from app.services.staging_ddl import notify_staging_ddl


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
    background_tasks.add_task(jenkins_failure_callback, event)
    return JSONResponse(
        {
            "accepted": True,
            "analyzing": True,
            "job_name": event.job_name,
            "build_number": event.build_number,
        }
    )


@app.post("/webhook/jenkins/staging")
async def jenkins_staging_webhook(
    background_tasks: BackgroundTasks,
    payload: WebhookPayload,
) -> JSONResponse:
    try:
        config = resolve_codebase(payload.job_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    event = JenkinsBuildEvent(**payload.model_dump())
    # Normalize aliases so repeated callbacks share the same notification state.
    event.job_name = config.alias
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
