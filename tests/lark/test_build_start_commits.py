import asyncio
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.agents.code_review.ddl_notice import DDLNoticeAgent
from app.lark import callback
from app.tools.git import GitRepository


class BuildStartCommitsTest(unittest.IsolatedAsyncioTestCase):
    async def test_passes_jenkins_commit_list_to_review(self):
        event = SimpleNamespace(
            codebase_confg=SimpleNamespace(alias="stage"), build_number=42
        )
        for commit_ids in (["a" * 40], ["b" * 40, "a" * 40], []):
            with self.subTest(commit_ids=commit_ids):
                event.build_number += 1
                client = Mock()
                client.get_build_info.return_value = {
                    "changeSet": {"items": [{"commitId": c} for c in commit_ids]}
                }
                review = AsyncMock(return_value={})
                with (
                    patch.object(
                        callback.JENKINS_CLIENT_POOL,
                        "get_jenkins_client",
                        return_value=client,
                    ),
                    patch.object(callback.ddl_notice_agent, "review_code", review),
                    patch.object(callback.ddl_notice_agent, "send_ddl_notice"),
                ):
                    await callback.jenkins_start_callback(event)
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                if commit_ids:
                    review.assert_awaited_once_with(event, commit_ids)
                else:
                    review.assert_not_called()

    def tearDown(self):
        callback._running_builds.clear()
        callback._pending_build_reports.clear()
        callback._completed_builds.clear()


class CommitListGroupingTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = SimpleNamespace(project_path=directory.name)
        self.agent = DDLNoticeAgent.__new__(DDLNoticeAgent)
        self.git("init", "-q")
        self.git("config", "user.name", "Developer")
        self.git("config", "user.email", "developer@example.com")
        self.git("config", "commit.gpgsign", "false")
        self.commits = []
        for index in range(4):
            self.git("commit", "--allow-empty", "-qm", str(index))
            self.commits.append(self.git("rev-parse", "HEAD"))

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.config.project_path,
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_only_requested_commits_are_grouped(self):
        for commit_ids in (
            [self.commits[0]],
            [self.commits[2]],
            [self.commits[3], self.commits[1]],
        ):
            with self.subTest(commit_ids=commit_ids), patch.object(GitRepository, "fetch"):
                self.assertEqual(
                    self.agent._group_commits_by_email(self.config, commit_ids),
                    {"developer@example.com": commit_ids},
                )

    def test_empty_list_does_not_read_head(self):
        with patch.object(GitRepository, "fetch") as fetch:
            self.assertEqual(self.agent._group_commits_by_email(self.config, []), {})
        fetch.assert_not_called()
