import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.webhook import app as webhook


class WebhookTest(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "job_name": "staging-job",
            "build_number": 42,
            "build_url": "https://example.com/42",
        }
        for name in ("load_dotenv", "get_config"):
            patcher = patch.object(webhook, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_health_and_staging_dispatch(self):
        with (
            patch.object(
                webhook, "resolve_codebase", return_value=MagicMock(alias="stage")
            ),
            patch.object(
                webhook, "notify_staging_ddl", new_callable=AsyncMock
            ) as notify,
            TestClient(webhook.app) as client,
        ):
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            response = client.post("/webhook/jenkins/staging", json=self.payload)
        self.assertEqual(response.status_code, 202)
        notify.assert_awaited_once()
        event = notify.call_args.args[0]
        self.assertEqual(event.job_name, "stage")
        self.assertEqual(event.build_number, 42)

    def test_failure_dispatch_and_invalid_build_number(self):
        with (
            patch.object(
                webhook, "notify_jenkins_failure", new_callable=AsyncMock
            ) as notify,
            TestClient(webhook.app) as client,
        ):
            self.assertEqual(
                client.post("/webhook/jenkins/test", json=self.payload).status_code, 200
            )
            invalid = dict(self.payload, build_number=0)
            self.assertEqual(
                client.post("/webhook/jenkins/test", json=invalid).status_code, 422
            )
        notify.assert_awaited_once()

    def test_uvicorn_uses_migrated_import_path(self):
        with patch("uvicorn.run") as run:
            webhook.run_webhook_server()
        self.assertEqual(run.call_args.args[0], "app.webhook.app:app")
