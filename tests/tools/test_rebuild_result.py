import unittest
from unittest.mock import patch

from app.config import CodebaseConfig
from app.tools.jenkins import JenkinsClient


class RebuildResultTest(unittest.TestCase):
    def setUp(self):
        config = CodebaseConfig(
            alias="stage", jenkins_job_name="job", jenkins_url="https://example.com",
            jenkins_user="user", jenkins_token="token", project_path="/tmp/repo",
            git_branch="main", semantics_hit_rule="stage",
        )
        factory = patch("app.tools.jenkins.jenkins.Jenkins")
        self.server = factory.start().return_value
        self.server.get_info.return_value = {"inQueue": False, "allBuilds": []}
        self.addCleanup(factory.stop)
        self.client = JenkinsClient(config)

    def test_queue_id_resolves_to_finished_build(self):
        self.server.build_job.return_value = 123
        self.server.get_queue_item.return_value = {"executable": {"number": 43}}
        self.server.get_build_info.side_effect = [
            {"result": None},
            {"result": "SUCCESS", "url": "https://example.com/job/43/"},
        ]
        with patch("app.tools.jenkins.time.sleep"):
            outcome = self.client.wait_for_build_result(self.client.queue_build())
        self.assertEqual(outcome, {
            "build_number": 43,
            "build_url": "https://example.com/job/43/",
            "result": "SUCCESS",
        })
        self.server.get_build_info.assert_called_with("job", 43)

    def test_cancelled_queue_is_not_treated_as_success(self):
        self.server.get_queue_item.return_value = {"cancelled": True}
        self.assertEqual(
            self.client.wait_for_build_result(123)["result"], "CANCELLED"
        )
