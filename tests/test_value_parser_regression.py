import unittest

from modules.value_parser import parse_deal_value
from ozbargain_monitor import score_deals


class ValueParserRegressionTests(unittest.TestCase):
    def test_rrp_uses_headline_pack_price_not_unit_price(self):
        result = parse_deal_value({
            "title": "85% off Secret Premium Coonawarra Shiraz 2020 12-Pack $150 ($12.50/Bottle, RRP $1020) Delivered @ Dozen Deals",
            "description": "",
        })

        self.assertEqual(result["deal_price"], 150)
        self.assertEqual(result["savings"], 870)

    def test_term_deposit_thresholds_are_not_savings(self):
        result = parse_deal_value({
            "title": "1 Year New Money Term Deposit Special Rates: 5.70% p.a. on Min. $250,000, 5.45% p.a. on Min. $50,000 @ Police Credit Union",
            "description": "",
        })

        self.assertEqual(result["savings"], 0)

    def test_percent_off_gift_cards_without_face_value_are_not_quantified(self):
        result = parse_deal_value({
            "title": "Digital Gift Card Store: 7% off IKEA eGift Cards @ CommBank Yello",
            "description": "$20, $50, $100, $200, $500 and $1000 denominations available.",
        })

        self.assertEqual(result["savings"], 0)

    def test_spend_get_voucher_counts_reward_not_difference(self):
        result = parse_deal_value({
            "title": "Spend $1000 in 1 Transaction & Get a $250 Voucher for Business Network Member @ IKEA",
            "description": "",
        })

        self.assertEqual(result["deal_price"], 1000)
        self.assertEqual(result["savings"], 250)
        self.assertIn("$250 reward value", result["explanation"])

    def test_tiered_reward_counts_largest_stated_reward_value(self):
        result = parse_deal_value({
            "title": "Join Hospital + Extras or Packaged Cover on Direct Debit, Stay 60 Days, Get $300 (Singles) / $600 (Family) EDR Dollars @ Bupa",
            "description": "",
        })

        self.assertEqual(result["savings"], 600)
        self.assertIn("$600 reward value", result["explanation"])

    def test_reward_matcher_does_not_count_spend_amount(self):
        result = parse_deal_value({
            "title": "Spend $500 and Receive $100 Credit @ Example",
            "description": "",
        })

        self.assertEqual(result["savings"], 100)

    def test_reward_deal_does_not_infer_fake_market_price(self):
        deals = [{
            "title": "Spend $1000 in 1 Transaction & Get a $250 Voucher for Business Network Member @ IKEA",
            "description": "",
            "link": "https://www.ozbargain.com.au/node/1",
            "external_url": "",
            "votes": 0,
            "comments": 0,
            "clicks": 0,
            "expiry_label": "No expiry date listed",
            "categories": ["Home & Garden"],
            "merchant_name": "ikea.com",
        }]

        scored = score_deals(deals)

        self.assertEqual(scored[0]["savings"], 250)
        self.assertEqual(scored[0].get("market_price", 0), 0)
        self.assertEqual(scored[0].get("savings_percent", 0), 0.0)

    def test_high_ticket_rrp_savings_are_not_dropped(self):
        result = parse_deal_value({
            "title": 'Samsung 115" QN90F Mini LED $14,929 (RRP $24,883) @ JB Hi Fi',
            "description": "",
        })

        self.assertEqual(result["deal_price"], 14929)
        self.assertEqual(result["savings"], 9954)

    def test_trade_in_bonus_stacks_with_cart_discount(self):
        result = parse_deal_value({
            "title": "Samsung Galaxy Tab S11 Ultra 256GB Wi-Fi $1099 Less Trade-in (with $550 off in Cart & $450 Trade in Bonus) Delivered @ Samsung",
            "description": "",
        })

        self.assertEqual(result["deal_price"], 1099)
        self.assertEqual(result["savings"], 1000)
        self.assertIn("$550 cart discount", result["explanation"])
        self.assertIn("$450 trade-in bonus", result["explanation"])


if __name__ == "__main__":
    unittest.main()
