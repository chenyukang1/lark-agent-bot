import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.devops.v2.specialists.codebase import CodebaseAgent


class CodebaseOutputTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = CodebaseAgent.__new__(CodebaseAgent)
        self.agent._sub_agent = SimpleNamespace(run=AsyncMock())
        self.payload = json.dumps(
            {
                "project_path": "/unused",
                "git_branch": "main",
                "jenkins_job_name": "test-job",
                "build_number": 42,
                "build_url": "https://example.com/42",
                "duration_ms": 1000,
                "commit_range": "abc1234..def5678",
                "build_errors": "build failed",
                "server_errors": "",
            }
        )
        repository = patch("app.agents.devops.v2.specialists.codebase.GitRepository")
        repository.start()
        self.addCleanup(repository.stop)
        self.report = (
            "## 🚨 Jenkins构建信息\n"
            "- **Job / 构建号**：test-job #42\n\n"
            "## 🔍 代码级根因分析\n编译失败\n\n"
            "## 🛠️ 建议修复方案\n修复代码\n"
            '$$METADATA:{"email": "dev@example.com", "name": "Developer"}$$'
        )

    async def test_removes_preamble_before_report(self):
        for preamble in (
            (
                "Based on my extensive investigation, I now have enough information "
                "to provide my analysis. Here is the final report:\n\n"
            ),
            "好的，以下是分析报告：\n\n",
            "\n\n",
        ):
            with self.subTest(preamble=preamble):
                self.agent._sub_agent.run.return_value = preamble + self.report
                self.assertEqual(
                    await self.agent.codebase_analysis(self.payload), self.report
                )

    async def test_preserves_report_without_preamble(self):
        self.agent._sub_agent.run.return_value = self.report
        self.assertEqual(await self.agent.codebase_analysis(self.payload), self.report)

    async def test_preserves_output_without_report_header(self):
        for content in ("无法完成分析，请检查仓库权限。", ""):
            with self.subTest(content=content):
                self.agent._sub_agent.run.return_value = content
                self.assertEqual(
                    await self.agent.codebase_analysis(self.payload), content
                )
