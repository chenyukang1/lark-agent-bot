import asyncio
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.code_review.ddl_notice import (
    NO_DDL_CHANGES,
    REPORT_HEADER,
    DDLNoticeAgent,
)
from app.tools.git import GitCommandError, GitRepository


class DDLNoticeGroupingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = SimpleNamespace(project_path=str(self.root), git_branch="unused")
        self.agent = DDLNoticeAgent.__new__(DDLNoticeAgent)
        self.git("init", "-q")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "user.name", "Developer")
        self.base = self.commit("base@example.com")
        self.first = self.commit("Alice@example.com")
        self.second = self.commit("bob@example.com")
        self.third = self.commit("alice@example.com")

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(self, email):
        self.git("-c", f"user.email={email}", "commit", "--allow-empty", "-qm", email)
        return self.git("rev-parse", "HEAD")

    async def test_groups_range_by_author_email_without_switching_checkout(self):
        main_thread = threading.get_ident()
        fetch_threads = []
        with patch.object(
            GitRepository,
            "fetch",
            side_effect=lambda: fetch_threads.append(threading.get_ident()),
        ):
            result = await asyncio.to_thread(
                self.agent._group_commits_by_email,
                self.config,
                f"{self.base}..{self.third}",
            )
        self.assertEqual(
            result,
            {
                "alice@example.com": [self.first, self.third],
                "bob@example.com": [self.second],
            },
        )
        self.assertNotEqual(fetch_threads[0], main_thread)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.third)

    async def test_empty_range_and_empty_input(self):
        with patch.object(GitRepository, "fetch") as fetch:
            self.assertEqual(
                await self.agent.review_code(
                    SimpleNamespace(codebase_confg=self.config), " "
                ),
                {},
            )
            fetch.assert_not_called()
            self.assertEqual(
                await self.agent.review_code(
                    SimpleNamespace(codebase_confg=self.config),
                    f"{self.third}..{self.third}",
                ),
                {},
            )

    async def test_invalid_revision_propagates_error(self):
        with patch.object(GitRepository, "fetch"), self.assertRaises(GitCommandError):
            await self.agent.review_code(
                SimpleNamespace(codebase_confg=self.config), "missing..revision"
            )


class DDLNoticeOutputTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = DDLNoticeAgent.__new__(DDLNoticeAgent)
        self.agent._sub_agent = SimpleNamespace(run=AsyncMock())
        self.event = SimpleNamespace(
            codebase_confg=SimpleNamespace(project_path="/unused"),
            job_name="stage",
            build_number=42,
            build_url="https://example.com/42",
        )
        grouping = patch.object(
            self.agent,
            "_group_commits_by_email",
            return_value={
                "alice@example.com": ["a" * 40],
            },
        )
        grouping.start()
        self.addCleanup(grouping.stop)
        resolver = patch(
            "app.agents.code_review.ddl_notice.resolve_open_id", return_value="ou_alice"
        )
        resolver.start()
        self.addCleanup(resolver.stop)

    async def test_no_changes_produces_no_notice(self):
        self.agent._sub_agent.run.return_value = "  " + NO_DDL_CHANGES + "\n"
        self.assertEqual(await self.agent.review_code(self.event, "range"), {})

    async def test_change_report_is_preserved(self):
        report = (
            REPORT_HEADER
            + "\n新增持久化字段\n```sql\nALTER TABLE users ADD COLUMN age integer;\n```"
        )
        self.agent._sub_agent.run.return_value = report
        self.assertEqual(
            await self.agent.review_code(self.event, "range"), {"ou_alice": report}
        )

    async def test_unknown_output_is_error_not_no_changes(self):
        for result in (
            None,
            "",
            "  ",
            "DDL_ANALYSIS_INCOMPLETE\n无法读取提交",
            "没有发现变化",
            "NO_DDL_CHANGES\n但仍输出报告",
        ):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.agent._sub_agent.run.return_value = result
                await self.agent.review_code(self.event, "range")

    async def test_no_change_author_does_not_hide_another_report(self):
        report = REPORT_HEADER + "\n新增字段"
        self.agent._sub_agent.run.side_effect = [NO_DDL_CHANGES, report]
        with (
            patch.object(
                self.agent,
                "_group_commits_by_email",
                return_value={
                    "alice@example.com": ["a" * 40],
                    "bob@example.com": ["b" * 40],
                },
            ),
            patch(
                "app.agents.code_review.ddl_notice.resolve_open_id",
                side_effect=["ou_alice", "ou_bob"],
            ),
        ):
            self.assertEqual(
                await self.agent.review_code(self.event, "range"), {"ou_bob": report}
            )
