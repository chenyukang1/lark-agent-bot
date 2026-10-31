import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.lark import callback
from app.tools import BuildChanges, collect_build_changes
from app.tools.git import GitRepository


class BuildStartCommitsTest(unittest.IsolatedAsyncioTestCase):
    async def test_passes_only_jenkins_commits_grouped_by_recipient(self):
        event = SimpleNamespace(
            codebase_confg=SimpleNamespace(alias="stage"), build_number=42
        )
        commits = {
            "a" * 40: {"name": "Alice", "email": "alice@example.com"},
            "b" * 40: {"name": "Bob", "email": "bob@example.com"},
        }
        review = AsyncMock(return_value={})
        agent = SimpleNamespace(review_code=review, send_ddl_notice=AsyncMock())
        with (
            patch.object(callback, "collect_build_changes", return_value=BuildChanges(commits, "")) as collect,
            patch.object(callback, "resolve_open_id", side_effect=["ou_alice", "ou_bob"]),
            patch.object(callback, "ddl_notice_agent", agent),
        ):
            await callback.jenkins_start_callback(event)
        collect.assert_called_once_with(event.codebase_confg, 42)
        review.assert_awaited_once_with(
            event, {"ou_alice": ["a" * 40], "ou_bob": ["b" * 40]}
        )

    async def test_empty_change_set_skips_review(self):
        event = SimpleNamespace(
            codebase_confg=SimpleNamespace(alias="stage"), build_number=43
        )
        review = AsyncMock()
        agent = SimpleNamespace(review_code=review, send_ddl_notice=AsyncMock())
        with (
            patch.object(callback, "collect_build_changes", return_value=BuildChanges({}, "")),
            patch.object(callback, "ddl_notice_agent", agent),
        ):
            await callback.jenkins_start_callback(event)
        review.assert_not_awaited()

    def tearDown(self):
        callback._running_builds.clear()
        callback._pending_build_reports.clear()
        callback._completed_builds.clear()


class BuildChangeCollectionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = directory.name
        self.config = SimpleNamespace(project_path=self.path, alias="stage")
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
            ["git", *args], cwd=self.path,
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_collects_only_requested_commits_without_changing_checkout(self):
        head = self.git("rev-parse", "HEAD")
        for ids in ([self.commits[0]], [self.commits[2]], [self.commits[3], self.commits[1]]):
            with self.subTest(ids=ids):
                client = Mock()
                client.get_build_info.return_value = {
                    "changeSet": {"items": [{"commitId": cid} for cid in ids]}
                }
                with (
                    patch("app.tools.JENKINS_CLIENT_POOL.get_jenkins_client", return_value=client),
                    patch.object(GitRepository, "fetch") as fetch,
                ):
                    result = collect_build_changes(self.config, 42)
                self.assertEqual(list(result.commits), ids)
                fetch.assert_not_called()
                self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_empty_change_set_does_not_read_repository(self):
        client = Mock()
        client.get_build_info.return_value = {"changeSet": {"items": []}}
        with (
            patch("app.tools.JENKINS_CLIENT_POOL.get_jenkins_client", return_value=client),
            patch.object(GitRepository, "fetch") as fetch,
        ):
            self.assertEqual(collect_build_changes(self.config, 42).commits, {})
        fetch.assert_not_called()
