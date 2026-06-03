"""
modules/email_builder.py
Rich HTML deal card email.

Each card shows:
  - Deal type icon (emoji, derived from title keywords — no image scraping needed)
  - Bold title + merchant badge
  - Savings amount (large, green)
  - 📐 How we calculated this — step-by-step breakdown table
  - 🎯 Score panel — score badge + rubric position + Claude's one-line reason
  - Cashback badge (if detected)
  - StaticICE price (only when a real price was found)
  - Top comment (if enrichment worked)
  - Relevance tags
  - CTA buttons: View Deal + Merchant (+ Cashback if available)
  - Flash Deal banner
Summary header + footer with filter settings
"""

from datetime import datetime, timezone


# ── Deal type icon ────────────────────────────────────────────────────────────

_ICON_RULES = [
    (["credit card", "credit-card"],                              "💳"),
    (["home loan", "mortgage", "refinanc", "offset"],            "🏠"),
    (["savings account", "high interest", "hisa"],               "🏦"),
    (["superannuation", "super fund", "smsf"],                   "🦺"),
    (["share", "etf", "brokerage", "trading", "asx", "invest"], "📈"),
    (["insurance", "cover", "policy", "premium"],                "🛡️"),
    (["loan", "personal loan", "car loan", "finance"],           "💵"),
    (["bank bonus", "bank account", "transaction account"],      "🏦"),
    (["laptop", "macbook", "notebook", "chromebook"],           "💻"),
    (["ipad", "tablet"],                                        "📱"),
    (["iphone", "phone", "samsung galaxy", "pixel"],            "📱"),
    (["tv", "television", "monitor", "oled", "qled"],          "📺"),
    (["headphone", "earphone", "airpod", "earbud", "bose",
      "sony wh", "jbl"],                                        "🎧"),
    (["robot vacuum", "roomba", "vacuum", "dyson"],             "🤖"),
    (["air fryer", "microwave", "oven", "dishwasher",
      "washing machine", "dryer", "fridge", "freezer"],         "🏠"),
    (["coffee machine", "nespresso", "espresso", "grinder"],    "☕"),
    (["flight", "airfare", "hotel", "travel", "airbnb", "holiday",
      "qantas", "virgin australia", "jetstar", "singapore airlines",
      "emirates", "cathay", "united airlines", "thai airways", "lufthansa",
      "fiji airways", "air pacific", "scoot", "airasia", "air asia",
      "korean air", "japan airlines", "eva air", "etihad", "turkish airlines",
      "china southern", "air china", "garuda", "philippine airlines",
      "air new zealand", "malaysia airlines", "royal brunei",
      "return gold coast", "return sydney", "return melbourne",
      "return brisbane", "return perth", "return adelaide",
      " rtn ", "cruise", "holiday package"],                     "✈️"),
    (["gift card", "voucher", "store credit", "eftpos"],        "🎁"),
    (["cashback", "shopback", "cashrewards"],                   "💰"),
    (["points", "qantas", "velocity", "flybuys", "rewards"],    "✈️"),
    (["game", "nintendo", "playstation", "xbox", "steam"],      "🎮"),
    (["camera", "gopro", "lens", "dslr", "mirrorless"],        "📷"),
    (["software", "subscription", "licence", "microsoft",
      "adobe", "vpn"],                                          "💿"),
    (["car", "vehicle", "driveaway", "ute", "suv"],            "🚗"),
    (["solar", "battery", "ev", "electric vehicle"],           "⚡"),
    (["furniture", "mattress", "desk", "chair", "couch"],       "🛋️"),
    (["watch", "smartwatch", "apple watch", "garmin"],          "⌚"),
]

def _deal_icon(title: str) -> str:
    t = title.lower()
    for keywords, icon in _ICON_RULES:
        if any(k in t for k in keywords):
            return icon
    return "🛍️"


# ── Score colour ──────────────────────────────────────────────────────────────

def _score_color(score: int) -> tuple:
    if score >= 9:   return "#1a7f37", "#d4edda", "Excellent"
    elif score >= 7: return "#2da44e", "#e6f4ea", "Great"
    elif score >= 5: return "#bf8700", "#fff8e1", "Good"
    else:            return "#cf222e", "#fdecea", "Fair"


# ── Savings calculation breakdown ─────────────────────────────────────────────

def _savings_breakdown(deal: dict) -> str:
    """Compact single-line savings callout — replaces the old 4-row table."""
    explanation = deal.get("explanation", "")
    savings     = deal.get("savings", 0)

    if not savings:
        return '<div style="font-size:12px;color:#888;margin:6px 0;">Check deal for current pricing</div>'

    calc_html = (
        f'<span style="font-size:11px;color:#555;margin-left:8px;">{explanation}</span>'
        if explanation else ""
    )
    return f"""
<div style="margin:8px 0;display:flex;align-items:baseline;flex-wrap:wrap;gap:4px;">
  <span style="font-size:22px;font-weight:800;color:#1a7f37;">~${savings:,} AUD</span>
  {calc_html}
</div>"""


# ── Score breakdown ───────────────────────────────────────────────────────────

def _score_breakdown(deal: dict) -> str:
    score  = deal.get("score", 0)
    reason = deal.get("score_reason", "")
    bg, light, label = _score_color(score)

    reason_html = (
        f'<span style="font-size:11px;color:#666;font-style:italic;margin-left:8px;">💬 {reason}</span>'
    ) if reason else ""

    return f"""
<div style="margin:10px 0;display:flex;align-items:center;flex-wrap:wrap;gap:6px;">
  <span style="background:{bg};color:#fff;font-size:13px;font-weight:800;
               padding:4px 12px;border-radius:20px;">🎯 {score}/10 {label}</span>
  {reason_html}
</div>"""


# ── Individual deal card ──────────────────────────────────────────────────────

def _deal_card(deal: dict) -> str:
    title      = deal.get("title", "No title")
    ozb_link   = deal.get("link", "#")
    ext_url    = deal.get("external_url", "")
    merchant   = deal.get("merchant_name", "")
    savings    = deal.get("savings", 0)
    score      = deal.get("score", 0)
    votes      = deal.get("votes", 0)
    comments   = deal.get("comments", 0)
    clicks     = deal.get("clicks", 0)
    pub_date   = deal.get("pubDate")
    top_cmts   = deal.get("top_comments", [])
    cats       = deal.get("categories", [])
    cb_plat    = deal.get("cashback_platform", "")
    cb_pct     = deal.get("cashback_pct", 0.0)
    cb_url     = deal.get("cashback_url", "")
    si_lowest  = deal.get("staticice_lowest", 0)
    si_label   = deal.get("staticice_label", "")
    si_url     = deal.get("staticice_url", "")
    rel_tags   = deal.get("relevance_tags", [])
    is_flash   = deal.get("is_flash", False)
    is_expired = deal.get("is_expired", False)

    bg, light, label = _score_color(score)
    icon = _deal_icon(title)

    # Age + freshness badge
    age_str   = ""
    is_new    = False
    if pub_date:
        age_mins = int((datetime.now(timezone.utc) - pub_date).total_seconds() / 60)
        age_str  = f"{age_mins//60}h {age_mins%60}m ago" if age_mins >= 60 else f"{age_mins}m ago"
        is_new   = age_mins < 1440  # posted within last 24 hours

    # Flash banner
    flash_html = (
        '<div style="background:#d73a49;color:#fff;font-size:12px;font-weight:bold;'
        'padding:5px 14px;text-align:center;">⚡ FLASH DEAL — Act Fast!</div>'
    ) if is_flash else ""

    # Merchant badge
    merchant_badge = (
        f'<span style="display:inline-block;background:#f0f0f0;color:#555;'
        f'font-size:11px;padding:2px 8px;border-radius:10px;margin-left:8px;">'
        f'{merchant}</span>'
    ) if merchant else ""

    # Score badge (top-right)
    score_badge = f"""
    <div style="text-align:center;min-width:70px;">
      <div style="background:{bg};color:#fff;font-size:20px;font-weight:800;
                  padding:8px 12px;border-radius:12px;display:inline-block;
                  min-width:50px;">{score}/10</div>
      <div style="font-size:10px;color:{bg};font-weight:700;margin-top:3px;">{label}</div>
    </div>"""

    # Category tags
    cat_tags = "".join(
        f'<span style="background:#e8f0fe;color:#1a73e8;font-size:10px;'
        f'padding:2px 8px;border-radius:10px;margin-right:4px;">{c}</span>'
        for c in cats[:3]
    )

    # Cashback badge
    cb_html = ""
    if cb_plat:
        cb_href = f'href="{cb_url}"' if cb_url else ""
        cb_html = (
            f'<a {cb_href} style="display:inline-block;background:#ff6900;color:#fff;'
            f'font-size:11px;font-weight:700;padding:4px 10px;border-radius:6px;'
            f'text-decoration:none;margin:6px 0;">💰 {cb_plat} ~{cb_pct:.0f}% cashback</a>'
        )

    si_html = ""

    # Market price panel
    market_lowest       = deal.get("market_lowest", 0)
    market_store        = deal.get("market_lowest_store", "")
    market_url          = deal.get("market_lowest_url", "")
    market_alt_stores   = deal.get("market_alt_stores", [])
    market_cheaper      = deal.get("market_cheaper", False)
    market_saving_vs    = deal.get("market_saving_vs_deal", 0)

    si_search_url = deal.get("staticice_url", "")
    si_link = (
        f'<a href="{si_search_url}" style="color:#888;font-size:10px;text-decoration:none;" '
        f'title="Prices sourced from StaticICE — may not reflect current stock or pricing">'
        f'via StaticICE ↗</a>'
    ) if si_search_url else '<span style="color:#888;font-size:10px;">via StaticICE</span>'
    stale_note = (
        f'<span style="color:#999;font-size:10px;margin-left:6px;">'
        f'· prices indicative, verify before purchase</span>'
    )

    market_html = ""
    if market_lowest > 0:
        if market_cheaper:
            # Deal is NOT the cheapest — warn the user
            market_href = f'href="{market_url}"' if market_url else ""
            alt_bits = "".join(
                f'<span style="font-size:11px;color:#666;margin-left:10px;">'
                f'· {a["store"]} ${a["price"]:,}</span>'
                for a in market_alt_stores[:2] if a.get("store")
            )
            market_html = f"""
<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;
            padding:8px 12px;margin:8px 0;font-size:12px;">
  <strong>⚠️ Cheaper available online:</strong>
  <a {market_href} style="color:#856404;font-weight:700;text-decoration:none;">
    {market_store or "another retailer"} — ${market_lowest:,} AUD
  </a>
  <span style="color:#856404;"> (${market_saving_vs:,} less than this deal)</span>
  {alt_bits}
  <br>{si_link}{stale_note}
</div>"""
        else:
            # Market price confirms or improves the deal — show as validation
            # Link to StaticICE search rather than direct store URL (store prices may be stale)
            store_label = market_store or "online"
            store_link = (
                f'<a href="{si_search_url}" style="color:#1a7f37;text-decoration:none;font-weight:700;">{store_label}</a>'
                if si_search_url else f"<strong>{store_label}</strong>"
            )
            alt_bits = "".join(
                f'<span style="font-size:11px;color:#666;margin-left:8px;">'
                f'· {a["store"]} ${a["price"]:,}</span>'
                for a in market_alt_stores[:2] if a.get("store")
            )
            market_html = f"""
<div style="background:#e6f4ea;border:1px solid #a8d5b5;border-radius:6px;
            padding:8px 12px;margin:8px 0;font-size:12px;">
  <strong>🏪 Next cheapest online:</strong> {store_link} — ~${market_lowest:,} AUD
  {alt_bits}
  <br>{si_link}{stale_note}
</div>"""

    # Top comment
    cmt_html = ""
    if top_cmts:
        c = top_cmts[0]
        cmt_html = (
            f'<div style="background:#fffbdd;border-left:3px solid #d4a72c;'
            f'padding:8px 10px;margin:10px 0;border-radius:0 4px 4px 0;font-size:12px;">'
            f'<strong>⚠️ Top comment</strong> '
            f'<span style="color:#888;">({c.get("author","anon")})</span><br>'
            f'<em style="color:#555;">{c.get("text","")[:200]}</em>'
            f'</div>'
        )

    # Relevance tags
    rel_html = ""
    if rel_tags:
        rel_html = (
            '<div style="margin:6px 0;">'
            + "".join(
                f'<span style="display:inline-block;background:#f6f8fa;border:1px solid #d0d7de;'
                f'color:#57606a;font-size:10px;padding:2px 8px;border-radius:10px;margin-right:4px;">'
                f'{tag}</span>'
                for tag in rel_tags[:4]
            )
            + '</div>'
        )

    # CTA buttons
    btn = ("display:inline-block;padding:8px 16px;border-radius:6px;"
           "text-decoration:none;font-size:13px;font-weight:700;margin-right:8px;margin-top:6px;")
    cta_view     = f'<a href="{ozb_link}" style="{btn}background:#e05c00;color:#fff;">🛍 View Deal</a>'
    cta_merchant = f'<a href="{ext_url}" style="{btn}background:#f6f8fa;color:#24292f;border:1px solid #d0d7de;">🏪 Merchant</a>' if ext_url else ""
    cta_cb       = f'<a href="{cb_url}" style="{btn}background:#ff6900;color:#fff;">💰 {cb_plat}</a>' if cb_url else ""

    # Stats bar
    stats = (
        f'<span style="color:#888;font-size:12px;">'
        f'👍 {votes} &nbsp;💬 {comments} &nbsp;👁 {clicks}'
        + (f'&nbsp; ⏰ {age_str}' if age_str else "")
        + '</span>'
    )

    expired_style = "opacity:0.55;" if is_expired else ""

    return f"""
<div style="border:1px solid #d0d7de;border-radius:10px;margin-bottom:18px;
            overflow:hidden;font-family:Arial,sans-serif;{expired_style}">
  {flash_html}
  <div style="padding:16px;display:flex;gap:14px;align-items:flex-start;">

    <!-- Icon -->
    <div style="flex-shrink:0;font-size:42px;width:56px;text-align:center;
                padding-top:4px;">{icon}</div>

    <!-- Main body -->
    <div style="flex:1;min-width:0;">

      <!-- Title -->
      <div style="margin-bottom:6px;">
        {'<span style="background:#0969da;color:#fff;font-size:10px;font-weight:800;padding:2px 7px;border-radius:8px;margin-right:6px;vertical-align:middle;">🆕 NEW</span>' if is_new else ""}
        <a href="{ozb_link}" style="color:#e05c00;font-weight:800;font-size:15px;
           text-decoration:none;line-height:1.4;">{title}</a>
        {merchant_badge}
      </div>

      {f'<div style="margin-bottom:8px;">{cat_tags}</div>' if cat_tags else ""}

      {cb_html}
      {si_html}
      {market_html}

      <!-- Savings breakdown -->
      {_savings_breakdown(deal)}

      <!-- Personal Opportunity Score -->
      {_opportunity_badge(deal)}

      <!-- Trust Score -->
      {_trust_badge(deal)}

      <!-- Score breakdown -->
      {_score_breakdown(deal)}

      {cmt_html}
      {rel_html}

      <!-- CTAs + stats -->
      <div style="margin-top:12px;display:flex;justify-content:space-between;
                  align-items:center;flex-wrap:wrap;gap:8px;">
        <div>{cta_view}{cta_merchant}{cta_cb}</div>
        {stats}
      </div>
    </div>

    <!-- Score badge -->
    {score_badge}
  </div>
</div>"""


# ── Full email ────────────────────────────────────────────────────────────────

def _cc_travel_card(deal: dict) -> str:
    """
    Rich card for Credit Card and Travel deals.
    Shows sub-type badge, points→$ breakdown, and retail comparison.
    """
    title        = deal.get("title", "No title")
    ozb_link     = deal.get("link", "#")
    ext_url      = deal.get("external_url", "")
    savings      = deal.get("savings", 0)
    score        = deal.get("score", 0)
    votes        = deal.get("votes", 0)
    comments     = deal.get("comments", 0)
    clicks       = deal.get("clicks", 0)
    pub_date     = deal.get("pubDate")
    explanation  = deal.get("explanation", "")
    score_reason = deal.get("score_reason", "")
    subtype      = deal.get("deal_subtype", "travel")

    icon = _deal_icon(title)
    bg, light, label = _score_color(score)

    age_str = ""
    is_new  = False
    if pub_date:
        age_mins = int((datetime.now(timezone.utc) - pub_date).total_seconds() / 60)
        age_str  = f"{age_mins//60}h {age_mins%60}m ago" if age_mins >= 60 else f"{age_mins}m ago"
        is_new   = age_mins < 1440

    new_badge = '<span style="background:#0969da;color:#fff;font-size:10px;font-weight:800;padding:2px 7px;border-radius:8px;margin-right:6px;">🆕 NEW</span>' if is_new else ""

    # Sub-type badge
    if subtype == "credit_card":
        badge_bg, badge_text, badge_label = "#4f46e5", "#fff", "💳 Credit Card"
    else:
        badge_bg, badge_text, badge_label = "#0284c7", "#fff", "✈️ Travel"

    subtype_badge = (
        f'<span style="display:inline-block;background:{badge_bg};color:{badge_text};'
        f'font-size:11px;font-weight:700;padding:2px 10px;border-radius:10px;'
        f'margin-bottom:6px;">{badge_label}</span>'
    )

    # Points breakdown — detect points in explanation and show → $ calculation
    points_html = ""
    import re as _re
    pts_match = _re.search(r"([\d,]+)\s*(Qantas|Velocity|qantas|velocity)\s*pts?", explanation, _re.IGNORECASE)
    if pts_match:
        pts_raw   = pts_match.group(1).replace(",", "")
        pts_brand = pts_match.group(2).capitalize()
        try:
            pts       = int(pts_raw)
            cpp       = 0.0135
            pts_value = int(pts * cpp)
            points_html = f"""
<div style="background:#f0f4ff;border:1px solid #c7d2fe;border-radius:6px;
            padding:8px 12px;margin:8px 0;font-size:12px;">
  <strong>✈️ Points Value Breakdown</strong><br>
  <span style="color:#4f46e5;">{pts:,} {pts_brand} points × ${cpp}/pt
  = <strong>${pts_value:,} AUD</strong></span>
  <span style="color:#888;font-size:11px;margin-left:6px;">
    (based on ${cpp}/pt redemption rate)
  </span>
</div>"""
        except ValueError:
            pass

    # Savings panel
    if savings:
        savings_html = (
            f'<div style="font-size:24px;font-weight:800;color:#1a7f37;margin:6px 0;">'
            f'~${savings:,} AUD</div>'
            f'<div style="font-size:12px;color:#555;margin-bottom:4px;">{explanation}</div>'
        )
    else:
        savings_html = '<div style="font-size:12px;color:#888;margin:6px 0 4px;">Value not quantified — check deal</div>'

    # Score line
    score_html = (
        f'<span style="background:{bg};color:#fff;font-size:12px;font-weight:700;'
        f'padding:2px 8px;border-radius:8px;">{score}/10 {label}</span>'
        + (f'<span style="font-size:11px;color:#666;margin-left:8px;font-style:italic;">'
           f'💬 {score_reason}</span>' if score_reason else "")
    )

    btn = ("display:inline-block;padding:7px 14px;border-radius:6px;"
           "text-decoration:none;font-size:13px;font-weight:700;margin-right:8px;margin-top:6px;")
    cta_view     = f'<a href="{ozb_link}" style="{btn}background:{badge_bg};color:#fff;">View Deal</a>'
    cta_merchant = f'<a href="{ext_url}" style="{btn}background:#f6f8fa;color:#24292f;border:1px solid #d0d7de;">Go to Offer</a>' if ext_url else ""

    stats = (
        f'<span style="color:#888;font-size:12px;">👍 {votes} &nbsp;💬 {comments} &nbsp;👁 {clicks}'
        + (f'&nbsp; ⏰ {age_str}' if age_str else "")
        + '</span>'
    )

    return f"""
<div style="border:1px solid #c7d2fe;border-radius:10px;margin-bottom:14px;
            overflow:hidden;font-family:Arial,sans-serif;background:#fafafa;">
  <div style="padding:14px 16px;display:flex;gap:12px;align-items:flex-start;">
    <div style="flex-shrink:0;font-size:36px;width:48px;text-align:center;padding-top:2px;">{icon}</div>
    <div style="flex:1;min-width:0;">
      {subtype_badge}
      <div style="margin-bottom:4px;">
        {new_badge}<a href="{ozb_link}" style="color:#1e1b4b;font-weight:800;font-size:14px;
           text-decoration:none;line-height:1.4;">{title}</a>
      </div>
      {savings_html}
      {points_html}
      {_opportunity_badge(deal)}
      {_trust_badge(deal)}
      <div style="margin-bottom:8px;">{score_html}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div>{cta_view}{cta_merchant}</div>
        {stats}
      </div>
    </div>
  </div>
</div>"""


def _financial_card(deal: dict) -> str:
    """Compact card for financial deals — same layout, green accent."""
    title      = deal.get("title", "No title")
    ozb_link   = deal.get("link", "#")
    ext_url    = deal.get("external_url", "")
    savings    = deal.get("savings", 0)
    score      = deal.get("score", 0)
    votes      = deal.get("votes", 0)
    comments   = deal.get("comments", 0)
    clicks     = deal.get("clicks", 0)
    pub_date   = deal.get("pubDate")
    explanation= deal.get("explanation", "")
    score_reason = deal.get("score_reason", "")

    icon = _deal_icon(title)

    age_str = ""
    is_new  = False
    if pub_date:
        age_mins = int((datetime.now(timezone.utc) - pub_date).total_seconds() / 60)
        age_str  = f"{age_mins//60}h {age_mins%60}m ago" if age_mins >= 60 else f"{age_mins}m ago"
        is_new   = age_mins < 1440

    new_badge = '<span style="background:#0969da;color:#fff;font-size:10px;font-weight:800;padding:2px 7px;border-radius:8px;margin-right:6px;">🆕 NEW</span>' if is_new else ""

    bg, light, label = _score_color(score)

    savings_html = (
        f'<div style="font-size:22px;font-weight:800;color:#1a7f37;margin:6px 0;">'
        f'~${savings:,} AUD</div>'
        f'<div style="font-size:12px;color:#555;margin-bottom:8px;">{explanation}</div>'
    ) if savings else (
        '<div style="font-size:12px;color:#888;margin:6px 0 8px;">Value not quantified — check deal</div>'
    )

    score_html = (
        f'<span style="background:{bg};color:#fff;font-size:12px;font-weight:700;'
        f'padding:2px 8px;border-radius:8px;">{score}/10</span>'
        + (f'<span style="font-size:11px;color:#666;margin-left:8px;font-style:italic;">{score_reason}</span>' if score_reason else "")
    )

    btn = ("display:inline-block;padding:7px 14px;border-radius:6px;"
           "text-decoration:none;font-size:13px;font-weight:700;margin-right:8px;margin-top:6px;")
    cta_view     = f'<a href="{ozb_link}" style="{btn}background:#1a7f37;color:#fff;">💳 View Deal</a>'
    cta_merchant = f'<a href="{ext_url}" style="{btn}background:#f6f8fa;color:#24292f;border:1px solid #d0d7de;">🏦 Go to Offer</a>' if ext_url else ""

    stats = (
        f'<span style="color:#888;font-size:12px;">👍 {votes} &nbsp;💬 {comments} &nbsp;👁 {clicks}'
        + (f'&nbsp; ⏰ {age_str}' if age_str else "")
        + '</span>'
    )

    return f"""
<div style="border:1px solid #c6e6d0;border-radius:10px;margin-bottom:14px;
            overflow:hidden;font-family:Arial,sans-serif;background:#f6fbf7;">
  <div style="padding:14px 16px;display:flex;gap:12px;align-items:flex-start;">
    <div style="flex-shrink:0;font-size:36px;width:48px;text-align:center;padding-top:2px;">{icon}</div>
    <div style="flex:1;min-width:0;">
      {new_badge}<a href="{ozb_link}" style="color:#1a7f37;font-weight:800;font-size:14px;
         text-decoration:none;line-height:1.4;">{title}</a>
      {savings_html}
      {_opportunity_badge(deal)}
      <div style="margin-bottom:8px;">{score_html}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div>{cta_view}{cta_merchant}</div>
        {stats}
      </div>
    </div>
  </div>
</div>"""


def _lifestyle_card(deal: dict, accent_color: str = "#e67e22") -> str:
    """Compact card for Food/Grocery and Home/Appliance deals."""
    title        = deal.get("title", "No title")
    ozb_link     = deal.get("link", "#")
    ext_url      = deal.get("external_url", "")
    savings      = deal.get("savings", 0)
    score        = deal.get("score", 0)
    votes        = deal.get("votes", 0)
    comments     = deal.get("comments", 0)
    clicks       = deal.get("clicks", 0)
    pub_date     = deal.get("pubDate")
    explanation  = deal.get("explanation", "")
    score_reason = deal.get("score_reason", "")

    icon = _deal_icon(title)
    bg, light, label = _score_color(score)

    age_str = ""
    if pub_date:
        age_mins = int((datetime.now(timezone.utc) - pub_date).total_seconds() / 60)
        age_str = f"{age_mins//60}h {age_mins%60}m ago" if age_mins >= 60 else f"{age_mins}m ago"

    savings_html = (
        f'<div style="font-size:20px;font-weight:800;color:#1a7f37;margin:5px 0;">'
        f'~${savings:,} AUD</div>'
        f'<div style="font-size:12px;color:#555;margin-bottom:6px;">{explanation}</div>'
    ) if savings else (
        '<div style="font-size:12px;color:#888;margin:5px 0 6px;">Check deal for pricing</div>'
    )

    score_html = (
        f'<span style="background:{bg};color:#fff;font-size:12px;font-weight:700;'
        f'padding:2px 8px;border-radius:8px;">{score}/10</span>'
        + (f'<span style="font-size:11px;color:#666;margin-left:8px;font-style:italic;">'
           f'💬 {score_reason}</span>' if score_reason else "")
    )

    btn = ("display:inline-block;padding:7px 14px;border-radius:6px;"
           "text-decoration:none;font-size:13px;font-weight:700;margin-right:8px;margin-top:6px;")
    cta_view     = f'<a href="{ozb_link}" style="{btn}background:{accent_color};color:#fff;">View Deal</a>'
    cta_merchant = (
        f'<a href="{ext_url}" style="{btn}background:#f6f8fa;color:#24292f;border:1px solid #d0d7de;">Go to Offer</a>'
    ) if ext_url else ""

    stats = (
        f'<span style="color:#888;font-size:12px;">👍 {votes} &nbsp;💬 {comments} &nbsp;👁 {clicks}'
        + (f'&nbsp; ⏰ {age_str}' if age_str else "")
        + '</span>'
    )

    return f"""
<div style="border:1px solid #ffe0b2;border-radius:10px;margin-bottom:14px;
            overflow:hidden;font-family:Arial,sans-serif;background:#fffaf5;">
  <div style="padding:14px 16px;display:flex;gap:12px;align-items:flex-start;">
    <div style="flex-shrink:0;font-size:36px;width:48px;text-align:center;padding-top:2px;">{icon}</div>
    <div style="flex:1;min-width:0;">
      <a href="{ozb_link}" style="color:{accent_color};font-weight:800;font-size:14px;
         text-decoration:none;line-height:1.4;">{title}</a>
      {savings_html}
      {_opportunity_badge(deal)}
      <div style="margin-bottom:8px;">{score_html}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div>{cta_view}{cta_merchant}</div>
        {stats}
      </div>
    </div>
  </div>
</div>"""


def _opportunity_badge(deal: dict) -> str:
    """Compact personal opportunity score + tier badge for any card."""
    opp = deal.get("opportunity_score")
    if opp is None:
        return ""
    tier = deal.get("tier", "3_ignore")
    ev   = deal.get("expected_value", 0)
    ev_note = deal.get("ev_note", "")

    if tier == "1_action":
        bg, color, icon = "#d73a49", "#fff", "🔴"
    elif tier == "2_watch":
        bg, color, icon = "#bf8700", "#fff", "🟡"
    else:
        bg, color, icon = "#6e7781", "#fff", "⚪"

    reasons_html = ""
    reasons = deal.get("personal_reasons", [])
    if reasons:
        reasons_html = (
            '<div style="font-size:10px;color:#555;margin-top:3px;">'
            + " &nbsp;·&nbsp; ".join(reasons[:2])
            + "</div>"
        )

    stacking = deal.get("stacking_hint", "")
    stacking_html = (
        f'<div style="font-size:10px;color:#4f46e5;margin-top:3px;">⚡ Stack: {stacking}</div>'
        if stacking else ""
    )

    quality = deal.get("deal_quality_label", "")
    quality_html = (
        f'<div style="font-size:10px;color:#1a7f37;font-weight:700;margin-top:3px;">📊 {quality}</div>'
        if quality else ""
    )

    flight = deal.get("flight_intel", {})
    flight_html = ""
    if flight and flight.get("best_path"):
        flight_html = (
            f'<div style="font-size:10px;color:#0969da;margin-top:3px;">'
            f'✈️ {flight["best_path"]}</div>'
            f'<div style="font-size:10px;font-weight:700;color:#d73a49;margin-top:2px;">'
            f'{flight.get("verdict","")}</div>'
        )

    ev_html = ""
    if ev > 0 and ev_note:
        ev_html = (
            f'<div style="font-size:10px;color:#555;margin-top:3px;">'
            f'💡 Expected value: <strong style="color:#1a7f37;">${ev:,}</strong> — {ev_note}</div>'
        )

    return f"""
<div style="background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;
            padding:8px 10px;margin:8px 0 4px 0;">
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="background:{bg};color:{color};font-size:11px;font-weight:800;
                 padding:2px 8px;border-radius:10px;">{icon} Opportunity {opp}/100</span>
    <span style="font-size:11px;color:#444;font-weight:600;">{deal.get("tier_label","")}</span>
  </div>
  {ev_html}
  {reasons_html}
  {quality_html}
  {stacking_html}
  {flight_html}
</div>"""




def _life_events_section(alerts: list) -> str:
    if not alerts:
        return ""
    rows = ""
    for a in alerts:
        icon      = a.get("urgency_icon", "🔵")
        value_str = f'<span style="color:#1a7f37;font-weight:700;">~${a["estimated_value"]:,} saving</span>' if a.get("estimated_value") else ""
        lines_html = "".join(
            f'<div style="font-size:11px;color:#555;margin-top:2px;">• {l}</div>'
            for l in a.get("detail_lines", [])[:3] if l
        )
        action_html = (
            f'<div style="font-size:11px;color:#0969da;margin-top:4px;font-style:italic;">'
            f'→ {a["action"][:140]}</div>'
        ) if a.get("action") else ""
        # Negotiation script — collapsed details block
        script = a.get("script", "")
        script_html = ""
        if script:
            safe = script.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>")
            script_html = (
                f'<details style="margin-top:6px;">'
                f'<summary style="font-size:11px;color:#0969da;cursor:pointer;font-weight:700;">'
                f'📋 View negotiation script</summary>'
                f'<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;'
                f'padding:10px;margin-top:6px;font-size:11px;color:#1e3a5f;'
                f'font-family:monospace;white-space:pre-wrap;line-height:1.5;">{safe}</div>'
                f'</details>'
            )
        rows += f"""
<div style="border-bottom:1px solid #fee2e2;padding:10px 0;{'background:#fff8f8;' if a.get('urgency')=='immediate' else ''}">
  <div style="font-weight:700;font-size:13px;">{icon} {a['headline']}</div>
  {lines_html}
  {action_html}
  {script_html}
  <div style="margin-top:4px;">{value_str}
    <span style="font-size:10px;color:#888;margin-left:8px;">{a['days_until']} days away</span>
  </div>
</div>"""
    return f"""
  <!-- Life Events section -->
  <div style="background:#fff5f5;border:2px solid #fca5a5;border-radius:10px;
              padding:14px 18px;margin-bottom:16px;">
    <div style="font-size:15px;font-weight:800;color:#dc2626;margin-bottom:2px;">
      📅 Life Events — Action Required
    </div>
    <div style="font-size:11px;color:#888;margin-bottom:10px;">
      Upcoming events that create financial opportunities
    </div>
    {rows}
  </div>"""


def _money_audit_section(opps: list) -> str:
    if not opps:
        return ""
    total = sum(o.get("estimated_value", 0) for o in opps)
    rows = ""
    for o in opps[:5]:
        icon = o.get("urgency_icon", "🔵")
        lines_html = "".join(
            f'<div style="font-size:11px;color:#555;margin-top:2px;">• {l}</div>'
            for l in o.get("detail_lines", [])[:3] if l
        )
        action_html = (
            f'<div style="font-size:11px;color:#0969da;margin-top:4px;font-style:italic;">'
            f'→ {o["action"][:140]}</div>'
        ) if o.get("action") else ""
        rows += f"""
<div style="border-bottom:1px solid #fde68a;padding:10px 0;">
  <div style="font-weight:700;font-size:13px;">{o['headline']}</div>
  {lines_html}
  {action_html}
  <div style="font-size:11px;color:#92400e;font-weight:700;margin-top:4px;">
    Est. value: ~${o.get('estimated_value',0):,} AUD
  </div>
</div>"""
    return f"""
  <!-- Money Audit section -->
  <div style="background:#fffbeb;border:2px solid #fbbf24;border-radius:10px;
              padding:14px 18px;margin-bottom:16px;">
    <div style="font-size:15px;font-weight:800;color:#92400e;margin-bottom:2px;">
      💸 Money Left on the Table — ~${total:,} AUD
    </div>
    <div style="font-size:11px;color:#888;margin-bottom:10px;">
      Financial opportunities you're currently missing
    </div>
    {rows}
  </div>"""


def _travel_arb_section(routes: list) -> str:
    if not routes:
        return ""
    rows = ""
    for r in routes:
        best = r.get("best") or {}
        cabin_label = r.get("cabin", "").replace("_", " ").title()
        verdict = r.get("verdict", "")

        opts_html = ""
        for opt in r.get("program_options", [])[:4]:
            bar_color = "#1a7f37" if opt["recommended"] and opt["can_afford"] else \
                        "#bf8700" if opt["can_afford"] else "#d0d7de"
            opts_html += f"""
<div style="display:flex;align-items:baseline;gap:8px;margin:3px 0;font-size:11px;">
  <span style="min-width:90px;font-weight:600;color:#333;">{opt['label']}</span>
  <span style="color:#555;">{opt['total_cost_str']}</span>
  <span style="color:{bar_color};font-weight:700;">{opt['cpp']:.2f}¢/pt</span>
  <span style="color:#888;font-size:10px;">{opt['verdict_line']}</span>
</div>"""

        rows += f"""
<div style="border-bottom:1px solid #bfdbfe;padding:10px 0;">
  <div style="font-weight:800;font-size:13px;color:#1e3a8a;">
    ✈️ {r['label']} — {cabin_label} × {r['pax']}pax
  </div>
  <div style="font-size:11px;color:#555;margin:3px 0;">
    Cash fare: ~${r['cash_total']:,} AUD
  </div>
  {opts_html}
  <div style="font-size:12px;font-weight:700;color:#1e3a8a;margin-top:6px;">{verdict}</div>
</div>"""

    return f"""
  <!-- Travel Arbitrage section -->
  <div style="background:#eff6ff;border:2px solid #93c5fd;border-radius:10px;
              padding:14px 18px;margin-bottom:16px;">
    <div style="font-size:15px;font-weight:800;color:#1e3a8a;margin-bottom:2px;">
      ✈️ Travel Arbitrage — Best Redemption Today
    </div>
    <div style="font-size:11px;color:#888;margin-bottom:10px;">
      Cash vs points across all your programs · CPP = cents per point
    </div>
    {rows}
  </div>"""


def _trust_badge(deal: dict) -> str:
    """Compact trust % widget shown on every deal card."""
    trust = deal.get("trust_pct", 0)
    barriers = deal.get("trust_barriers", [])
    if not trust:
        return ""
    if trust >= 80:
        color, label = "#1a7f37", "High Trust"
    elif trust >= 50:
        color, label = "#bf8700", "Moderate"
    else:
        color, label = "#d73a49", "Low Trust"
    barrier_html = ""
    if barriers:
        barrier_html = (
            '<span style="font-size:10px;color:#555;margin-left:8px;">'
            + " · ".join(f"⚠️ {b}" for b in barriers[:2])
            + "</span>"
        )
    return (
        f'<div style="margin:4px 0;display:flex;align-items:center;flex-wrap:wrap;gap:4px;">'
        f'<span style="background:{color};color:#fff;font-size:10px;font-weight:700;'
        f'padding:2px 8px;border-radius:8px;">🔐 Trust {trust}% — {label}</span>'
        f'{barrier_html}</div>'
    )


def _briefing_section(briefing: dict) -> str:
    """Morning briefing executive summary card."""
    if not briefing or not briefing.get("actions"):
        return ""
    actions = briefing["actions"]
    rows = ""
    for i, a in enumerate(actions, 1):
        script_note = ' <span style="font-size:10px;color:#0969da;">📋 Script ready</span>' if a.get("has_script") else ""
        rows += (
            f'<div style="display:flex;align-items:baseline;gap:10px;padding:6px 0;'
            f'border-bottom:1px solid #f0fdf4;">'
            f'<span style="font-size:14px;font-weight:800;color:#1a7f37;min-width:18px;">#{i}</span>'
            f'<div style="flex:1;">'
            f'<span style="font-weight:700;font-size:12px;">{a["icon"]} {a["title"]}</span>'
            f'{script_note}'
            f'<div style="font-size:10px;color:#666;margin-top:1px;">{a["one_liner"]}</div>'
            f'</div>'
            f'<span style="font-size:12px;font-weight:800;color:#1a7f37;white-space:nowrap;">'
            f'~${a["value"]:,}</span>'
            f'</div>'
        )
    return f"""
  <!-- Morning Briefing -->
  <div style="background:linear-gradient(135deg,#f0fdf4,#dcfce7);border:2px solid #86efac;
              border-radius:10px;padding:16px 20px;margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">
      <div>
        <div style="font-size:17px;font-weight:800;color:#14532d;">
          ☀️ {briefing.get('date','')} — {briefing['action_count']} action(s) today
        </div>
        <div style="font-size:11px;color:#166534;margin-top:2px;">
          ~${briefing['total_value']:,} total value &nbsp;·&nbsp; est. {briefing['total_minutes']} min
        </div>
      </div>
    </div>
    {rows}
  </div>"""


def build_email_html(
    deals: list[dict],
    financial_deals: list[dict] = None,
    cc_travel_deals: list[dict] = None,
    food_deals: list[dict] = None,
    home_deals: list[dict] = None,
    min_score: int = 7,
    min_savings: int = 500,
    min_votes: int = 30,
    min_comments: int = 10,
    min_clicks: int = 200,
    max_age_hours: int = 24,
    fin_min_savings: int = 200,
    travel_min_savings: int = 200,
    life_event_alerts: list = None,
    money_audit: list = None,
    travel_arb: list = None,
    extra_deals: list = None,
    briefing: dict = None,
) -> str:
    financial_deals   = financial_deals   or []
    cc_travel_deals   = cc_travel_deals   or []
    food_deals        = food_deals        or []
    home_deals        = home_deals        or []
    extra_deals       = extra_deals       or []
    life_event_alerts = life_event_alerts or []
    money_audit       = money_audit       or []
    travel_arb        = travel_arb        or []
    briefing          = briefing          or {}
    total_savings = sum(d.get("savings", 0) for d in deals)
    flash_count   = sum(1 for d in deals if d.get("is_flash"))
    now_str       = datetime.now().strftime("%d %b %Y %H:%M AEST")

    LIFESTYLE_TOP_N = 5

    # Sort by opportunity_score (personal) first, then flash, then generic score
    def _sort_key(d):
        return (d.get("opportunity_score", 0), d.get("is_flash", False), d.get("score", 0), d.get("savings", 0))

    sorted_deals = sorted(deals, key=_sort_key, reverse=True)
    cards = "\n".join(_deal_card(d) for d in sorted_deals)

    flash_note = (
        f'&nbsp;·&nbsp;<span style="color:#d73a49;font-weight:700;">'
        f'⚡ {flash_count} flash deal(s)</span>'
    ) if flash_count else ""

    fin_note = (
        f'&nbsp;·&nbsp;<span style="color:#1a7f37;font-weight:700;">'
        f'🏦 {len(financial_deals)} banking deal(s)</span>'
    ) if financial_deals else ""

    cct_note = (
        f'&nbsp;·&nbsp;<span style="color:#4f46e5;font-weight:700;">'
        f'💳✈️ {len(cc_travel_deals)} CC/travel deal(s)</span>'
    ) if cc_travel_deals else ""

    food_note = (
        f'&nbsp;·&nbsp;<span style="color:#e67e22;font-weight:700;">'
        f'🍎 {len(food_deals)} food deal(s)</span>'
    ) if food_deals else ""

    home_note = (
        f'&nbsp;·&nbsp;<span style="color:#8e44ad;font-weight:700;">'
        f'🏠 {len(home_deals)} home deal(s)</span>'
    ) if home_deals else ""

    all_savings = sum(
        d.get("savings", 0)
        for d in deals + financial_deals + cc_travel_deals + food_deals + home_deals + extra_deals
    )
    briefing_html        = _briefing_section(briefing)
    life_events_html     = _life_events_section(life_event_alerts)
    money_audit_html     = _money_audit_section(money_audit)
    travel_arb_html      = _travel_arb_section(travel_arb)

    # ── Tier 1 "Act Now" callout section ───────────────────────────────────────
    all_flat = deals + financial_deals + cc_travel_deals + food_deals + home_deals
    tier1_deals = sorted(
        [d for d in all_flat if d.get("tier") == "1_action"],
        key=lambda d: d.get("opportunity_score", 0), reverse=True
    )
    if tier1_deals:
        t1_items = "".join(
            f'<div style="padding:6px 0;border-bottom:1px solid #fecaca;">'
            f'<span style="font-weight:700;color:#1a1a1a;">{d.get("title","")[:70]}</span>'
            f'<br><span style="font-size:11px;color:#555;">'
            f'Score {d.get("opportunity_score",0)}/100 · '
            f'Expected value ${d.get("expected_value",0):,} · '
            f'{d.get("ev_note","")}'
            f'</span></div>'
            for d in tier1_deals[:5]
        )
        tier1_section = f"""
  <!-- Tier 1 Act Now callout -->
  <div style="background:#fff5f5;border:2px solid #d73a49;border-radius:10px;
              padding:14px 18px;margin-bottom:18px;">
    <div style="font-size:16px;font-weight:800;color:#d73a49;margin-bottom:8px;">
      🔴 Act Now — Top {len(tier1_deals)} Personal Opportunity Deal(s)
    </div>
    {t1_items}
  </div>"""
    else:
        tier1_section = ""

    # Financial (banking) section
    if financial_deals:
        sorted_fin = sorted(
            financial_deals,
            key=lambda d: (d.get("opportunity_score", 0), d.get("savings", 0), d.get("score", 0)),
            reverse=True,
        )
        fin_cards = "\n".join(_financial_card(d) for d in sorted_fin)
        fin_section = f"""
  <!-- Banking/financial deals section -->
  <div style="margin-top:24px;">
    <div style="background:linear-gradient(135deg,#1a7f37,#116329);border-radius:10px 10px 0 0;
                padding:14px 20px;color:#fff;">
      <div style="font-size:17px;font-weight:800;">🏦 Banking &amp; Financial Deals</div>
      <div style="font-size:11px;opacity:0.85;margin-top:2px;">
        {len(financial_deals)} deal(s) · savings accounts, home loans, trading bonuses
      </div>
    </div>
    <div style="background:#f6fbf7;border:1px solid #c6e6d0;border-top:none;
                border-radius:0 0 10px 10px;padding:14px;margin-bottom:18px;">
      {fin_cards}
    </div>
  </div>"""
    else:
        fin_section = ""

    # Credit Card & Travel section
    if cc_travel_deals:
        sorted_cct = sorted(
            cc_travel_deals,
            key=lambda d: (d.get("opportunity_score", 0), d.get("savings", 0), d.get("score", 0)),
            reverse=True,
        )
        # Split for sub-section counts
        n_cc     = sum(1 for d in sorted_cct if d.get("deal_subtype") == "credit_card")
        n_travel = len(sorted_cct) - n_cc
        sub_note = []
        if n_cc:     sub_note.append(f"{n_cc} credit card")
        if n_travel: sub_note.append(f"{n_travel} travel")
        sub_str = " · ".join(sub_note)

        cct_total_savings = sum(d.get("savings", 0) for d in sorted_cct)
        cct_cards = "\n".join(_cc_travel_card(d) for d in sorted_cct)

        cct_section = f"""
  <!-- Credit Card & Travel section -->
  <div style="margin-top:24px;">
    <div style="background:linear-gradient(135deg,#4f46e5,#3730a3);border-radius:10px 10px 0 0;
                padding:14px 20px;color:#fff;">
      <div style="font-size:17px;font-weight:800;">💳✈️ Credit Card &amp; Travel Deals</div>
      <div style="font-size:11px;opacity:0.85;margin-top:2px;">
        {len(sorted_cct)} deal(s) · {sub_str}
        &nbsp;·&nbsp; ~${cct_total_savings:,} AUD total value
        &nbsp;·&nbsp; Points valued at $0.0135/pt (Qantas &amp; Velocity)
      </div>
    </div>
    <div style="background:#f8f7ff;border:1px solid #c7d2fe;border-top:none;
                border-radius:0 0 10px 10px;padding:14px;margin-bottom:18px;">
      {cct_cards}
    </div>
  </div>"""
    else:
        cct_section = ""

    deals_section = f"""
  <!-- Main deals section -->
  <div style="margin-bottom:8px;font-size:13px;font-weight:700;color:#444;">
    🛍 Product &amp; Service Deals
  </div>
  {cards}""" if deals else ""

    # Food & Grocery section
    if food_deals:
        sorted_food = sorted(
            food_deals,
            key=lambda d: (d.get("opportunity_score", 0), d.get("score", 0), d.get("savings", 0)),
            reverse=True,
        )[:LIFESTYLE_TOP_N]
        food_cards = "\n".join(_lifestyle_card(d, accent_color="#e67e22") for d in sorted_food)
        food_section = f"""
  <!-- Food & Grocery section -->
  <div style="margin-top:24px;">
    <div style="background:linear-gradient(135deg,#e67e22,#ca6f1e);border-radius:10px 10px 0 0;
                padding:14px 20px;color:#fff;">
      <div style="font-size:17px;font-weight:800;">🍎 Food &amp; Groceries</div>
      <div style="font-size:11px;opacity:0.85;margin-top:2px;">
        Top {len(sorted_food)} of {len(food_deals)} deal(s) · supermarket, meal kits, groceries · score≥5 only
      </div>
    </div>
    <div style="background:#fffaf5;border:1px solid #ffe0b2;border-top:none;
                border-radius:0 0 10px 10px;padding:14px;margin-bottom:18px;">
      {food_cards}
    </div>
  </div>"""
    else:
        food_section = ""

    # Home & Appliances section
    if home_deals:
        sorted_home = sorted(
            home_deals,
            key=lambda d: (d.get("opportunity_score", 0), d.get("score", 0), d.get("savings", 0)),
            reverse=True,
        )[:LIFESTYLE_TOP_N]
        home_cards = "\n".join(_lifestyle_card(d, accent_color="#8e44ad") for d in sorted_home)
        home_section = f"""
  <!-- Home & Appliances section -->
  <div style="margin-top:24px;">
    <div style="background:linear-gradient(135deg,#8e44ad,#7d3c98);border-radius:10px 10px 0 0;
                padding:14px 20px;color:#fff;">
      <div style="font-size:17px;font-weight:800;">🏠 Home &amp; Appliances</div>
      <div style="font-size:11px;opacity:0.85;margin-top:2px;">
        Top {len(sorted_home)} of {len(home_deals)} deal(s) · whitegoods, kitchen, vacuum, appliances · score≥5 only
      </div>
    </div>
    <div style="background:#fdf5ff;border:1px solid #e8d5f5;border-top:none;
                border-radius:0 0 10px 10px;padding:14px;margin-bottom:18px;">
      {home_cards}
    </div>
  </div>"""
    else:
        home_section = ""

    # Extra categories — group by section label, one card per deal
    if extra_deals:
        sorted_extra = sorted(
            extra_deals,
            key=lambda d: (d.get("opportunity_score", 0), d.get("score", 0), d.get("savings", 0)),
            reverse=True,
        )[:LIFESTYLE_TOP_N * 2]  # show top 10 across all extra categories
        extra_cards  = "\n".join(_lifestyle_card(d, accent_color="#555") for d in sorted_extra)
        # Group label breakdown
        from collections import Counter
        cat_counts = Counter(d.get("_section", "other") for d in extra_deals)
        cat_str = " · ".join(f"{v} {k}" for k, v in cat_counts.most_common(5))
        extra_section = f"""
  <!-- Extra categories section -->
  <div style="margin-top:24px;">
    <div style="background:linear-gradient(135deg,#374151,#1f2937);border-radius:10px 10px 0 0;
                padding:14px 20px;color:#fff;">
      <div style="font-size:17px;font-weight:800;">📦 More Categories</div>
      <div style="font-size:11px;opacity:0.85;margin-top:2px;">
        Top {len(sorted_extra)} of {len(extra_deals)} deal(s) · {cat_str} · savings≥$200
      </div>
    </div>
    <div style="background:#f9fafb;border:1px solid #d1d5db;border-top:none;
                border-radius:0 0 10px 10px;padding:14px;margin-bottom:18px;">
      {extra_cards}
    </div>
  </div>"""
    else:
        extra_section = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OzBargain Deal Alert</title>
</head>
<body style="margin:0;padding:0;background:#f6f8fa;font-family:Arial,sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:20px;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#e05c00,#c44d00);border-radius:10px 10px 0 0;
              padding:20px 24px;color:#fff;">
    <div style="font-size:22px;font-weight:800;">🤖 OZB Deal Tracking Agent</div>
    <div style="font-size:12px;opacity:0.85;margin-top:4px;">📅 {now_str} &nbsp;·&nbsp; Powered by Claude AI</div>
  </div>

  <!-- Summary bar -->
  <div style="background:#fff;border:1px solid #d0d7de;border-top:none;
              border-radius:0 0 10px 10px;padding:12px 20px;margin-bottom:14px;">
    <strong>{len(deals)}</strong> product deal(s) found{flash_note}{cct_note}{fin_note}{food_note}{home_note}
    &nbsp;·&nbsp;
    <strong style="color:#1a7f37;">~${all_savings:,} AUD</strong> total possible savings
  </div>

  {briefing_html}
  {life_events_html}
  {money_audit_html}
  {travel_arb_html}
  {tier1_section}
  {deals_section}
  {cct_section}
  {fin_section}
  {food_section}
  {home_section}
  {extra_section}

  <!-- Footer -->
  <div style="font-size:11px;color:#999;margin-top:16px;padding:12px;
              border-top:1px solid #e8e8e8;text-align:center;">
    Product filters: score≥{min_score} · savings≥${min_savings:,} · votes≥{min_votes}
    · comments≥{min_comments} · clicks≥{min_clicks} · no age limit
    <br>CC/Travel &amp; Banking filters: score≥5 · savings≥${fin_min_savings:,} · Qantas/Velocity pts at $0.0135/pt · no age limit
    <br>Food &amp; Home: top 5 · score≥5 · no savings minimum · votes≥20 · comments≥3 · clicks≥50
    <br>
    <a href="https://www.ozbargain.com.au/cat/financial" style="color:#1a7f37;margin-right:12px;">
      Financial deals
    </a>
    <a href="https://www.ozbargain.com.au/cat/travel" style="color:#4f46e5;margin-right:12px;">
      Travel deals
    </a>
    <a href="https://www.ozbargain.com.au/cat/groceries" style="color:#e67e22;margin-right:12px;">
      Grocery deals
    </a>
    <a href="https://www.ozbargain.com.au/tag/appliances" style="color:#8e44ad;">
      Appliance deals
    </a>
  </div>

</div>
</body>
</html>"""
