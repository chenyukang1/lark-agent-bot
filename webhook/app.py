import asyncio
import os
from collections import OrderedDict
from contextlib import asynccontextmanager

import lark_oapi
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from devopsagents import DevopsAgent
from devopsagents.agents.ddl_agent import (
    analyze_build,
    collect_build_changes,
    parse_reminders,
    resolve_config,
)
from lark import (
    SendAlarmCardPayload,
    SendSQLNoticeCardPayload,
    handle_agent_result,
    lark_api_client,
    send_alarm_card,
    send_sql_notice_card,
)
from lark.feishu_mapping import resolve_open_id
from lark.handler import card_update_callback


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
    build_number: int = Field(gt=0)
    build_url: str
    phase: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not NOTIFY_CHAT_ID:
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
    background_tasks.add_task(_notify_jenkins_failure, event)
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
        config = resolve_config(payload.job_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    event = JenkinsBuildEvent(**payload.model_dump())
    # Normalize aliases so repeated callbacks share the same notification state.
    event.job_name = config.alias
    background_tasks.add_task(_notify_staging_ddl, event)
    return JSONResponse(
        {
            "accepted": True,
            "analyzing": True,
            "job_name": payload.job_name,
            "build_number": payload.build_number,
        },
        status_code=202,
    )


# Bounded, single-process retry state. Cache reports so retrying a failed
# reminder does not regenerate Markdown or resend successful reminders.
_staging_lock = asyncio.Lock()
_staging_sent: OrderedDict[tuple[str, int], set[int]] = OrderedDict()
_staging_done: set[tuple[str, int]] = set()
_staging_reports: dict[tuple[str, int], tuple] = {}


async def _notify_staging_ddl(event: JenkinsBuildEvent) -> None:
    async with _staging_lock:
        key = (event.job_name, event.build_number)
        if key in _staging_done:
            return
        sent = _staging_sent.setdefault(key, set())
        _staging_sent.move_to_end(key)
        while len(_staging_sent) > 1000:
            expired, _ = _staging_sent.popitem(last=False)
            _staging_done.discard(expired)
            _staging_reports.pop(expired, None)
        try:
            config = resolve_config(event.job_name)
            if key not in _staging_reports:
                changes = await asyncio.to_thread(
                    collect_build_changes, config, event.build_number
                )
                markdown = await analyze_build(
                    changes, job_name=config.jenkins_job_name,
                    build_number=event.build_number, build_url=event.build_url,
                )
                reminders = parse_reminders(markdown, changes)
                _staging_reports[key] = (changes, reminders)
            changes, reminders = _staging_reports[key]
            complete = True
            for index, reminder in enumerate(reminders):
                if index in sent:
                    continue
                author = changes.commits[reminder.commit_id]
                try:
                    open_id = await asyncio.to_thread(
                        resolve_open_id, lark_api_client.client,
                        author["name"], author["email"],
                    )
                    if not open_id or not open_id.startswith("ou_"):
                        complete = False
                        lark_oapi.logger.warning(
                            "DDL 提醒无法匹配飞书用户: commit=%s", reminder.commit_id
                        )
                        continue
                    await asyncio.to_thread(
                        send_sql_notice_card,
                        lark_api_client.client,
                        SendSQLNoticeCardPayload(
                            receive_id_type="open_id", receive_id=open_id,
                            report_content=reminder.markdown,
                        ),
                    )
                    sent.add(index)
                except Exception:
                    complete = False
                    lark_oapi.logger.exception(
                        "staging DDL 私聊发送失败: build=%s reminder=%s", key, index
                    )
            if complete:
                _staging_done.add(key)
            lark_oapi.logger.info(
                "staging DDL 检查结束: build=%s complete=%s reminders=%s",
                key,
                complete,
                len(reminders),
            )
        except Exception:
            lark_oapi.logger.exception(
                "staging DDL 检查失败，需人工检查 SQL: build=%s", key
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
            report_content=intro,
        ),
    )
    card_message_id = create_message_resp.data.message_id

    def card_callback(content):
        return card_update_callback(lark_api_client.client, card_message_id, content)

    task = asyncio.create_task(
        devops_agent.handle_user_query(
            NOTIFY_CHAT_ID,
            NOTIFY_CHAT_ID,
            build_agent_instruction(event),
            card_callback,
        )
    )
    task.add_done_callback(
        lambda t: handle_agent_result(
            lark_api_client.client, card_message_id, receive_id_type, NOTIFY_CHAT_ID, t
        )
    )


def build_agent_instruction(event: JenkinsBuildEvent) -> str:
    parts = [
        f"Jenkins Job【{event.job_name}】构建失败，",
        "请分析最可能导致失败的提交人（committer）。",
    ]
    return "".join(parts)


devops_agent = DevopsAgent()
