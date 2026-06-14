"""Tiered/weekly-premium health-insurance offers must not report the top slab.

The headline figure in offers like Medibank "join & stay" is only reachable on
the very highest weekly-premium tier, so it should not be treated as a flat
saving. Fixed stated tiers (e.g. $300/$600 single/family) are unaffected.
"""
import unittest
from modules.value_parser import parse_deal_value


class HealthInsuranceSlabTests(unittest.TestCase):
    def test_weekly_premium_slab_in_description_not_taken(self):
        deal = {
            "title": "Join Eligible Medibank Combined Hospital & Extras Cover, Get up to $2,025 Back @ Medibank",
            "description": (
                "Receive a gift card worth up to 6 weeks of your premium. "
                "Single $675, Couple $1,350, Family $2,025 depending on your weekly premium. "
                "Top family tier $2,025 only applies to the highest weekly premium."
            ),
        }
        result = parse_deal_value(deal)
        self.assertLess(result["savings"], 2025,
                        f"weekly-premium slab should not be the headline saving: {result}")

    def test_bare_up_to_ceiling_in_title_not_taken(self):
        # "up to $X" with no fixed-tier restatement is a ceiling, not a saving.
        deal = {"title": "Get up to $2,025 Gift Card on Health Cover @ Medibank", "description": ""}
        result = parse_deal_value(deal)
        self.assertNotEqual(result["savings"], 2025)

    def test_real_medibank_fixed_giftcard_still_counts(self):
        # Real OzBargain title — a concrete fixed bonus is still a saving.
        deal = {"title": "Join Eligible Medibank Combined Hospital & Extras Cover, Stay Til Oct 30, Get Bonus $300 Visa eGift Card @ Finder", "description": ""}
        result = parse_deal_value(deal)
        self.assertEqual(result["savings"], 300)

    def test_up_to_with_fixed_family_tier_still_counts(self):
        # "Up To $600 ... $600 Family or $300 Single" — $600 is a real fixed tier.
        deal = {"title": "Get Up To $600 Gift Card for NIB Health Insurance + 10 Weeks Free Cover (Hospital & Extras $600 Family or $300 Single) @ Econnex", "description": ""}
        result = parse_deal_value(deal)
        self.assertEqual(result["savings"], 600)

    def test_fixed_single_family_tier_unaffected(self):
        # Regression guard: existing fixed-tier behaviour (largest) is preserved.
        deal = {"title": "Join Hospital + Extras or Packaged Cover on Direct Debit, Stay 60 Days, Get $300 (Singles) / $600 (Family) EDR Dollars @ Bupa", "description": ""}
        result = parse_deal_value(deal)
        self.assertEqual(result["savings"], 600)


if __name__ == "__main__":
    unittest.main()
