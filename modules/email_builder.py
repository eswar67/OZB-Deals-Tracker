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


def _format_age(age_mins: int) -> str:
    """Human-readable age: minutes < 1h, hours < 48h, otherwise days."""
    if age_mins < 60:
        return f"{age_mins}m ago"
    if age_mins < 2880:   # < 48 hours
        return f"{age_mins // 60}h {age_mins % 60}m ago"
    return f"{age_mins // 1440}d ago"   # 48h+ → days


def _expiry_is_urgent(label: str) -> bool:
    """Urgent = expires within ~5 days (labels prefixed with the ⏰ clock)."""
    return label.startswith("⏰")


def _expiry_html(label: str) -> str:
    """Inline expiry chip for the stats bar. Always shown so status is explicit."""
    if not label:
        return ""
    urgent  = _expiry_is_urgent(label)
    no_date = label == "No expiry date listed"
    color   = "#b45309" if urgent else "#999" if no_date else "#555"
    weight  = "700" if urgent else "400"
    return (f'&nbsp; <span style="color:{color};font-weight:{weight};font-size:11px;">'
            f'{label}</span>')


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
    savings_pct = deal.get("savings_percent", 0)

    if not savings:
        return '<div style="font-size:12px;color:#888;margin:6px 0;">Check deal for current pricing</div>'

    pct_html = (
        f'<span style="font-size:12px;font-weight:700;color:#1a7f37;">({savings_pct:.1f}% off)</span>'
        if savings_pct else ""
    )
    calc_html = (
        f'<span style="font-size:11px;color:#555;margin-left:8px;">{explanation}</span>'
        if explanation else ""
    )
    return f"""
<div style="margin:8px 0;display:flex;align-items:baseline;flex-wrap:wrap;gap:4px;">
  <span style="font-size:22px;font-weight:800;color:#1a7f37;">~${savings:,} AUD</span>
  {pct_html}
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
    market_price  = deal.get("market_price", 0)
    market_note   = deal.get("market_note", "")
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
        age_str = _format_age(age_mins)
        is_new   = age_mins < 1440  # posted within last 24 hours

    # Expiry label
    expiry_label = deal.get("expiry_label", "")
    expiry_urgent = _expiry_is_urgent(expiry_label)

    # Flash / urgency banner
    if is_flash:
        flash_html = (
            '<div style="background:#d73a49;color:#fff;font-size:12px;font-weight:bold;'
            'padding:5px 14px;text-align:center;">⚡ FLASH DEAL — Act Fast!</div>'
        )
    elif expiry_urgent:
        flash_html = (
            f'<div style="background:#b45309;color:#fff;font-size:12px;font-weight:bold;'
            f'padding:5px 14px;text-align:center;">{expiry_label} — Limited time!</div>'
        )
    elif savings >= 800 and score >= 7:
        flash_html = (
            '<div style="background:#1a7f37;color:#fff;font-size:12px;font-weight:bold;'
            'padding:5px 14px;text-align:center;">🔥 High-Value Deal — Review Before It Expires</div>'
        )
    else:
        flash_html = ""

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

    # Cashback badge — availability only, no % (check live rate via link)
    cb_html = ""
    if cb_plat:
        cb_href = f'href="{cb_url}"' if cb_url else ""
        cb_html = (
            f'<a {cb_href} style="display:inline-block;background:#ff6900;color:#fff;'
            f'font-size:11px;font-weight:700;padding:4px 10px;border-radius:6px;'
            f'text-decoration:none;margin:6px 0;">💰 Cashback likely via {cb_plat} — check rate</a>'
        )

    # Market price panel (Claude-sourced)
    market_cheaper = deal.get("market_cheaper", False)
    market_saving  = deal.get("market_saving", 0)
    deal_price_val = deal.get("deal_price", 0)

    market_html = ""
    if market_price > 0:
        if market_cheaper:
            # Deal price is HIGHER than typical market — warn
            overpay = deal_price_val - market_price if deal_price_val else 0
            market_html = f"""
<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;
            padding:8px 12px;margin:8px 0;font-size:12px;">
  <strong>⚠️ Market check:</strong> {market_note or f'~${market_price:,} AUD typical market price'}
  {f'<span style="color:#856404;"> — deal may be ${overpay:,} above market</span>' if overpay > 0 else ""}
  <span style="color:#999;font-size:10px;margin-left:6px;">· verify current pricing</span>
</div>"""
        else:
            # Market price validates the deal or provides useful context
            market_html = f"""
<div style="background:#e6f4ea;border:1px solid #a8d5b5;border-radius:6px;
            padding:8px 12px;margin:8px 0;font-size:12px;">
  <strong>🏪 Market price:</strong> {market_note or f'~${market_price:,} AUD'}
  <span style="color:#999;font-size:10px;margin-left:6px;">· estimated from Claude AI</span>
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
        + _expiry_html(expiry_label)
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
      {market_html}

      <!-- Savings breakdown -->
      {_savings_breakdown(deal)}


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
        age_str = _format_age(age_mins)
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
            from modules.value_parser import QANTAS_CPP, VELOCITY_CPP
            cpp       = VELOCITY_CPP if pts_brand.lower() == "velocity" else QANTAS_CPP
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
        + _expiry_html(deal.get("expiry_label", ""))
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
        age_str = _format_age(age_mins)
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
        + _expiry_html(deal.get("expiry_label", ""))
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
        age_str = _format_age(age_mins)

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
        + _expiry_html(deal.get("expiry_label", ""))
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
      <div style="margin-bottom:8px;">{score_html}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div>{cta_view}{cta_merchant}</div>
        {stats}
      </div>
    </div>
  </div>
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
        rows += (
            f'<div style="display:flex;align-items:baseline;gap:10px;padding:6px 0;'
            f'border-bottom:1px solid #f0fdf4;">'
            f'<span style="font-size:14px;font-weight:800;color:#1a7f37;min-width:18px;">#{i}</span>'
            f'<div style="flex:1;">'
            f'<span style="font-weight:700;font-size:12px;">{a["icon"]} {a["title"]}</span>'
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
    <div style="margin-bottom:10px;">
      <div style="font-size:17px;font-weight:800;color:#14532d;">
        ☀️ {briefing.get('date','')} — Top {briefing['action_count']} deal(s)
      </div>
      <div style="font-size:11px;color:#166534;margin-top:2px;">
        ~${briefing['total_value']:,} combined savings
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
    extra_deals: list = None,
    briefing: dict = None,
) -> str:
    financial_deals   = financial_deals   or []
    cc_travel_deals   = cc_travel_deals   or []
    food_deals        = food_deals        or []
    home_deals        = home_deals        or []
    extra_deals       = extra_deals       or []
    briefing          = briefing          or {}
    total_savings = sum(d.get("savings", 0) for d in deals)
    flash_count   = sum(1 for d in deals if d.get("is_flash"))
    now_str       = datetime.now().strftime("%d %b %Y %H:%M AEST")

    LIFESTYLE_TOP_N = 5

    # Sort by flash first, then savings, then score
    def _sort_key(d):
        return (d.get("is_flash", False), d.get("savings", 0), d.get("score", 0))

    sorted_deals = sorted(deals, key=_sort_key, reverse=True)
    grouped_cards = []
    if sorted_deals:
        from collections import defaultdict
        grouped = defaultdict(list)
        for d in sorted_deals:
            cats = d.get("categories") or ["Other"]
            grouped[cats[0] or "Other"].append(d)

        for category, cat_deals in sorted(
            grouped.items(),
            key=lambda item: sum(d.get("savings", 0) for d in item[1]),
            reverse=True,
        ):
            cat_savings = sum(d.get("savings", 0) for d in cat_deals)
            cat_cards = "\n".join(_deal_card(d) for d in cat_deals)
            grouped_cards.append(f"""
  <div style="margin-top:18px;">
    <div style="background:#24292f;color:#fff;border-radius:8px 8px 0 0;
                padding:10px 14px;font-size:15px;font-weight:800;">
      {category} · {len(cat_deals)} deal(s) · ~${cat_savings:,} AUD savings
    </div>
    <div style="background:#fff;border:1px solid #d0d7de;border-top:none;
                border-radius:0 0 8px 8px;padding:12px;">
      {cat_cards}
    </div>
  </div>""")
    cards = "\n".join(grouped_cards)

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

    # Financial (banking) section
    if financial_deals:
        sorted_fin = sorted(
            financial_deals,
            key=lambda d: (d.get("savings", 0), d.get("score", 0)),
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
            key=lambda d: (d.get("savings", 0), d.get("score", 0)),
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
    🛍 Deals with Quantified Savings ≥ ${min_savings:,}
  </div>
  {cards}""" if deals else ""

    # Food & Grocery section
    if food_deals:
        sorted_food = sorted(
            food_deals,
            key=lambda d: (d.get("savings", 0), d.get("score", 0)),
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
        Top {len(sorted_food)} of {len(food_deals)} deal(s) · supermarket, meal kits, groceries · score≥5 · savings≥$100
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
            key=lambda d: (d.get("savings", 0), d.get("score", 0)),
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
        Top {len(sorted_home)} of {len(home_deals)} deal(s) · whitegoods, kitchen, vacuum, appliances · score≥5 · savings≥$100
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
            key=lambda d: (d.get("savings", 0), d.get("score", 0)),
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
        Top {len(sorted_extra)} of {len(extra_deals)} deal(s) · {cat_str} · savings≥$100
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
    {'<strong>' + str(len(deals)) + '</strong> product deal(s)' if deals else ''}{flash_note}{cct_note}{fin_note}{food_note}{home_note}
    &nbsp;·&nbsp;
    <strong style="color:#1a7f37;">~${all_savings:,} AUD</strong> total possible savings
  </div>

  {briefing_html}
  {deals_section}
  {cct_section}
  {fin_section}
  {food_section}
  {home_section}
  {extra_section}

  <!-- Footer -->
  <div style="font-size:11px;color:#999;margin-top:16px;padding:12px;
              border-top:1px solid #e8e8e8;text-align:center;">
    Inclusion rule: quantified savings ≥ ${min_savings:,} · no votes/comments/clicks filter · HTML crawl across OzBargain deal pages
    <br>Market price and savings percentage are inferred from explicit title/description prices when available.
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
