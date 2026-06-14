import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from modules import deal_memory


class DealMemoryTests(unittest.TestCase):
    def test_record_run_updates_memory_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(deal_memory, "OUTPUT_DIR", out), \
                 patch.object(deal_memory, "MEMORY_FILE", out / "deal_memory.json"), \
                 patch.object(deal_memory, "AUDIT_FILE", out / "missed_deal_audit.jsonl"), \
                 patch.object(deal_memory, "LATEST_AUDIT_FILE", out / "latest_missed_deal_audit.json"):

                deals = [
                    {
                        "node_id": "1",
                        "title": "Good Deal Save $250 @ Example",
                        "link": "https://www.ozbargain.com.au/node/1",
                        "savings": 250,
                    },
                    {
                        "node_id": "2",
                        "title": "Small Deal Save $50 @ Example",
                        "link": "https://www.ozbargain.com.au/node/2",
                        "savings": 50,
                    },
                ]

                deal_memory.annotate_deals(deals)
                audit = deal_memory.record_run(deals, [deals[0]], min_savings=200)
                deal_memory.annotate_deals(deals)

                self.assertEqual(audit["emailed"], 1)
                self.assertEqual(audit["reason_counts"]["emailed"], 1)
                self.assertEqual(audit["reason_counts"]["below_savings_threshold"], 1)
                self.assertEqual(deals[0]["times_seen"], 1)
                self.assertFalse(deals[0]["is_new_deal"])
                self.assertFalse(deals[0]["is_delta_deal"])
                self.assertEqual(deals[0]["email_count"], 1)
                self.assertTrue((out / "deal_memory.json").exists())
                self.assertTrue((out / "latest_missed_deal_audit.json").exists())

    def test_delta_recognition_only_realerts_on_improved_savings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(deal_memory, "OUTPUT_DIR", out), \
                 patch.object(deal_memory, "MEMORY_FILE", out / "deal_memory.json"), \
                 patch.object(deal_memory, "AUDIT_FILE", out / "missed_deal_audit.jsonl"), \
                 patch.object(deal_memory, "LATEST_AUDIT_FILE", out / "latest_missed_deal_audit.json"):

                deal = {
                    "node_id": "10",
                    "title": "Phone Deal Save $300 @ Example",
                    "link": "https://www.ozbargain.com.au/node/10",
                    "savings": 300,
                }

                deal_memory.annotate_deals([deal])
                self.assertTrue(deal["is_delta_deal"])
                self.assertEqual(deal["delta_reason"], "new")

                deal_memory.record_run([deal], [deal], min_savings=200)
                repeat = dict(deal)
                deal_memory.annotate_deals([repeat])
                self.assertFalse(repeat["is_delta_deal"])
                self.assertEqual(repeat["delta_reason"], "")

                improved = dict(deal, savings=450)
                deal_memory.annotate_deals([improved])
                self.assertTrue(improved["is_delta_deal"])
                self.assertEqual(improved["delta_reason"], "saving_improved")

    def test_first_email_delta_only_for_recently_seen_deals(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            memory_file = out / "deal_memory.json"
            old_seen = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
            recent_seen = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(timespec="seconds")
            memory_file.write_text(
                """
{
  "version": 1,
  "deals": {
    "node:old": {
      "first_seen_at": "%s",
      "best_savings": 300,
      "email_count": 0
    },
    "node:recent": {
      "first_seen_at": "%s",
      "best_savings": 300,
      "email_count": 0
    }
  }
}
""" % (old_seen, recent_seen)
            )

            with patch.object(deal_memory, "OUTPUT_DIR", out), \
                 patch.object(deal_memory, "MEMORY_FILE", memory_file), \
                 patch.object(deal_memory, "AUDIT_FILE", out / "missed_deal_audit.jsonl"), \
                 patch.object(deal_memory, "LATEST_AUDIT_FILE", out / "latest_missed_deal_audit.json"):

                old_deal = {
                    "node_id": "old",
                    "title": "Old Never Emailed Deal Save $300 @ Example",
                    "link": "https://www.ozbargain.com.au/node/old",
                    "savings": 300,
                }
                recent_deal = {
                    "node_id": "recent",
                    "title": "Recent Never Emailed Deal Save $300 @ Example",
                    "link": "https://www.ozbargain.com.au/node/recent",
                    "savings": 300,
                }

                deal_memory.annotate_deals([old_deal, recent_deal])

                self.assertFalse(old_deal["is_delta_deal"])
                self.assertEqual(old_deal["delta_reason"], "")
                self.assertTrue(recent_deal["is_delta_deal"])
                self.assertEqual(recent_deal["delta_reason"], "first_email")


if __name__ == "__main__":
    unittest.main()
