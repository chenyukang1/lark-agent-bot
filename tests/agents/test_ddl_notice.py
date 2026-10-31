import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agents.code_review.ddl_notice import (
    ANALYSIS_INCOMPLETE,
    NO_DDL_CHANGES,
    REPORT_HEADER,
    DDLNoticeAgent,
)


class DDLNoticeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = DDLNoticeAgent.__new__(DDLNoticeAgent)
        self.agent._sub_agent = SimpleNamespace(run=AsyncMock())
        self.event = SimpleNamespace(
            codebase_confg=SimpleNamespace(project_path="/unused"),
            job_name="stage",
            build_number=42,
            build_url="https://example.com/42",
        )
        self.commits = {"ou_alice": ["a" * 40]}

    async def test_empty_commits_do_not_call_model(self):
        self.assertEqual(await self.agent.review_code(self.event, {}), {})
        self.agent._sub_agent.run.assert_not_called()

    async def test_no_changes_produce_no_notice(self):
        self.agent._sub_agent.run.return_value = f"  {NO_DDL_CHANGES}\n"
        self.assertEqual(await self.agent.review_code(self.event, self.commits), {})

    async def test_change_report_preserves_recipient_and_commit_context(self):
        report = REPORT_HEADER + "\n新增持久化字段"
        self.agent._sub_agent.run.return_value = report
        self.assertEqual(
            await self.agent.review_code(self.event, self.commits),
            {"ou_alice": report},
        )
        kwargs = self.agent._sub_agent.run.call_args.kwargs
        self.assertEqual(kwargs["work_dir"], "/unused")
        self.assertIn("a" * 40, kwargs["prompt"])
        self.assertIn("stage #42", kwargs["prompt"])

    async def test_incomplete_or_unrecognized_output_is_not_sent(self):
        for output in (ANALYSIS_INCOMPLETE + "\n缺少上下文", "没有发现变化"):
            with self.subTest(output=output):
                self.agent._sub_agent.run.return_value = output
                self.assertEqual(await self.agent.review_code(self.event, self.commits), {})

    async def test_empty_model_output_raises_for_retry(self):
        for output in (None, "", "  "):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.agent._sub_agent.run.return_value = output
                await self.agent.review_code(self.event, self.commits)

    async def test_one_author_without_changes_does_not_hide_another(self):
        report = REPORT_HEADER + "\n新增字段"
        self.agent._sub_agent.run.side_effect = [NO_DDL_CHANGES, report]
        commits = {"ou_alice": ["a" * 40], "ou_bob": ["b" * 40]}
        self.assertEqual(
            await self.agent.review_code(self.event, commits),
            {"ou_bob": report},
        )
