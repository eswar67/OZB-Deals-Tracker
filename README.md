# OZB Deals Tracker

OZB Deals Tracker is an AI-powered OzBargain deal-intelligence agent that finds, scores, explains, emails, and publishes high-value Australian deals. It crawls OzBargain deal pages in parallel, filters out expired or out-of-stock items, extracts structured deal data, and focuses on quantified value rather than raw popularity. Its main purpose is to surface genuinely worthwhile opportunities with clear savings, relevance, and confidence signals.

The agent uses deterministic parsing first, then optional AI review where needed. It understands common deal patterns such as was/now pricing, RRP comparisons, explicit savings, cashback, gift cards, vouchers, points bonuses, trade-in bonuses, free bundled items, and combined savings stacks. Recent upgrades let it infer optimal savings when the deal text or comments mention stacked discounts, while avoiding false inflation from repeated descriptions, denomination lists, or alternative offers.

It maintains memory across runs, tracking first seen, last seen, best detected value, and whether a deal has already appeared. This helps identify new finds, repeated opportunities, and deals whose value has improved. Deals are sorted by descending savings within each section so the highest-impact opportunities appear first.

The email output is designed as a concise daily briefing rather than a raw scrape. Deals are grouped into useful sections, including flash or time-sensitive deals at the top, and each item includes practical context such as title, link, estimated value, AI-derived reasoning, score, category, merchant, and preference match.

The public website mirrors the daily deal set and gives users a clean, filterable interface to explore remembered deals by search, category, merchant, savings, and other criteria.

Scheduling is handled primarily through GitHub Actions, with local Mac automation kept as a backup path only if GitHub Actions fails. The intended daily run is once per day at 6:00 PM Australia/Sydney time. The system also publishes the refreshed website through GitHub Pages so the email can link to a live, shareable deal dashboard:

https://eswar67.github.io/OZB-Deals-Tracker/

Overall, this agent is evolving from a scraper into a personal deal analyst: it remembers context, estimates real value, highlights urgency, supports preference-based filtering, and continuously improves its judgement around complex savings structures.
