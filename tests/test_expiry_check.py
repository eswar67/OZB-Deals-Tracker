"""Tests for OzBargain expiry verification."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import expiry_check

LIVE_PAGE = """
<div class="links"><ul class="links">
<li><span class="nodeexpiry"><i class="fa fa-calendar"></i> 30 Sep </span></li>
</ul></div>
"""

EXPIRED_PAGE = """
<div class="messages node"><ul><li><span class="expired">expired</span></li></ul></div>
<div class="links"><ul class="links">
<li><span class="nodeexpiry expired"><i class="fa fa-calendar"></i> 21 Jul </span></li>
</ul></div>
"""

# Some dead nodes only carry the banner, with no expiry date attached.
BANNER_ONLY_PAGE = '<ul><li><span class="expired">expired</span></li></ul>'


class CheckNodeTests(unittest.TestCase):
    def _check(self, status, html):
        with patch.object(expiry_check, "_fetch", return_value=(status, html)):
            return expiry_check.check_node("123")

    def test_live_node_is_not_expired(self):
        self.assertEqual(self._check(200, LIVE_PAGE), {"expired": False, "expires_on": ""})

    def test_expired_node_reports_date(self):
        self.assertEqual(self._check(200, EXPIRED_PAGE), {"expired": True, "expires_on": "21 Jul"})

    def test_banner_without_date_still_expires(self):
        self.assertEqual(self._check(200, BANNER_ONLY_PAGE), {"expired": True, "expires_on": ""})

    def test_deleted_node_counts_as_expired(self):
        self.assertEqual(self._check(404, ""), {"expired": True, "expires_on": ""})

    def test_unreachable_node_is_undetermined(self):
        # A network failure must never be read as "expired" — that would hide
        # live deals whenever OzBargain rate-limits us.
        self.assertIsNone(self._check(0, ""))
        self.assertIsNone(self._check(503, ""))


class RefreshExpiryTests(unittest.TestCase):
    def test_marks_expired_and_skips_already_dead(self):
        store = {
            "node:1": {"node_id": "1"},
            "node:2": {"node_id": "2"},
            "node:3": {"node_id": "3", "expired": True},  # terminal, never re-checked
        }
        seen = []

        def fake_check(node_id):
            seen.append(node_id)
            return {"expired": node_id == "1", "expires_on": "21 Jul" if node_id == "1" else ""}

        with patch.object(expiry_check, "check_node", side_effect=fake_check):
            counts = expiry_check.refresh_expiry(store)

        self.assertEqual(sorted(seen), ["1", "2"])
        self.assertEqual(counts, {"checked": 2, "expired": 1, "live": 1, "unknown": 0})
        self.assertTrue(store["node:1"]["expired"])
        self.assertEqual(store["node:1"]["expires_on"], "21 Jul")
        self.assertFalse(store["node:2"]["expired"])
        self.assertIn("expiry_checked_at", store["node:2"])

    def test_undetermined_leaves_deal_untouched(self):
        store = {"node:1": {"node_id": "1"}}
        with patch.object(expiry_check, "check_node", return_value=None):
            counts = expiry_check.refresh_expiry(store)
        self.assertEqual(counts["unknown"], 1)
        self.assertNotIn("expired", store["node:1"])

    def test_node_id_falls_back_to_link(self):
        store = {"link:x": {"link": "https://www.ozbargain.com.au/node/962268"}}
        with patch.object(expiry_check, "check_node", return_value={"expired": True, "expires_on": ""}) as chk:
            expiry_check.refresh_expiry(store)
        chk.assert_called_once_with("962268")

    def test_limit_caps_the_workload(self):
        store = {f"node:{i}": {"node_id": str(i)} for i in range(10)}
        with patch.object(expiry_check, "check_node", return_value={"expired": False, "expires_on": ""}):
            counts = expiry_check.refresh_expiry(store, limit=4)
        self.assertEqual(counts["checked"], 4)


if __name__ == "__main__":
    unittest.main()
