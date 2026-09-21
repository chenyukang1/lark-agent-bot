import asyncio
import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks, HTTPException

from devopsagents.agents import ddl_agent
from devopsagents.config import CodebaseConfig
webhook = importlib.import_module("webhook.app")


class BuildChangesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = self.directory.name
        self.config = CodebaseConfig(
            alias="stage", jenkins_job_name="folder/staging", jenkins_url="https://jenkins.example",
            jenkins_user="user", jenkins_token="token", project_path=self.path,
            git_branch="main", semantics_hit_rule="staging",
        )
        self.git("init")
        self.git("config", "user.name", "Alice")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "commit.gpgsign", "false")
        Path(self.path, "User.java").write_text("class User { int id; }\n")
        self.git("add", ".")
        self.git("commit", "-m", "entity")
        self.first = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.path, check=True, text=True, capture_output=True).stdout

    def collect(self, build):
        with patch.object(ddl_agent.jenkins, "Jenkins") as factory:
            factory.return_value.get_build_info.return_value = build
            result = ddl_agent.collect_build_changes(self.config, 42)
            factory.return_value.get_build_info.assert_called_once_with("folder/staging", 42)
            return result

    def test_root_commit_included_and_duplicate_changesets_removed(self):
        item = {"commitId": self.first}
        result = self.collect({"result": "SUCCESS", "changeSet": {"items": [item]}, "changeSets": [{"items": [item]}]})
        self.assertEqual(list(result.commits), [self.first])
        self.assertEqual(result.commits[self.first]["email"], "alice@example.com")
        self.assertIn("User.java", result.commits[self.first]["files"])
        self.assertIn("+class User", result.patches)

    def test_pipeline_includes_sql_in_other_commit_and_ignores_later_head(self):
        Path(self.path, "migration.sql").write_text("CREATE TABLE users (id INT);\n")
        self.git("add", ".")
        self.git("commit", "-m", "sql")
        second = self.git("rev-parse", "HEAD").strip()
        Path(self.path, "unrelated.txt").write_text("not in build")
        self.git("add", ".")
        self.git("commit", "-m", "later")
        result = self.collect({"result": "SUCCESS", "changeSets": [{"items": [{"commitId": self.first}, {"commitId": second}]}]})
        self.assertEqual(len(result.commits), 2)
        self.assertIn("CREATE TABLE", result.patches)
        self.assertNotIn("unrelated.txt", result.patches)

    def test_empty_changes_does_not_fall_back_to_head(self):
        result = self.collect({"result": "SUCCESS", "changeSet": {"items": []}})
        self.assertFalse(result.commits)

    def test_merge_commit_contains_changes_against_first_parent(self):
        branch = self.git("branch", "--show-current").strip()
        self.git("checkout", "-b", "feature")
        Path(self.path, "User.java").write_text("class User { int id; String email; }\n")
        self.git("add", ".")
        self.git("commit", "-m", "add email")
        self.git("checkout", branch)
        self.git("merge", "--no-ff", "feature", "-m", "merge entity")
        merge = self.git("rev-parse", "HEAD").strip()
        result = self.collect({"result": "SUCCESS", "changeSet": {"items": [{"commitId": merge}]}})
        self.assertIn("+class User { int id; String email; }", result.patches)
        self.assertIn("User.java", result.commits[merge]["files"])

    def test_incomplete_failed_missing_or_invalid_changes_are_rejected(self):
        for build in [
            {"building": True}, {"result": "FAILURE"}, {"result": "SUCCESS"},
            {"result": "SUCCESS", "changeSet": {"items": [{"commitId": "--all"}]}},
        ]:
            with self.subTest(build=build), self.assertRaises(ValueError):
                self.collect(build)

    def test_oversized_diff_is_not_silently_truncated(self):
        with patch.object(ddl_agent, "MAX_DIFF_CHARS", 1), self.assertRaises(ValueError):
            self.collect({"result": "SUCCESS", "changeSet": {"items": [{"commitId": self.first}]}})


class StagingNotificationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        webhook._staging_lock = asyncio.Lock()
        webhook._staging_sent.clear()
        webhook._staging_done.clear()
        self.config = MagicMock(alias="stage", jenkins_job_name="staging")
        self.changes = ddl_agent.BuildChanges(
            commits={"a" * 40: {"name": "Alice", "email": "alice@example.com", "files": {"User.java"}}},
            patches="diff",
        )
        self.event = webhook.JenkinsBuildEvent(job_name="stage", build_number=42, build_url="https://jenkins/42")
        self.report = ddl_agent.DDLReport(findings=[ddl_agent.DDLFinding(
            commit_id="a" * 40, file_path="User.java", evidence="+String email;",
            reason="新增持久化字段 email", confidence="high", sql_status="missing",
        )])
        self.mocks = {}
        for name, mock in {
            "resolve_config": MagicMock(return_value=self.config),
            "collect_build_changes": MagicMock(return_value=self.changes),
            "analyze_build": AsyncMock(return_value=self.report),
            "resolve_open_id": MagicMock(return_value="ou_alice"),
            "send_message": MagicMock(),
        }.items():
            patcher = patch.object(webhook, name, mock)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    async def test_private_notification_and_duplicate_callback(self):
        await webhook._notify_staging_ddl(self.event)
        await webhook._notify_staging_ddl(self.event)
        self.mocks["send_message"].assert_called_once()
        payload = self.mocks["send_message"].call_args.args[1]
        self.assertEqual(payload.receive_id_type, "open_id")
        self.assertEqual(payload.receive_id, "ou_alice")
        self.assertIn("检查是否提交sql", json.loads(payload.content)["text"])
        self.mocks["analyze_build"].assert_awaited_once()

    async def test_covered_low_confidence_or_no_findings_do_not_notify(self):
        for findings in [[], [self.report.findings[0].model_copy(update={"sql_status": "covered"})],
                         [self.report.findings[0].model_copy(update={"confidence": "low"})]]:
            webhook._staging_done.clear()
            self.mocks["analyze_build"].return_value = ddl_agent.DDLReport(findings=findings)
            await webhook._notify_staging_ddl(self.event)
        self.mocks["send_message"].assert_not_called()

    async def test_unknown_recipient_is_not_sent_to_group_and_can_retry(self):
        self.mocks["resolve_open_id"].return_value = ""
        await webhook._notify_staging_ddl(self.event)
        self.mocks["send_message"].assert_not_called()
        self.mocks["resolve_open_id"].return_value = "ou_alice"
        await webhook._notify_staging_ddl(self.event)
        self.mocks["send_message"].assert_called_once()

    async def test_failed_send_can_retry(self):
        self.mocks["send_message"].side_effect = [RuntimeError("send failed"), None]
        await webhook._notify_staging_ddl(self.event)
        await webhook._notify_staging_ddl(self.event)
        self.assertEqual(self.mocks["send_message"].call_count, 2)

    async def test_partial_delivery_retries_only_failed_recipient(self):
        self.changes.commits["b" * 40] = {"name": "Bob", "email": "bob@example.com", "files": {"User.java"}}
        self.report.findings.append(self.report.findings[0].model_copy(update={"commit_id": "b" * 40}))
        self.mocks["resolve_open_id"].side_effect = lambda client, name, email: "ou_" + name.lower()
        self.mocks["send_message"].side_effect = [None, RuntimeError("failed"), None]
        await webhook._notify_staging_ddl(self.event)
        await webhook._notify_staging_ddl(self.event)
        self.assertEqual([call.args[1].receive_id for call in self.mocks["send_message"].call_args_list],
                         ["ou_alice", "ou_bob", "ou_bob"])

    async def test_analysis_failure_sends_nothing(self):
        self.mocks["analyze_build"].side_effect = ValueError("invalid model output")
        await webhook._notify_staging_ddl(self.event)
        self.mocks["send_message"].assert_not_called()
        self.assertFalse(webhook._staging_done)

    async def test_endpoint_queues_completed_build_and_ignores_started(self):
        tasks = BackgroundTasks()
        payload = webhook.WebhookPayload(**self.event.model_dump())
        response = await webhook.jenkins_staging_webhook(tasks, payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(tasks.tasks), 1)
        tasks = BackgroundTasks()
        response = await webhook.jenkins_staging_webhook(tasks, payload.model_copy(update={"phase": "STARTED"}))
        self.assertFalse(json.loads(response.body)["analyzing"])
        self.assertFalse(tasks.tasks)

    async def test_endpoint_rejects_unknown_job(self):
        self.mocks["resolve_config"].side_effect = ValueError("unknown job")
        with self.assertRaises(HTTPException) as exc:
            await webhook.jenkins_staging_webhook(BackgroundTasks(), webhook.WebhookPayload(**self.event.model_dump()))
        self.assertEqual(exc.exception.status_code, 400)

    async def test_model_cannot_choose_commit_or_file_outside_build(self):
        finding = self.report.findings[0].model_copy(update={"file_path": "Other.java"})
        with patch.object(ddl_agent, "ChatOpenAI") as model:
            model.return_value.with_structured_output.return_value.ainvoke = AsyncMock(
                return_value=ddl_agent.DDLReport(findings=[finding]))
            with self.assertRaises(ValueError):
                await ddl_agent.analyze_build(self.changes)
