import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import ozbargain_monitor as monitor


class DefaultMainPipelineTests(unittest.TestCase):
    def test_default_main_avoids_legacy_feeds_and_anthropic(self):
        sample_deal = {
            "title": "Quiet Laptop Deal Save $250 @ Example Store",
            "description": "",
            "link": "https://www.ozbargain.com.au/node/123",
            "external_url": "https://example.com/laptop",
            "pubDate": datetime.now(timezone.utc),
            "votes": 0,
            "comments": 0,
            "clicks": 0,
            "expiry_label": "No expiry date listed",
            "is_expired": False,
            "is_oos": False,
            "categories": ["Computing"],
            "merchant_name": "example.com",
        }

        with patch.object(monitor, "fetch_all_deals", return_value=[sample_deal]), \
             patch.object(monitor, "fetch_financial_deals", side_effect=AssertionError("legacy financial feed called")), \
             patch.object(monitor, "fetch_travel_deals", side_effect=AssertionError("legacy travel feed called")), \
             patch.object(monitor, "fetch_lifestyle_deals", side_effect=AssertionError("legacy lifestyle feed called")), \
             patch.object(monitor.anthropic, "Anthropic", side_effect=AssertionError("Anthropic should be disabled by default")), \
             patch.object(monitor, "get_google_creds", return_value=object()), \
             patch.object(monitor, "record_run") as record_run, \
             patch.object(monitor, "send_gmail_alert") as send_email:
            monitor.main()

        send_email.assert_called_once()
        record_run.assert_called_once()
        sent_deals = send_email.call_args.args[1]
        self.assertEqual(len(sent_deals), 1)
        self.assertEqual(sent_deals[0]["savings"], 250)


if __name__ == "__main__":
    unittest.main()
