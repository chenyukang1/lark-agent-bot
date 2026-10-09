import asyncio
from collections import OrderedDict

import lark_oapi

from app.agents.ddl import analyze_build, parse_reminders
from app.config import resolve_codebase
from app.lark import get_lark_client
from app.lark.model import SendDDLNoticeCardPayload
from app.lark.users import resolve_open_id
from app.model import JenkinsBuildEvent
from app.tools import collect_build_changes

# Bounded, single-process retry state. Cache reports so retrying a failed
# reminder does not regenerate Markdown or resend successful reminders.
_staging_lock = asyncio.Lock()
_staging_sent: OrderedDict[tuple[str, int], set[int]] = OrderedDict()
_staging_done: set[tuple[str, int]] = set()
_staging_reports: dict[tuple[str, int], tuple] = {}


async def notify_staging_ddl(event: JenkinsBuildEvent) -> None:
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
            config = resolve_codebase(event.job_name)
            if key not in _staging_reports:
                changes = await asyncio.to_thread(
                    collect_build_changes, config, event.build_number
                )
                markdown = await analyze_build(
                    changes,
                    job_name=config.jenkins_job_name,
                    build_number=event.build_number,
                    build_url=event.build_url,
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
                        resolve_open_id,
                        author["name"],
                        author["email"],
                    )
                    if not open_id or not open_id.startswith("ou_"):
                        complete = False
                        lark_oapi.logger.warning(
                            "DDL 提醒无法匹配飞书用户: commit=%s", reminder.commit_id
                        )
                        continue
                    await asyncio.to_thread(
                        get_lark_client().send_ddl_notice_card,
                        SendDDLNoticeCardPayload(
                            receive_id_type="open_id",
                            receive_id=open_id,
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
