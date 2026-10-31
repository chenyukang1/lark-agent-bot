import asyncio
import json
import threading
import unittest
from unittest.mock import MagicMock, patch

from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

# Agent 实例在导入时初始化；测试不依赖本地配置和 API 密钥。
with patch("app.config.get_config", return_value={
    "codebase_configs": {},
    "dashscope_api_key": "test",
    "dashscope_api_host": "https://example.com",
    "sub_agent": "claude",
}):
    from app.lark import handlers

from app.lark.client import LarkClient


class CardActionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = MagicMock()
        self.pool = MagicMock()
        self.jenkins = self.pool.get_jenkins_client.return_value
        self.jenkins.queue_build.return_value = 123
        self.jenkins.wait_for_build_result.return_value = {
            "build_number": 43,
            "build_url": "https://jenkins.example.com/job/43/",
            "result": "SUCCESS",
        }
        self.enterContext(patch.object(handlers, "get_lark_client", return_value=self.client))
        self.enterContext(patch.object(handlers, "JENKINS_CLIENT_POOL", self.pool))
        self.tracker = MagicMock()
        self.tracker.pending.return_value = []
        self.enterContext(patch.object(handlers, "BuildTracker", return_value=self.tracker))
        self.enterContext(patch.dict(handlers.card_states, {
            "om_card": {
                "alias": "test_java",
                "report_content": "故障分析结果",
                "alarm_time": "2026-10-14 12:00:00",
                "source_build_number": 42,
            },
        }, clear=True))
        self.handler = handlers.P2CardActionTriggerHandler()
        self.event = P2CardActionTrigger({
            "event": {
                "operator": {"open_id": "ou_operator"},
                "context": {"open_message_id": "om_card"},
                "action": {"tag": "button", "value": {"action": "rebuild"}},
            },
        })

    async def test_callback_and_event_loop_remain_responsive_during_build_and_send(self):
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        build_started, send_started = asyncio.Event(), asyncio.Event()
        release_build, release_send = threading.Event(), threading.Event()
        worker_threads = []

        def trigger():
            worker_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(build_started.set)
            if not release_build.wait(5):
                raise TimeoutError("Test did not release Jenkins request")
            return 123

        def send(payload):
            worker_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(send_started.set)
            if not release_send.wait(5):
                raise TimeoutError("Test did not release card request")

        self.jenkins.queue_build.side_effect = trigger
        self.client.send_alarm_card.side_effect = send
        self.client.mark_rebuild_card_resolved.side_effect = (
            lambda *args, **kwargs: worker_threads.append(threading.get_ident())
        )

        response = self.handler.handle(self.event)
        tasks = tuple(self.handler._background_tasks)
        self.assertEqual(response.toast.content, "已收到构建请求，正在后台触发")
        self.assertIsNone(response.card)
        self.assertEqual(len(tasks), 1)
        self.pool.get_jenkins_client.assert_not_called()

        try:
            await asyncio.wait_for(build_started.wait(), 2)
            self.client.send_alarm_card.assert_not_called()
            release_build.set()
            await asyncio.wait_for(send_started.wait(), 2)
            self.client.mark_rebuild_card_resolved.assert_not_called()
        finally:
            release_build.set()
            release_send.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 2)

        payload = self.client.send_alarm_card.call_args_list[0].args[0]
        self.assertEqual(payload.receive_id_type, "open_id")
        self.assertEqual(payload.receive_id, "ou_operator")
        self.assertIn("队列 #123", payload.report_content)
        self.client.mark_rebuild_card_resolved.assert_called_once_with(
            "om_card", report_content="故障分析结果", alarm_time="2026-10-14 12:00:00",
        )
        self.assertEqual(len(worker_threads), 4)
        self.assertNotIn(loop_thread, worker_threads)
        self.assertFalse(self.handler._background_tasks)

    async def test_build_failure_is_sent_without_resolving_original_card(self):
        self.jenkins.wait_for_build_result.return_value["result"] = "FAILURE"
        self.handler.handle(self.event)
        await asyncio.gather(*self.handler._background_tasks)

        payload = self.client.send_alarm_card.call_args.args[0]
        self.assertIn("结果：FAILURE", payload.report_content)
        self.client.mark_rebuild_card_resolved.assert_not_called()

    async def test_result_lookup_error_leaves_card_pending(self):
        self.jenkins.wait_for_build_result.side_effect = TimeoutError("timeout")
        with self.assertLogs(handlers.logger, level="ERROR"):
            self.handler.handle(self.event)
            await asyncio.gather(*self.handler._background_tasks)
        self.client.mark_rebuild_card_resolved.assert_not_called()
        self.tracker.record_result.assert_not_called()
        self.tracker.mark_notified.assert_not_called()
        self.assertIn("无法确认", self.client.send_alarm_card.call_args.args[0].report_content)

    async def test_duplicate_callback_schedules_only_one_build(self):
        first_response = self.handler.handle(self.event)
        second_response = self.handler.handle(self.event)
        await asyncio.gather(*self.handler._background_tasks)

        self.assertEqual(first_response.toast.content, "已收到构建请求，正在后台触发")
        self.assertIsNone(second_response.toast)
        self.assertNotIn("om_card", handlers.card_states)
        self.assertEqual(self.pool.get_jenkins_client.call_count, 2)
        self.jenkins.queue_build.assert_called_once_with()
        self.tracker.record_queued.assert_called_once_with(
            card_message_id="om_card", alias="test_java", open_id="ou_operator",
            report_content="故障分析结果", alarm_time="2026-10-14 12:00:00",
            source_build_number=42, queue_id=123,
        )

    async def test_background_errors_are_logged_without_retriggering_build(self):
        for operation in (
            self.pool.get_jenkins_client,
            self.jenkins.queue_build,
            self.jenkins.wait_for_build_result,
            self.client.send_alarm_card,
            self.client.mark_rebuild_card_resolved,
        ):
            with self.subTest(operation=operation):
                self.pool.reset_mock()
                self.client.reset_mock()
                handlers.card_states["om_card"] = {
                    "alias": "test_java",
                    "report_content": "故障分析结果",
                    "alarm_time": "2026-10-14 12:00:00",
                    "source_build_number": 42,
                }
                operation.side_effect = RuntimeError("service unavailable")
                try:
                    with self.assertLogs(handlers.logger, level="ERROR") as logs:
                        self.handler.handle(self.event)
                        await asyncio.gather(*self.handler._background_tasks)
                    self.assertIn("message_id=om_card", logs.output[0])
                    self.assertLessEqual(self.jenkins.queue_build.call_count, 1)
                    self.assertFalse(self.handler._background_tasks)
                finally:
                    operation.side_effect = None

    async def test_unknown_card_does_not_schedule_build(self):
        handlers.card_states.clear()
        self.handler.handle(self.event)
        self.assertFalse(self.handler._background_tasks)
        self.pool.get_jenkins_client.assert_not_called()

    async def test_missing_operator_does_not_schedule_build(self):
        self.event.event.operator = None
        with self.assertLogs(handlers.logger, level="WARNING"):
            self.handler.handle(self.event)
        self.assertFalse(self.handler._background_tasks)
        self.pool.get_jenkins_client.assert_not_called()


class RebuildCardUpdateTest(unittest.TestCase):
    def test_background_card_update_preserves_report_and_alarm_time(self):
        client = object.__new__(LarkClient)
        client.rebuild_card_id = "rebuild_template"
        client._client = MagicMock()
        client.mark_rebuild_card_resolved(
            "om_card", report_content="故障分析结果", alarm_time="2026-10-14 12:00:00",
        )

        request = client._client.im.v1.message.patch.call_args.args[0]
        self.assertEqual(request.message_id, "om_card")
        variables = json.loads(request.request_body.content)["data"]["template_variable"]
        self.assertEqual(variables["report_content"], "故障分析结果")
        self.assertEqual(variables["alarm_time"], "2026-10-14 12:00:00")
        self.assertEqual(variables["header_color"], "green")


if __name__ == "__main__":
    unittest.main()
