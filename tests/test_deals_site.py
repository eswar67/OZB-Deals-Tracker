import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_deals_site import build, load_latest_deals


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
            self.assertIn("OzBargain Deal Radar", html)
            self.assertIn("Dyson Vacuum", html)


if __name__ == "__main__":
    unittest.main()
