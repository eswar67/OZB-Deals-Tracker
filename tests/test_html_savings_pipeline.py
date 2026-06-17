import unittest

from ozbargain_monitor import parse_bargain_radar_deals, parse_html_deal_cards, score_deals


HTML_FIXTURE = """
<div class="infscroll" id="is0" data-page="11">
  <div class="node node-ozbdeal node-teaser" id="node961633">
    <div class="n-left">
      <div class="n-vote n-deal inact" data-nid="961633">
        <span class="nvb voteup"><span>10</span></span>
      </div>
    </div>
    <div class="n-right">
      <div class="right">
        <div class="foxshot-container">
          <a href="/goto/961633" title="Go to https://desky.com.au/products/chair"></a>
        </div>
      </div>
      <h2 class="title" data-title="Desky Chair $399 (Was $699) + Free Shipping @ Desky">
        <a href="/node/961633">Desky Chair $399 (Was $699) + Free Shipping @ Desky</a>
      </h2>
      <div class="submitted">on 02/06/2026 - 13:53 <span class="via"><a href="/goto/961633">desky.com.au</a></span></div>
      <div class="content"><p>A full $300 off, with free shipping.</p></div>
      <div class="links"><ul class="links">
        <li><i class="fa fa-comment"></i> 23</li>
        <li><span class="tag"><a href="/cat/home-garden">Home &amp; Garden</a></span></li>
        <li><span class="nodeexpiry">30 Jun <span class="marker">25 days left</span></span></li>
      </ul></div>
    </div>
  </div>
</div>
"""


class HtmlSavingsPipelineTests(unittest.TestCase):
    def test_parse_html_deal_card(self):
        deals = parse_html_deal_cards(HTML_FIXTURE)

        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["node_id"], "961633")
        self.assertEqual(deals[0]["link"], "https://www.ozbargain.com.au/node/961633")
        self.assertEqual(deals[0]["external_url"], "https://desky.com.au/products/chair")
        self.assertEqual(deals[0]["votes"], 10)
        self.assertEqual(deals[0]["comments"], 23)
        self.assertEqual(deals[0]["categories"], ["Home & Garden"])

    def test_savings_threshold_does_not_require_engagement(self):
        deals = [{
            "title": "Quiet Deal Save $250 @ Example Store",
            "description": "",
            "link": "https://www.ozbargain.com.au/node/1",
            "external_url": "",
            "votes": 0,
            "comments": 0,
            "clicks": 0,
            "expiry_label": "No expiry date listed",
            "categories": ["Other"],
            "merchant_name": "example.com",
        }]

        scored = score_deals(deals)

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0]["savings"], 250)
        self.assertEqual(scored[0]["score"], 10)

    def test_was_price_sets_market_price_and_savings_percent(self):
        deals = [{
            "title": "Desky Chair $399 (Was $699) @ Desky",
            "description": "",
            "link": "https://www.ozbargain.com.au/node/2",
            "external_url": "",
            "votes": 0,
            "comments": 0,
            "clicks": 0,
            "expiry_label": "No expiry date listed",
            "categories": ["Home & Garden"],
            "merchant_name": "desky.com.au",
        }]

        scored = score_deals(deals)

        self.assertEqual(scored[0]["savings"], 300)
        self.assertEqual(scored[0]["deal_price"], 399)
        self.assertEqual(scored[0]["market_price"], 699)
        self.assertAlmostEqual(scored[0]["savings_percent"], 42.9)

    def test_parse_bargain_radar_json_deals(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
              {
                "@type": "Product",
                "name": "Dyson V15 Detect $799 (Was $1,199) @ Dyson",
                "url": "/deals/dyson-v15",
                "brand": "Dyson",
                "category": "Home Appliances",
                "description": "Save $400 on Dyson V15"
              }
            ]
          }
          </script>
        </head></html>
        """

        deals = parse_bargain_radar_deals(html)

        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["title"], "Dyson V15 Detect $799 (Was $1,199) @ Dyson")
        self.assertEqual(deals[0]["link"], "https://bargainradar.com.au/deals/dyson-v15")
        self.assertEqual(deals[0]["merchant_name"], "Dyson")
        self.assertEqual(deals[0]["categories"], ["Home Appliances"])
        self.assertEqual(deals[0]["source"], "bargainradar")

    def test_parse_bargain_radar_html_cards(self):
        html = """
        <article class="deal-card" data-deal-id="abc">
          <a href="/deal/sony-headphones">
            <h2 class="deal-title">Sony Headphones $299 (Was $499) @ Sony</h2>
          </a>
          <span class="merchant">Sony Australia</span>
          <span class="category">Electronics</span>
          <p>Deal is active and ready to buy.</p>
        </article>
        """

        deals = parse_bargain_radar_deals(html)

        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["node_id"], "br-html-0")
        self.assertEqual(deals[0]["link"], "https://bargainradar.com.au/deal/sony-headphones")
        self.assertEqual(deals[0]["merchant_name"], "Sony Australia")
        self.assertEqual(deals[0]["categories"], ["Electronics"])
        self.assertFalse(deals[0]["is_expired"])


if __name__ == "__main__":
    unittest.main()
