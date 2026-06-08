import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import requests

import ozbargain_monitor as monitor


def _deal(link: str, title: str) -> dict:
    return {
        "link": link,
        "node_id": link.rsplit("/", 1)[-1],
        "title": title,
        "pubDate": datetime.now(timezone.utc),
    }


def _page_from_url(url: str) -> int:
    if "?page=" not in url:
        return 0
    return int(url.rsplit("?page=", 1)[1])


class ParallelHtmlCrawlTests(unittest.TestCase):
    def test_fetch_all_deals_processes_parallel_pages_in_order_and_dedupes(self):
        page_items = {
            0: [_deal("https://www.ozbargain.com.au/node/1", "Page 0 deal")],
            1: [
                _deal("https://www.ozbargain.com.au/node/1", "Duplicate deal"),
                _deal("https://www.ozbargain.com.au/node/2", "Page 1 deal"),
            ],
            2: [_deal("https://www.ozbargain.com.au/node/3", "Page 2 deal")],
            3: [],
            4: [],
            5: [],
            6: [],
            7: [_deal("https://www.ozbargain.com.au/node/7", "Fetched but not processed")],
        }

        def fake_fetch_html(url):
            return f"page:{_page_from_url(url)}"

        def fake_parse_html(html):
            return page_items.get(int(html.split(":", 1)[1]), [])

        with patch.object(monitor, "OZB_MAX_PAGES", 10), \
             patch.object(monitor, "OZB_HTML_WORKERS", 3), \
             patch.object(monitor, "fetch_html", side_effect=fake_fetch_html), \
             patch.object(monitor, "parse_html_deal_cards", side_effect=fake_parse_html):
            deals = monitor.fetch_all_deals()

        self.assertEqual([deal["link"] for deal in deals], [
            "https://www.ozbargain.com.au/node/1",
            "https://www.ozbargain.com.au/node/2",
            "https://www.ozbargain.com.au/node/3",
        ])

    def test_fetch_all_deals_retries_page_failures(self):
        calls = {}

        def fake_fetch_html(url):
            page = _page_from_url(url)
            calls[page] = calls.get(page, 0) + 1
            if page == 0 and calls[page] == 1:
                raise RuntimeError("temporary failure")
            return f"page:{page}"

        def fake_parse_html(html):
            page = int(html.split(":", 1)[1])
            if page == 0:
                return [_deal("https://www.ozbargain.com.au/node/1", "Retried deal")]
            return []

        with patch.object(monitor, "OZB_MAX_PAGES", 6), \
             patch.object(monitor, "OZB_HTML_WORKERS", 2), \
             patch.object(monitor, "fetch_html", side_effect=fake_fetch_html), \
             patch.object(monitor, "parse_html_deal_cards", side_effect=fake_parse_html):
            deals = monitor.fetch_all_deals()

        self.assertEqual(len(deals), 1)
        self.assertEqual(calls[0], 2)

    def test_fetch_all_deals_respects_worker_limit(self):
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_fetch_html(url):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return f"page:{_page_from_url(url)}"

        with patch.object(monitor, "OZB_MAX_PAGES", 6), \
             patch.object(monitor, "OZB_HTML_WORKERS", 3), \
             patch.object(monitor, "fetch_html", side_effect=fake_fetch_html), \
             patch.object(monitor, "parse_html_deal_cards", return_value=[]):
            deals = monitor.fetch_all_deals()

        self.assertEqual(deals, [])
        self.assertLessEqual(max_active, 3)
        self.assertGreater(max_active, 1)

    def test_fetch_all_deals_stops_on_first_404_page(self):
        parsed_pages = []

        def fake_fetch_html(url):
            page = _page_from_url(url)
            if page >= 4:
                response = requests.Response()
                response.status_code = 404
                raise requests.HTTPError("404 Client Error", response=response)
            return f"page:{page}"

        def fake_parse_html(html):
            page = int(html.split(":", 1)[1])
            parsed_pages.append(page)
            return [_deal(f"https://www.ozbargain.com.au/node/{page}", f"Page {page} deal")]

        with patch.object(monitor, "OZB_MAX_PAGES", 12), \
             patch.object(monitor, "OZB_HTML_WORKERS", 3), \
             patch.object(monitor, "fetch_html", side_effect=fake_fetch_html), \
             patch.object(monitor, "parse_html_deal_cards", side_effect=fake_parse_html):
            deals = monitor.fetch_all_deals()

        self.assertEqual(parsed_pages, [0, 1, 2, 3])
        self.assertEqual([deal["node_id"] for deal in deals], ["0", "1", "2", "3"])


if __name__ == "__main__":
    unittest.main()
