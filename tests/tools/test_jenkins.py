import json
import threading
import unittest
from unittest.mock import patch

from app.agents.devops.v1 import tools as v1_tools
from app.config import CodebaseConfig
from app.tools import collect_build_changes
from app.tools.jenkins import JenkinsBuildBusyError, JenkinsBuildException, JenkinsClient


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
        self.server.get_info.return_value = {"inQueue": False, "allBuilds": []}
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
        self.server.get_info.assert_called_once_with(
            "job/folder/job/staging", query="?tree=inQueue,allBuilds[number,building]"
        )

    def test_running_build_rejects_submission_even_when_newest_build_finished(self):
        self.server.get_info.return_value = {
            "inQueue": False,
            "allBuilds": [{"number": 43, "building": False},
                          {"number": 42, "building": True}],
        }
        with self.assertRaisesRegex(JenkinsBuildBusyError, "#42 正在执行"):
            self.client.queue_build()
        self.server.build_job.assert_not_called()

    def test_queued_build_rejects_submission(self):
        self.server.get_info.return_value = {"inQueue": True, "allBuilds": []}
        with self.assertRaisesRegex(JenkinsBuildBusyError, "排队"):
            self.client.queue_build()
        self.server.build_job.assert_not_called()

    def test_finished_build_allows_submission(self):
        self.server.get_info.return_value = {
            "inQueue": False, "allBuilds": [{"number": 42, "building": False}],
        }
        self.assertEqual(self.client.queue_build(), 123)
        self.server.build_job.assert_called_once_with("folder/staging")

    def test_status_error_or_incomplete_response_never_submits(self):
        for status in ({}, {"inQueue": False},
                       {"inQueue": False, "allBuilds": [{"number": 42}]}):
            with self.subTest(status=status):
                self.server.get_info.return_value = status
                with self.assertRaises(JenkinsBuildException):
                    self.client.queue_build()
        self.server.get_info.side_effect = RuntimeError("Jenkins unavailable")
        with self.assertRaisesRegex(RuntimeError, "Jenkins unavailable"):
            self.client.queue_build()
        self.server.build_job.assert_not_called()

    def test_trigger_reports_busy_as_failure(self):
        self.server.get_info.return_value = {
            "inQueue": False, "allBuilds": [{"number": 42, "building": True}],
        }
        result = self.client.trigger_jenkins_build()
        self.assertIn("打包失败", result)
        self.assertIn("#42 正在执行", result)
        self.server.build_job.assert_not_called()

    def test_simultaneous_request_is_rejected_during_submission(self):
        started, release = threading.Event(), threading.Event()

        def submit(job_name):
            started.set()
            if not release.wait(2):
                raise TimeoutError("test did not release submission")
            return 123

        self.server.build_job.side_effect = submit
        outcomes = []
        worker = threading.Thread(target=lambda: outcomes.append(self.client.queue_build()))
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaises(JenkinsBuildBusyError):
                self.client.queue_build()
        finally:
            release.set()
            worker.join(2)
        self.assertEqual(outcomes, [123])
        self.server.build_job.assert_called_once()

    def test_status_query_failure_releases_submission_lock(self):
        self.server.get_info.side_effect = RuntimeError("unavailable")
        with self.assertRaises(RuntimeError):
            self.client.queue_build()
        self.server.get_info.side_effect = None
        self.assertEqual(self.client.queue_build(), 123)

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
