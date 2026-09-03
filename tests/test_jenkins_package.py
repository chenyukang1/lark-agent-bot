import unittest
from unittest.mock import MagicMock, patch

from devopsagents import devops_agent
from devopsagents.config import CodebaseConfig


class JenkinsPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CodebaseConfig(
            alias="staging",
            jenkins_job_name="staging-build",
            jenkins_url="https://jenkins.example.com",
            jenkins_user="user",
            jenkins_token="token",
            project_path="/tmp/project",
            git_branch="main",
            semantics_hit_rule="staging 项目",
        )

    @patch.object(devops_agent, "jenkins")
    def test_triggers_build_once_with_alias_configuration(self, jenkins_module) -> None:
        server = MagicMock()
        server.build_job.return_value = 42
        jenkins_module.Jenkins.return_value = server

        with patch.object(
            devops_agent,
            "DEFAULT_CONFIG",
            {"codebase_configs": {"staging": self.config}},
        ):
            result = devops_agent.trigger_jenkins_build("staging")

        jenkins_module.Jenkins.assert_called_once_with(
            "https://jenkins.example.com", username="user", password="token"
        )
        server.build_job.assert_called_once_with("staging-build")
        self.assertIn("队列 ID：42", result)

    @patch.object(devops_agent, "jenkins")
    def test_returns_error_without_triggering_unknown_alias(
        self, jenkins_module
    ) -> None:
        with patch.object(devops_agent, "DEFAULT_CONFIG", {"codebase_configs": {}}):
            result = devops_agent.trigger_jenkins_build("missing")

        jenkins_module.Jenkins.assert_not_called()
        self.assertIn("未找到别名", result)


if __name__ == "__main__":
    unittest.main()
