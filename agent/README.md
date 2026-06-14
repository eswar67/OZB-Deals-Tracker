# Deal Assistant

The Deal Radar assistant runs in two modes.

## 1. Local agent (default, always on)
A fully client-side agentic engine baked into the site by `scripts/build_deals_site.py`.
No API key, no backend, no cost. It does:

- **Intent classification** — search, compare, aggregate, cheapest, price-history,
  hype-check, cashback/effective-price, explain, points-valuation, goal, help.
- **Entity/slot extraction** — price ranges (“under $500”, “between $200 and $800”),
  savings thresholds, categories, merchants, metrics, and points amounts/programs.
- **Tools over the deal data** — filter, rank, aggregate, compare, effective-price,
  points valuation (using your `points_value_per_point_aud` rates), lowest-seen,
  hype-vs-value.
- **Conversation memory** — follow-ups like “compare the top two”, “the cheapest of
  those”, “is the MacBook the lowest price”.
- **Rich answers** — deal chips, side-by-side comparison tables, and effective-price
  breakdowns rendered inline in the chat.

## 2. Generative brain (optional)
For open-ended reasoning, deploy `cloudflare-worker.js` (keeps the Anthropic key
server-side) and set `agent_llm_endpoint` in `user-prefs.json`. The site auto-detects
the endpoint, routes questions to Claude with the live deal context, and **falls back
to the local agent** if the proxy is unavailable. See the header of
`cloudflare-worker.js` for deploy steps.
