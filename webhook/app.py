import asyncio
import json
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
    resolve_config,
)
from lark import (
    SendAlarmCardPayload,
    handle_agent_result,
    lark_api_client,
    send_alarm_card,
)
from lark.feishu_mapping import resolve_open_id
from lark.handler import SendMessagePayload, card_update_callback, send_message


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


# Bounded, single-process retry state. Successful recipients are not sent twice
# when another recipient fails and Jenkins retries the callback.
_staging_lock = asyncio.Lock()
_staging_sent: OrderedDict[tuple[str, int], set[str]] = OrderedDict()
_staging_done: set[tuple[str, int]] = set()


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
        try:
            config = resolve_config(event.job_name)
            changes = await asyncio.to_thread(
                collect_build_changes, config, event.build_number
            )
            report = await analyze_build(changes)
            recipients: dict[str, list[str]] = {}
            complete = True
            for finding in report.findings:
                if finding.confidence != "high" or finding.sql_status == "covered":
                    continue
                author = changes.commits[finding.commit_id]
                open_id = await asyncio.to_thread(
                    resolve_open_id,
                    lark_api_client.client,
                    author["name"],
                    author["email"],
                )
                if not open_id or not open_id.startswith("ou_"):
                    complete = False
                    lark_oapi.logger.warning(
                        "DDL 提醒无法匹配飞书用户: commit=%s", finding.commit_id
                    )
                    continue
                recipients.setdefault(open_id, []).append(
                    f"- {finding.commit_id[:12]} / {finding.file_path}\n"
                    f"  {finding.reason}\n  变更依据：{finding.evidence}"
                )
            for open_id, details in recipients.items():
                if open_id in sent:
                    continue
                content = (
                    "检查是否提交sql\n"
                    f"staging 构建：{config.jenkins_job_name} #{event.build_number}\n"
                    f"{event.build_url}\n"
                    "检测到可能需要同步数据库 DDL 的修改：\n"
                    + "\n".join(details)
                    + "\n请确认对应 SQL 已提交并纳入发布；如已单独提交，请忽略此提醒。"
                )
                try:
                    await asyncio.to_thread(
                        send_message,
                        lark_api_client.client,
                        SendMessagePayload(
                            receive_id_type="open_id",
                            receive_id=open_id,
                            msg_type="text",
                            content=json.dumps({"text": content}, ensure_ascii=False),
                        ),
                    )
                    sent.add(open_id)
                except Exception:
                    complete = False
                    lark_oapi.logger.exception(
                        "staging DDL 私聊发送失败: build=%s", key
                    )
            if complete:
                _staging_done.add(key)
            lark_oapi.logger.info(
                "staging DDL 检查结束: build=%s complete=%s recipients=%s",
                key,
                complete,
                len(recipients),
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
