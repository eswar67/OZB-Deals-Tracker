"""Delta should mean new-or-improved since the last run — not 'all deals'.

Reproduces the bug where empty/unpersisted memory marked every deal as delta,
and verifies the site flags only genuinely new or improved deals.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import modules.deal_memory as dm
import ozbargain_monitor as monitor
from scripts.build_deals_site import deals_from_monitor_run


class DeltaSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._patches = [
            mock.patch.object(dm, "OUTPUT_DIR", base),
            mock.patch.object(dm, "MEMORY_FILE", base / "deal_memory.json"),
            mock.patch.object(dm, "AUDIT_FILE", base / "audit.jsonl"),
            mock.patch.object(dm, "LATEST_AUDIT_FILE", base / "latest.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _deal(self, nid, title, savings, price=0):
        return {"node_id": nid, "title": title, "link": f"https://x/node/{nid}",
                "savings": savings, "deal_price": price, "merchant_name": "Store"}

    def test_unchanged_deal_is_not_delta_next_run(self):
        # Day 1: two deals — both new, both delta, then recorded to memory.
        d1 = [self._deal("1", "Samsung TV Save $500", 500),
              self._deal("2", "Dyson Save $300", 300)]
        dm.annotate_deals(d1)
        rows1, _ = deals_from_monitor_run(d1)
        self.assertEqual(sum(r["is_today_delta"] for r in rows1), 2)  # all new on day 1
        dm.record_run(d1, d1, min_savings=100)

        # Day 2: same two deals unchanged + one brand-new deal.
        d2 = [self._deal("1", "Samsung TV Save $500", 500),
              self._deal("2", "Dyson Save $300", 300),
              self._deal("3", "New Laptop Save $400", 400)]
        dm.annotate_deals(d2)
        rows2, _ = deals_from_monitor_run(d2)
        delta = [r for r in rows2 if r["is_today_delta"]]
        self.assertEqual(len(delta), 1, "only the brand-new deal should be delta")
        self.assertEqual(delta[0]["title"], "New Laptop Save $400")
        self.assertEqual(delta[0]["delta_reason"], "new")

    def test_improved_saving_is_delta(self):
        d1 = [self._deal("1", "Samsung TV", 500)]
        dm.annotate_deals(d1)
        dm.record_run(d1, d1, min_savings=100)

        d2 = [self._deal("1", "Samsung TV", 650)]  # saving improved 500 -> 650
        dm.annotate_deals(d2)
        rows2, _ = deals_from_monitor_run(d2)
        self.assertTrue(rows2[0]["is_today_delta"])
        self.assertEqual(rows2[0]["delta_reason"], "saving_improved")

    def test_dropped_saving_is_not_delta(self):
        d1 = [self._deal("1", "Samsung TV", 500)]
        dm.annotate_deals(d1)
        dm.record_run(d1, d1, min_savings=100)

        d2 = [self._deal("1", "Samsung TV", 400)]  # saving dropped
        dm.annotate_deals(d2)
        rows2, _ = deals_from_monitor_run(d2)
        self.assertFalse(rows2[0]["is_today_delta"])
        self.assertEqual(rows2[0]["delta_reason"], "")

    def test_restored_manual_rerun_delta_is_rendered(self):
        deal = self._deal("1", "Samsung TV", 500)
        deal["is_delta_deal"] = True
        deal["delta_reason"] = "rerun"

        rows, _ = deals_from_monitor_run([deal])

        self.assertTrue(rows[0]["is_today_delta"])
        self.assertEqual(rows[0]["delta_reason"], "rerun")

    def test_restore_previous_site_delta_matches_active_deals(self):
        site = Path(self.tmp.name) / "index.html"
        site.write_text("""
        <script id="deal-data" type="application/json">[
          {"title":"Samsung TV","link":"https://x/node/1","is_today_delta":true,"delta_reason":"new"},
          {"title":"Old Dyson","link":"https://x/node/2","is_today_delta":false,"delta_reason":""}
        ]</script>
        """)
        deals = [self._deal("1", "Samsung TV", 500), self._deal("3", "Laptop", 400)]

        restored = monitor.restore_previous_site_delta(deals, site)

        self.assertEqual(restored, 1)
        self.assertTrue(deals[0]["is_delta_deal"])
        self.assertEqual(deals[0]["delta_reason"], "new")
        self.assertFalse(deals[1].get("is_delta_deal", False))


if __name__ == "__main__":
    unittest.main()
