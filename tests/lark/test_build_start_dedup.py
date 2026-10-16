import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from app.lark import callback


class BuildStartDedupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name in ("_running_builds", "_pending_build_reports", "_completed_builds"):
            state = getattr(callback, name)
            state.clear()
            self.addCleanup(state.clear)
        self.event = SimpleNamespace(
            codebase_confg=SimpleNamespace(alias="stage"), build_number=42,
            job_name="jenkins-stage",
        )
        self.client = Mock()
        self.client.get_build_info.return_value = {
            "changeSet": {"items": [{"commitId": "a" * 40}]}
        }
        self.review = AsyncMock(return_value={"ou_a": "report a", "ou_b": "report b"})
        self.send = AsyncMock()
        for target, name, replacement in (
            (callback.JENKINS_CLIENT_POOL, "get_jenkins_client", Mock(return_value=self.client)),
            (callback.ddl_notice_agent, "review_code", self.review),
            (callback.ddl_notice_agent, "send_ddl_notice", self.send),
        ):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_concurrent_and_completed_duplicates_are_skipped(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def review(*args):
            started.set()
            await release.wait()
            return {"ou_a": "report a"}

        self.review.side_effect = review
        task = asyncio.create_task(callback.jenkins_start_callback(self.event))
        try:
            await asyncio.wait_for(started.wait(), 2)
            self.event.job_name = "stage"
            await callback.jenkins_start_callback(self.event)
        finally:
            release.set()
            await task
        await callback.jenkins_start_callback(self.event)
        self.client.get_build_info.assert_called_once()
        self.review.assert_awaited_once()
        self.send.assert_awaited_once_with({"ou_a": "report a"})

    async def test_partial_delivery_retries_only_unsent_reports(self):
        self.send.side_effect = [None, RuntimeError("send failed"), None]
        with self.assertRaises(RuntimeError):
            await callback.jenkins_start_callback(self.event)
        await callback.jenkins_start_callback(self.event)
        await callback.jenkins_start_callback(self.event)
        self.review.assert_awaited_once()
        self.client.get_build_info.assert_called_once()
        self.assertEqual(self.send.await_args_list, [
            call({"ou_a": "report a"}), call({"ou_b": "report b"}),
            call({"ou_b": "report b"}),
        ])

    async def test_fetch_and_review_failures_allow_retry(self):
        self.client.get_build_info.side_effect = [
            RuntimeError("Jenkins unavailable"),
            {"changeSet": {"items": [{"commitId": "a" * 40}]}},
            {"changeSet": {"items": [{"commitId": "a" * 40}]}},
        ]
        self.review.side_effect = [RuntimeError("review failed"), {}]
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await callback.jenkins_start_callback(self.event)
        await callback.jenkins_start_callback(self.event)
        await callback.jenkins_start_callback(self.event)
        self.assertEqual(self.client.get_build_info.call_count, 3)
        self.assertEqual(self.review.await_count, 2)
        self.send.assert_not_called()

    async def test_different_builds_and_codebases_are_independent(self):
        await callback.jenkins_start_callback(self.event)
        self.event.build_number += 1
        await callback.jenkins_start_callback(self.event)
        self.event.codebase_confg.alias = "other"
        await callback.jenkins_start_callback(self.event)
        self.assertEqual(self.review.await_count, 3)

    async def test_empty_changes_are_completed_without_review(self):
        self.client.get_build_info.return_value = {"changeSet": {"items": []}}
        await callback.jenkins_start_callback(self.event)
        await callback.jenkins_start_callback(self.event)
        self.client.get_build_info.assert_called_once()
        self.review.assert_not_called()
        self.send.assert_not_called()
