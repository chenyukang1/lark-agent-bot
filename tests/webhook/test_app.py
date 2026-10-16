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
            "phase": "CHECKOUT_COMPLETED",
        }
        for name in ("load_dotenv", "get_config"):
            patcher = patch.object(webhook, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_health_and_build_start_dispatch(self):
        with (
            patch.object(
                webhook, "resolve_codebase", return_value=MagicMock(alias="stage")
            ),
            patch.object(
                webhook, "jenkins_start_callback", new_callable=AsyncMock
            ) as notify,
            TestClient(webhook.app) as client,
        ):
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            response = client.post("/webhook/jenkins/build_start", json=self.payload)
        self.assertEqual(response.status_code, 202)
        notify.assert_awaited_once()
        event = notify.call_args.args[0]
        self.assertEqual(event.job_name, "staging-job")
        self.assertEqual(event.codebase_confg.alias, "stage")
        self.assertEqual(event.build_number, 42)

    def test_failure_dispatch_and_invalid_build_number(self):
        with (
            patch.object(
                webhook, "jenkins_failure_callback", new_callable=AsyncMock
            ) as notify,
            TestClient(webhook.app) as client,
        ):
            self.assertEqual(
                client.post("/webhook/jenkins/build_fail", json=self.payload).status_code, 200
            )
            invalid = dict(self.payload, build_number=0)
            self.assertEqual(
                client.post("/webhook/jenkins/build_fail", json=invalid).status_code, 422
            )
        notify.assert_awaited_once()

    def test_build_start_phase_filter_and_unknown_job(self):
        with (
            patch.object(webhook, "resolve_codebase", return_value=MagicMock(alias="stage")) as resolve,
            patch.object(webhook, "jenkins_start_callback", new_callable=AsyncMock) as notify,
            TestClient(webhook.app) as client,
        ):
            for phase in ("STARTED", "COMPLETED", "FAILED"):
                response = client.post("/webhook/jenkins/build_start", json=dict(self.payload, phase=phase))
                self.assertEqual(response.status_code, 202)
                self.assertFalse(response.json()["analyzing"])
            notify.assert_not_called()
            response = client.post("/webhook/jenkins/build_start", json=dict(self.payload, phase="CHECKOUT_COMPLETED"))
            self.assertEqual(response.status_code, 202)
            self.assertTrue(response.json()["analyzing"])
            notify.assert_awaited_once()
            self.assertEqual(notify.call_args.args[0].phase, "CHECKOUT_COMPLETED")
            notify.reset_mock()
            resolve.side_effect = ValueError("unknown job")
            self.assertEqual(client.post("/webhook/jenkins/build_start", json=self.payload).status_code, 400)
            self.assertEqual(client.post("/webhook/jenkins/build_start", json=dict(self.payload, build_number=0)).status_code, 422)
            notify.assert_not_called()

    def test_uvicorn_uses_migrated_import_path(self):
        with patch("uvicorn.run") as run:
            webhook.run_webhook_server()
        self.assertEqual(run.call_args.args[0], "app.webhook.app:app")
