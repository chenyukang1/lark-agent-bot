import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.devops.v2.agent import DevopsAgentV2
from app.config import CodebaseConfig
from app.tools.jenkins import JenkinsBuildException, JenkinsClient


class ExactBuildTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_analyzes_requested_build_without_routing(self):
        agent = DevopsAgentV2.__new__(DevopsAgentV2)
        agent.codebase_agent = MagicMock()
        agent.codebase_agent.codebase_analysis = AsyncMock(return_value="report")
        client = MagicMock()
        client.get_failed_build_info.return_value = '{"build_number": 41}'
        progress = MagicMock()

        with patch(
            "app.agents.devops.v2.agent.JENKINS_CLIENT_POOL"
        ) as pool:
            pool.get_jenkins_client.return_value = client
            decision, report = await agent.analyze_failed_build("stage", 41, progress)

        self.assertEqual((decision.intent, decision.alias, report), ("troubleshoot", "stage", "report"))
        client.get_failed_build_info.assert_called_once_with(41)
        agent.codebase_agent.codebase_analysis.assert_awaited_once_with(
            '{"build_number": 41}'
        )

    async def test_jenkins_rejects_non_failed_build(self):
        config = CodebaseConfig(
            alias="stage", jenkins_job_name="job", jenkins_url="https://example.com",
            jenkins_user="user", jenkins_token="token", project_path="/tmp/repo",
            git_branch="main", semantics_hit_rule="stage",
        )
        with patch("app.tools.jenkins.jenkins.Jenkins") as factory:
            factory.return_value.get_build_info.return_value = {"result": "SUCCESS"}
            client = JenkinsClient(config)
            with self.assertRaises(JenkinsBuildException):
                client.get_failed_build_info(41)
            factory.return_value.get_build_console_output.assert_not_called()

    async def test_jenkins_payload_uses_requested_build_and_its_changes(self):
        config = CodebaseConfig(
            alias="stage", jenkins_job_name="job", jenkins_url="https://example.com",
            jenkins_user="user", jenkins_token="token", project_path="/tmp/repo",
            git_branch="main", semantics_hit_rule="stage",
        )
        with patch("app.tools.jenkins.jenkins.Jenkins") as factory:
            server = factory.return_value
            server.get_build_info.return_value = {
                "result": "FAILURE", "url": "https://example.com/job/41/",
                "changeSet": {"items": [{"commitId": "abc123", "msg": "change"}]},
            }
            server.get_build_console_output.return_value = "BUILD FAILURE\nerror"
            payload = json.loads(JenkinsClient(config).get_failed_build_info(41))
            server.get_job_info.assert_not_called()
            server.get_build_info.assert_called_once_with("job", 41)
        self.assertEqual(payload["build_number"], 41)
        self.assertEqual(payload["commits"], [{"id": "abc123", "message": "change"}])
