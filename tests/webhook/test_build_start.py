import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.webhook import app as webhook


class BuildStartWebhookTest(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "job_name": "staging-job",
            "build_number": 42,
            "build_url": "https://example.com/42",
            "phase": "CHECKOUT_COMPLETED",
        }
        self.configs = {
            "stage": SimpleNamespace(alias="stage", jenkins_job_name="staging-job")
        }
        for target in ("app.config.get_config", "app.webhook.app.get_config"):
            patcher = patch(target, return_value={"codebase_configs": self.configs})
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(webhook, "jenkins_start_callback", new_callable=AsyncMock)
        self.callback = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(webhook.app)
        self.addCleanup(self.client.close)

    def test_accepts_configured_job_name_and_alias(self):
        for job_name in ("staging-job", "stage"):
            with self.subTest(job_name=job_name):
                self.callback.reset_mock()
                response = self.client.post(
                    "/webhook/jenkins/build_start",
                    json=dict(self.payload, job_name=job_name),
                )
                self.assertEqual(response.status_code, 202)
                self.assertTrue(response.json()["accepted"])
                self.callback.assert_awaited_once()
                self.assertEqual(self.callback.call_args.args[0].job_name, job_name)

    def test_rejects_unknown_job_without_dispatch(self):
        response = self.client.post(
            "/webhook/jenkins/build_start",
            json=dict(self.payload, job_name="unknown-job"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown-job", response.json()["detail"])
        self.callback.assert_not_called()

    def test_ignores_other_phases_before_checkout_dispatch(self):
        for phase in ("STARTED", "COMPLETED", "FAILED", "UNKNOWN", "", None):
            with self.subTest(phase=phase):
                response = self.client.post(
                    "/webhook/jenkins/build_start",
                    json=dict(self.payload, phase=phase),
                )
                self.assertEqual(response.status_code, 202)
                self.assertTrue(response.json()["accepted"])
                self.assertFalse(response.json()["analyzing"])
                self.callback.assert_not_called()

        without_phase = dict(self.payload)
        without_phase.pop("phase")
        response = self.client.post("/webhook/jenkins/build_start", json=without_phase)
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["analyzing"])
        self.callback.assert_not_called()

        response = self.client.post("/webhook/jenkins/build_start", json=self.payload)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["analyzing"])
        self.callback.assert_awaited_once()
        self.assertEqual(self.callback.call_args.args[0].phase, "CHECKOUT_COMPLETED")

    def test_rejects_ambiguous_job_without_dispatch(self):
        self.configs["other"] = SimpleNamespace(
            alias="other", jenkins_job_name="staging-job"
        )
        response = self.client.post("/webhook/jenkins/build_start", json=self.payload)
        self.assertEqual(response.status_code, 400)
        self.callback.assert_not_called()

    def test_rejects_invalid_payload_without_dispatch(self):
        response = self.client.post(
            "/webhook/jenkins/build_start",
            json=dict(self.payload, build_number=0),
        )
        self.assertEqual(response.status_code, 422)
        self.callback.assert_not_called()
