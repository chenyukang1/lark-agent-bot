import json
import unittest
from unittest.mock import patch

from app.agents.devops.v1 import tools as v1_tools
from app.config import CodebaseConfig
from app.tools import collect_build_changes
from app.tools.jenkins import JenkinsClient


class JenkinsClientTest(unittest.TestCase):
    def setUp(self):
        self.config = CodebaseConfig(
            alias="stage",
            jenkins_job_name="folder/staging",
            jenkins_url="https://jenkins.example.com",
            jenkins_user="user",
            jenkins_token="token",
            project_path="/tmp/project",
            git_branch="staging",
            semantics_hit_rule="staging",
        )
        patcher = patch("app.tools.jenkins.jenkins.Jenkins", autospec=True)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.server = self.factory.return_value
        self.server.get_job_info.return_value = {
            "lastFailedBuild": {"number": 42, "url": "https://jenkins.example.com/42"}
        }
        self.server.get_build_info.return_value = {
            "result": "FAILURE",
            "url": "https://jenkins.example.com/42",
            "duration": 100,
            "changeSet": {"items": []},
        }
        self.server.get_build_console_output.return_value = "BUILD FAILURE\ncompile error"
        self.server.build_job.return_value = 123
        self.client = JenkinsClient(self.config)

    def test_operations_use_bound_job_instead_of_alias(self):
        self.assertEqual(self.client.get_job_info(), self.server.get_job_info.return_value)
        self.assertEqual(self.client.get_build_info(42), self.server.get_build_info.return_value)
        self.assertIn("BUILD FAILURE", self.client.get_build_console_output(42))
        self.assertEqual(self.client.queue_build(), 123)

        self.server.get_job_info.assert_called_once_with("folder/staging")
        self.server.get_build_info.assert_called_once_with("folder/staging", 42)
        self.server.get_build_console_output.assert_called_once_with("folder/staging", 42)
        self.server.build_job.assert_called_once_with("folder/staging")

    def test_latest_failed_build_uses_bound_job_and_repository(self):
        payload = json.loads(self.client.get_latest_failed_build_info())

        self.assertEqual(payload["jenkins_job_name"], "folder/staging")
        self.assertEqual(payload["build_number"], 42)
        self.assertEqual(payload["project_path"], "/tmp/project")
        self.assertEqual(payload["git_branch"], "staging")
        self.assertIn("compile error", payload["build_errors"])
        self.server.get_job_info.assert_called_once_with("folder/staging")
        self.server.get_build_info.assert_called_once_with("folder/staging", 42)
        self.server.get_build_console_output.assert_called_once_with("folder/staging", 42)

    def test_exact_failed_build_does_not_consult_latest_build(self):
        payload = json.loads(self.client.get_failed_build_info(41))
        self.assertEqual(payload["build_number"], 41)
        self.server.get_job_info.assert_not_called()
        self.server.get_build_info.assert_called_once_with("folder/staging", 41)
        self.server.get_build_console_output.assert_called_once_with("folder/staging", 41)

    def test_v1_tool_uses_bound_job(self):
        with patch.object(
            v1_tools, "get_config", return_value={"codebase_configs": {"stage": self.config}}
        ):
            payload = json.loads(v1_tools.get_latest_failed_build_info("stage"))
        self.assertEqual(payload["build_number"], 42)
        self.server.get_job_info.assert_called_once_with("folder/staging")
        self.server.get_build_info.assert_called_once_with("folder/staging", 42)
        self.server.get_build_console_output.assert_called_once_with("folder/staging", 42)

    def test_v1_console_tool_uses_bound_job(self):
        with patch.object(
            v1_tools, "get_config", return_value={"codebase_configs": {"stage": self.config}}
        ):
            result = v1_tools.extract_failed_build_console_errors("stage")
        self.assertIn("BUILD FAILURE", result)
        self.server.get_build_console_output.assert_called_once_with("folder/staging", 42)

    def test_build_changes_uses_bound_job(self):
        with patch(
            "app.tools.JENKINS_CLIENT_POOL.get_jenkins_client", return_value=self.client
        ):
            changes = collect_build_changes(self.config, 42)
        self.assertFalse(changes.commits)
        self.server.get_build_info.assert_called_once_with("folder/staging", 42)
