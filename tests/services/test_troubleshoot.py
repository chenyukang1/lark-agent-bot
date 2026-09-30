import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.devops.v2.subagents import codebase
from app.tools.git import GitCommandError


class TroubleshootTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload = json.dumps(
            {
                "project_path": "/tmp/test-repo",
                "git_branch": "staging",
                "jenkins_job_name": "staging-job",
                "build_number": 42,
                "build_url": "https://example.com/42",
                "duration_ms": 100,
                "commit_range": "a..b",
                "build_errors": "BUILD FAILURE",
                "server_errors": "",
            }
        )

    async def test_analysis_receives_prepared_repository_and_build_context(self):
        backend = MagicMock(run=AsyncMock(return_value="analysis"))
        with (
            patch.object(codebase, "GitRepository") as repository,
            patch.object(
                codebase.SubAgentFactory, "get_sub_agent", return_value=backend
            ),
        ):
            result = await codebase.codebase_analysis(self.payload)
        repository.return_value.fetch.assert_called_once_with()
        repository.return_value.switch_to_remote.assert_called_once_with("staging")
        self.assertEqual(result, "analysis")
        path, prompt = backend.run.call_args.args
        self.assertEqual(path, "/tmp/test-repo")
        self.assertIn("staging-job #42", prompt)
        self.assertIn("BUILD FAILURE", prompt)

    async def test_failed_fetch_stops_switch_and_analysis(self):
        with (
            patch.object(codebase, "GitRepository") as repository,
            patch.object(codebase.SubAgentFactory, "get_sub_agent") as backend,
        ):
            repository.return_value.fetch.side_effect = GitCommandError(
                1, ["git", "fetch"]
            )
            with self.assertRaises(GitCommandError):
                await codebase.codebase_analysis(self.payload)
        repository.return_value.switch_to_remote.assert_not_called()
        backend.assert_not_called()
