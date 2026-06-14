"""Tests for price-history tracking in deal_memory."""
import json
import unittest
import tempfile
from pathlib import Path
from unittest import mock

import modules.deal_memory as dm


class PriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        # Redirect module file paths into a temp dir
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

    def _deal(self, price, savings):
        return {
            "node_id": "111",
            "title": "Test Widget",
            "link": "https://x/node/111",
            "deal_price": price,
            "savings": savings,
            "market_price": price + savings,
        }

    def test_history_accumulates_and_tracks_lowest(self):
        # Run 1: price 500
        d1 = self._deal(500, 100)
        dm.annotate_deals([d1])
        dm.record_run([d1], [d1], min_savings=50)

        # Run 2: price drops to 450 (better)
        d2 = self._deal(450, 150)
        dm.annotate_deals([d2])
        self.assertEqual(d2["lowest_price_seen"], 450)
        self.assertTrue(d2["is_lowest_price"])
        dm.record_run([d2], [d2], min_savings=50)

        # Run 3: price rises to 480 — lowest should still be 450
        d3 = self._deal(480, 120)
        dm.annotate_deals([d3])
        self.assertEqual(d3["lowest_price_seen"], 450)
        self.assertFalse(d3["is_lowest_price"])

        mem = json.loads((Path(self.tmp.name) / "deal_memory.json").read_text())
        hist = mem["deals"]["node:111"]["price_history"]
        self.assertEqual([h["deal_price"] for h in hist], [500, 450])

    def test_unchanged_price_does_not_duplicate(self):
        for _ in range(3):
            d = self._deal(300, 80)
            dm.annotate_deals([d])
            dm.record_run([d], [d], min_savings=50)
        mem = json.loads((Path(self.tmp.name) / "deal_memory.json").read_text())
        hist = mem["deals"]["node:111"]["price_history"]
        self.assertEqual(len(hist), 1)

    def test_history_capped_at_60(self):
        for i in range(70):
            d = self._deal(300 + i, 80)  # changing price each run
            dm.annotate_deals([d])
            dm.record_run([d], [d], min_savings=50)
        mem = json.loads((Path(self.tmp.name) / "deal_memory.json").read_text())
        hist = mem["deals"]["node:111"]["price_history"]
        self.assertLessEqual(len(hist), 60)


if __name__ == "__main__":
    unittest.main()
