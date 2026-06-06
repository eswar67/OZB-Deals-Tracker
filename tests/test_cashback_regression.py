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

    def test_email_html_stays_compact_with_many_deals(self):
        deals = []
        for i in range(80):
            deals.append({
                "title": f"Large Saving Deal {i} Save $250 @ Store",
                "link": f"https://www.ozbargain.com.au/node/{i}",
                "external_url": f"https://example.com/deal-{i}",
                "merchant_name": "Example",
                "score": 10,
                "savings": 250 + i,
                "savings_percent": 20.0,
                "deal_price": 999,
                "market_price": 1249,
                "explanation": "Explicit saving of $250 stated in title",
                "votes": 100,
                "comments": 20,
                "clicks": 0,
                "categories": ["Computing"],
            })

        html = build_email_html(deals, min_savings=200)

        self.assertLess(len(html.encode("utf-8")), 95_000)
        self.assertIn("Large Saving Deal 0", html)
        self.assertIn("Large Saving Deal 79", html)

    def test_email_html_links_summary_and_promotes_time_sensitive_deals(self):
        html = build_email_html([
            {
                "title": "Flash Laptop Save $300 @ Example",
                "link": "https://www.ozbargain.com.au/node/flash",
                "external_url": "https://example.com/flash",
                "merchant_name": "Example",
                "score": 10,
                "savings": 300,
                "explanation": "Explicit saving of $300 stated in title",
                "votes": 0,
                "comments": 0,
                "clicks": 0,
                "categories": ["Computing"],
                "is_flash": True,
            },
            {
                "title": "Regular Laptop Save $250 @ Example",
                "link": "https://www.ozbargain.com.au/node/regular",
                "external_url": "https://example.com/regular",
                "merchant_name": "Example",
                "score": 10,
                "savings": 250,
                "explanation": "Explicit saving of $250 stated in title",
                "votes": 0,
                "comments": 0,
                "clicks": 0,
                "categories": ["Computing"],
                "is_flash": False,
            },
        ], min_savings=200)

        self.assertIn('href="#all-deals"', html)
        self.assertIn('href="#time-sensitive"', html)
        self.assertIn("Potential Value", html)
        self.assertIn("Top Opportunity", html)
        self.assertIn("⚡ Time-sensitive opportunities", html)
        self.assertIn("⚡ Time-sensitive ·", html)
        self.assertIn("potential</span>", html)
        self.assertEqual(html.count("Flash Laptop Save $300"), 1)

    def test_email_html_promotes_watchlist_priority_and_memory_cues(self):
        html = build_email_html([
            {
                "title": "Samsung OLED TV $999 (Was $1999) @ Example",
                "link": "https://www.ozbargain.com.au/node/1",
                "savings": 1000,
                "deal_price": 999,
                "merchant_name": "Example",
                "categories": ["Electrical & Electronics"],
                "relevance_tags": ["👀 Watchlist: samsung"],
                "relevance_score": 50,
                "is_priority_watchlist": True,
                "is_new_deal": True,
                "memory_key": "node:1",
            },
        ], min_savings=200)

        self.assertIn("Watchlist priority", html)
        self.assertIn("View 1 watchlist priority deal", html)
        self.assertIn("New find", html)

    def test_email_html_links_public_deals_site(self):
        html = build_email_html([
            {
                "title": "Samsung OLED TV $999 (Was $1999) @ Example",
                "link": "https://www.ozbargain.com.au/node/1",
                "savings": 1000,
                "merchant_name": "Example",
                "categories": ["Electrical & Electronics"],
            },
        ], min_savings=200, public_deals_url="https://example.com/deals/")

        self.assertIn("Open clean website view", html)
        self.assertIn("https://example.com/deals/", html)


if __name__ == "__main__":
    unittest.main()
