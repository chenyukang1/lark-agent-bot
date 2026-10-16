import asyncio
import logging
import os
from collections import OrderedDict

import lark_oapi

from app.agents import ddl_notice_agent, devopsAgentV2
from app.lark import get_lark_client
from app.lark.handlers import handle_agent_output
from app.lark.model import (
    SendAlarmCardPayload,
    UpdateAlarmCardPayload,
)
from app.lark.users import resolve_open_id
from app.model import JenkinsBuildEvent
from app.tools import collect_build_changes

logger = logging.getLogger(__name__)

# Process-local retry state. Keep active/partially sent builds until they finish;
# bound the completed-build history to avoid retaining every build forever.
_running_builds: set[tuple[str, int]] = set()
_pending_build_reports: dict[tuple[str, int], dict[str, str]] = {}
_completed_builds: OrderedDict[tuple[str, int], None] = OrderedDict()
_COMPLETED_BUILD_LIMIT = 1024


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


async def jenkins_start_callback(event: JenkinsBuildEvent) -> None:
    if not event.codebase_confg:
        return

    key = (event.codebase_confg.alias, event.build_number)
    if key in _running_builds or key in _completed_builds:
        return

    # Claim before the first await so concurrent callbacks cannot both start.
    _running_builds.add(key)
    try:
        if key not in _pending_build_reports:
            build_changes = await asyncio.to_thread(
                collect_build_changes, event.codebase_confg, event.build_number
            )
            commits: dict[str, list[str]] = {}
            for commit_id, detail in build_changes.commits.items():
                open_id = resolve_open_id(email=detail["email"], name=detail["name"])
                commits.setdefault(open_id, []).append(commit_id)

            reports = (
                await ddl_notice_agent.review_code(event, commits) if commits else {}
            )
            _pending_build_reports[key] = dict(reports)

        pending = _pending_build_reports[key]
        for open_id, report in list(pending.items()):
            await ddl_notice_agent.send_ddl_notice({open_id: report})
            del pending[open_id]

        _completed_builds[key] = None
        _pending_build_reports.pop(key)
        while len(_completed_builds) > _COMPLETED_BUILD_LIMIT:
            _completed_builds.popitem(last=False)
    finally:
        _running_builds.discard(key)


def build_agent_instruction(event: JenkinsBuildEvent) -> str:
    parts = [
        f"Jenkins Job【{event.job_name}】构建失败，",
        "请分析最可能导致失败的提交人（committer）。",
    ]
    return "".join(parts)
