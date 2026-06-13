import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import ozbargain_monitor as monitor
from scripts.build_deals_site import build, build_from_deals, load_all_memory_deals, load_latest_deals


class DealsSiteTests(unittest.TestCase):
    def test_load_latest_deals_uses_latest_emailed_run_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Path(tmp) / "memory.json"
            memory.write_text(json.dumps({
                "deals": {
                    "old": {
                        "last_title": "Old Deal Save $999 @ Store",
                        "link": "https://www.ozbargain.com.au/node/1",
                        "node_id": "1",
                        "last_savings": 999,
                        "best_savings": 999,
                        "last_emailed_at": "2026-06-05T09:00:00+00:00",
                    },
                    "new": {
                        "last_title": "Samsung TV $999 (Was $1999) @ Store",
                        "link": "https://www.ozbargain.com.au/node/2",
                        "node_id": "2",
                        "last_savings": 1000,
                        "best_savings": 1000,
                        "last_emailed_at": "2026-06-06T09:21:33+00:00",
                    },
                }
            }))

            deals, latest = load_latest_deals(memory)

            self.assertEqual(latest.isoformat(), "2026-06-06T09:21:33+00:00")
            self.assertEqual(len(deals), 1)
            self.assertEqual(deals[0]["category"], "Electronics")

    def test_build_writes_static_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Path(tmp) / "memory.json"
            output = Path(tmp) / "index.html"
            memory.write_text(json.dumps({
                "deals": {
                    "deal": {
                        "last_title": "Dyson Vacuum $499 (Was $799) @ Store",
                        "link": "https://www.ozbargain.com.au/node/3",
                        "node_id": "3",
                        "last_savings": 300,
                        "best_savings": 300,
                        "last_emailed_at": "2026-06-06T09:21:33+00:00",
                    },
                }
            }))

            count, path = build(memory, output)

            html = path.read_text()
            self.assertEqual(count, 1)
            self.assertIn("layout: default", html)
            self.assertIn("Today's best quantified deals", html)
            self.assertIn("Dyson Vacuum", html)
            self.assertIn("deal-data", html)
            self.assertIn("Minimum saving", html)
            self.assertIn("Saved preference presets", html)
            self.assertIn("Flash / time-sensitive deals", html)
            self.assertIn("urgent-strip", html)
            self.assertIn("Top 10 strongest opportunities", html)
            self.assertIn("AI confidence high to low", html)
            self.assertIn("Urgency high to low", html)
            self.assertIn("Agent picks only", html)
            self.assertIn("agentInsight", html)
            self.assertNotIn("Seen at least", html)
            self.assertNotIn("Most seen", html)
            self.assertNotIn("Most emailed", html)
            self.assertNotIn("Emailed only", html)
            self.assertNotIn("First seen", html)
            self.assertNotIn("Node ", html)
            self.assertIn("Hide expired/OOS", html)
            self.assertIn("Watchlist terms", html)
            self.assertIn("detail-drawer", html)
            self.assertIn("category-summary", html)
            self.assertIn("URLSearchParams", html)
            self.assertIn("clear-filters", html)
            self.assertIn("Potential value is AI-derived from deal signals", html)
            self.assertIn("Built with Claude AI Code and OpenAI Codex", html)
            self.assertIn("Deal Assistant", html)
            self.assertIn("chat-panel", html)
            self.assertIn("assistantReply", html)
            self.assertIn("data-chat-prompt", html)
            self.assertIn("AI confidence", html)
            self.assertIn("Today's Delta", html)
            self.assertIn("today-deals", html)
            self.assertIn("All active deals", html)
            self.assertIn("all-active-details", html)

    def test_build_uses_all_memory_deals_for_filtering(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Path(tmp) / "memory.json"
            memory.write_text(json.dumps({
                "deals": {
                    "old": {
                        "last_title": "Old Laptop Save $500 @ Store",
                        "link": "https://www.ozbargain.com.au/node/1",
                        "node_id": "1",
                        "last_savings": 500,
                        "best_savings": 500,
                        "last_seen_at": "2026-06-05T09:00:00+00:00",
                        "last_emailed_at": "2026-06-05T09:00:00+00:00",
                    },
                    "new": {
                        "last_title": "Samsung TV Save $1000 @ Store",
                        "link": "https://www.ozbargain.com.au/node/2",
                        "node_id": "2",
                        "last_savings": 1000,
                        "best_savings": 1000,
                        "last_seen_at": "2026-06-06T09:21:33+00:00",
                        "last_emailed_at": "2026-06-06T09:21:33+00:00",
                    },
                }
            }))
            output = Path(tmp) / "index.html"

            deals, latest = load_all_memory_deals(memory)
            count, path = build(memory, output)

            html = path.read_text()
            self.assertEqual(len(deals), 2)
            self.assertEqual(count, 2)
            self.assertEqual(latest.isoformat(), "2026-06-06T09:21:33+00:00")
            self.assertIn("Old Laptop", html)
            self.assertIn("Samsung TV", html)
            self.assertIn("Savings high to low", html)
            self.assertIn("Today's delta deals", html)
            self.assertIn("No new or improved deals match the current filters.", html)
            self.assertNotIn('"times_seen"', html)
            self.assertNotIn('"email_count"', html)
            self.assertNotIn('"node_id"', html)

    def test_build_from_live_monitor_deals(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "index.html"
            count, path = build_from_deals([
                {
                    "title": "Samsung 115 TV $14929 (RRP $24883) @ JB Hi Fi",
                    "link": "https://www.ozbargain.com.au/node/962268",
                    "node_id": "962268",
                    "merchant_name": "JB Hi-Fi",
                    "savings": 9954,
                    "is_delta_deal": True,
                    "delta_reason": "new",
                }
            ], output)

            html = path.read_text()
            self.assertEqual(count, 1)
            self.assertIn("Samsung 115 TV", html)
            self.assertIn("$9,954", html)
            self.assertIn('"is_today_delta": true', html)
            self.assertIn("New today", html)

    def test_monitor_publish_uses_current_run_deals(self):
        deals = [{
            "title": "Fresh Deal Save $500 @ Store",
            "link": "https://www.ozbargain.com.au/node/5",
            "node_id": "5",
            "savings": 500,
        }]
        build_mock = MagicMock(return_value=(1, Path("docs/index.html")))

        with patch.object(monitor, "ENABLE_SITE_BUILD", True), \
             patch.object(monitor, "ENABLE_SITE_AUTO_PUBLISH", False), \
             patch("scripts.build_deals_site.build_from_deals", build_mock):
            monitor.publish_deals_site(deals)

        build_mock.assert_called_once_with(deals)


if __name__ == "__main__":
    unittest.main()
