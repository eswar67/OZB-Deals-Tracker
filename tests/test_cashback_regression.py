import unittest

from modules.email_builder import build_email_html
from modules.price_intel import detect_cashback


class CashbackRegressionTests(unittest.TestCase):
    def test_detect_cashback_flags_known_merchant_without_percentage(self):
        deal = {
            "title": "Amazon Echo Dot $49",
            "description": "",
            "merchant_name": "Amazon",
            "external_url": "https://www.amazon.com.au/example",
        }

        enriched = detect_cashback(deal)

        self.assertEqual(enriched["cashback_platform"], "ShopBack/Cashrewards")
        self.assertEqual(enriched["cashback_pct"], 0.0)
        self.assertIn("shopback.com.au/search", enriched["cashback_url"])

    def test_email_html_renders_cashback_availability_without_percentage(self):
        html = build_email_html([
            {
                "title": "Amazon Echo Dot $49",
                "link": "https://www.ozbargain.com.au/node/1",
                "external_url": "https://www.amazon.com.au/example",
                "merchant_name": "Amazon",
                "score": 8,
                "savings": 50,
                "votes": 100,
                "comments": 20,
                "clicks": 500,
                "cashback_platform": "ShopBack/Cashrewards",
                "cashback_pct": 0.0,
                "cashback_url": "https://www.shopback.com.au/search?query=Amazon",
            }
        ])

        self.assertIn("Cashback likely via ShopBack/Cashrewards", html)
        self.assertNotIn("~0%", html)


if __name__ == "__main__":
    unittest.main()
