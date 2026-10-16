import asyncio
import logging
import os

import lark_oapi

from app.agents import ddl_notice_agent, devopsAgentV2
from app.lark import get_lark_client
from app.lark.handlers import handle_agent_output
from app.lark.model import (
    SendAlarmCardPayload,
    UpdateAlarmCardPayload,
)
from app.model import JenkinsBuildEvent
from app.tools import JENKINS_CLIENT_POOL

logger = logging.getLogger(__name__)


async def jenkins_failure_callback(event: JenkinsBuildEvent) -> None:
    notify_chat_id = os.getenv("NOTIFY_CHAT_ID")
    if not notify_chat_id:
        logger.error("NOTIFY_CHAT_ID 未配置，无法发送飞书通知")
        return

    receive_id_type = "open_id" if notify_chat_id.startswith("ou_") else "chat_id"
    intro = (
        f"收到 Jenkins 构建失败通知\n"
        f"- Job: {event.job_name}\n"
        f"- 构建号: #{event.build_number}\n"
        f"- 状态: 构建失败\n"
        f"正在分析中..."
    )

    lark_client = get_lark_client()
    create_message_resp = lark_client.send_alarm_card(
        SendAlarmCardPayload(
            receive_id_type=receive_id_type,
            receive_id=notify_chat_id,
            report_content=intro,
        ),
    )
    response_data = create_message_resp.data
    if response_data is None:
        lark_oapi.logger.error("飞书告警卡片发送失败：响应数据为空")
        return

    card_message_id = response_data.message_id

    task = asyncio.create_task(
        devopsAgentV2.handle_user_query(
            notify_chat_id,
            notify_chat_id,
            build_agent_instruction(event),
            lambda t: lark_client.update_alarm_card(
                UpdateAlarmCardPayload(
                    message_id=card_message_id,
                    report_type="processing",
                    report_content=t,
                ),
            ),
        )
    )
    task.add_done_callback(
        lambda t: handle_agent_output(
            card_message_id, receive_id_type, notify_chat_id, t.result()
        )
    )


async def jenkins_start_callback(event: JenkinsBuildEvent):
    if not event.codebase_confg:
        return

    jenkins_client = JENKINS_CLIENT_POOL.get_jenkins_client(event.codebase_confg.alias)
    build_info = jenkins_client.get_build_info(event.build_number)
    change_set = build_info.get("changeSet", {})
    items = change_set.get("items", [])
    if not items:
        return
    commit_ids = [item["commitId"] for item in items]
    task = asyncio.create_task(ddl_notice_agent.review_code(event, commit_ids))
    task.add_done_callback(lambda t: ddl_notice_agent.send_ddl_notice(t.result()))


def build_agent_instruction(event: JenkinsBuildEvent) -> str:
    parts = [
        f"Jenkins Job【{event.job_name}】构建失败，",
        "请分析最可能导致失败的提交人（committer）。",
    ]
    return "".join(parts)
