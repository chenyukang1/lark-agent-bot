import asyncio
import unittest
from unittest.mock import patch

from app.services import git_analysis


class RepositorySyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_sync_is_shared_by_tools_in_one_run_and_isolated_between_runs(self):
        async def analyze():
            token = git_analysis._synced_repos.set(set())
            try:
                for _ in range(2):
                    error = await asyncio.to_thread(
                        git_analysis._ensure_repo_synced, "/tmp/analysis-repo"
                    )
                    self.assertIsNone(error)
            finally:
                git_analysis._synced_repos.reset(token)

        with patch.object(git_analysis, "_pull_latest_changes", return_value=None) as pull:
            await asyncio.gather(analyze(), analyze())
        self.assertEqual(pull.call_count, 2)
