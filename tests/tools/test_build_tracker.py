import tempfile
import unittest
from pathlib import Path

from app.tools.build_tracker import BuildTracker


class BuildTrackerTest(unittest.TestCase):
    def test_pending_attempt_survives_new_tracker_and_records_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "builds.sqlite3"
            tracker = BuildTracker(path)
            tracker.record_queued(
                card_message_id="om_1", alias="stage", open_id="ou_1",
                report_content="report", alarm_time="2026-11-01 10:00",
                source_build_number=41, queue_id=123,
            )
            restarted = BuildTracker(path)
            pending = restarted.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["source_build_number"], 41)
            self.assertEqual(pending[0]["queue_id"], 123)

            restarted.record_result(
                "om_1", build_number=43,
                build_url="https://example.com/43/", result="SUCCESS",
            )
            self.assertEqual(restarted.pending()[0]["result"], "SUCCESS")
            restarted.mark_notified("om_1")
            self.assertEqual(restarted.pending(), [])
