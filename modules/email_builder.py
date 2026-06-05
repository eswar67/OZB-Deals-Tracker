"""
modules/email_builder.py

Email-client-safe HTML renderer for OzBargain deal alerts.

The layout intentionally uses simple tables and inline styles. That is less
fashionable than flexbox, but it is far more reliable in Gmail, Apple Mail,
Outlook, and mobile clients.
"""

from collections import defaultdict
from datetime import datetime, timezone
from html import escape


BRAND = "#e05c00"
INK = "#24292f"
MUTED = "#667085"
BORDER = "#d0d7de"
BG = "#f6f8fa"
GREEN = "#1a7f37"
RED = "#cf222e"
AMBER = "#b45309"


def _money(value) -> str:
    try:
        return f"${int(value):,}"
    except (TypeError, ValueError):
        return "$0"


def _format_age(age_mins: int) -> str:
    if age_mins < 60:
        return f"{age_mins}m ago"
    if age_mins < 2880:
        return f"{age_mins // 60}h {age_mins % 60}m ago"
    return f"{age_mins // 1440}d ago"


def _age_label(deal: dict) -> str:
    pub_date = deal.get("pubDate")
    if not pub_date:
        return ""
    try:
        age_mins = int((datetime.now(timezone.utc) - pub_date).total_seconds() / 60)
        return _format_age(max(age_mins, 0))
    except Exception:
        return ""


def _deal_icon(title: str) -> str:
    t = (title or "").lower()
    rules = [
        (("credit card", "bank", "savings account", "home loan"), "💳"),
        (("flight", "airfare", "hotel", "travel", "qantas", "velocity", "cruise"), "✈️"),
        (("laptop", "macbook", "notebook", "chromebook"), "💻"),
        (("iphone", "phone", "samsung galaxy", "pixel", "ipad", "tablet"), "📱"),
        (("tv", "television", "monitor", "oled", "qled"), "📺"),
        (("headphone", "earphone", "airpod", "earbud", "bose", "sony wh"), "🎧"),
        (("vacuum", "dyson", "roomba", "washing machine", "dryer", "fridge"), "🏠"),
        (("camera", "gopro", "lens", "dslr", "mirrorless"), "📷"),
        (("gift card", "voucher", "store credit"), "🎁"),
        (("game", "nintendo", "playstation", "xbox", "steam"), "🎮"),
        (("car", "vehicle", "driveaway", "suv", "ute"), "🚗"),
        (("cashback", "shopback", "cashrewards"), "💰"),
    ]
    for words, icon in rules:
        if any(word in t for word in words):
            return icon
    return "🛍️"


def _category(deal: dict) -> str:
    cats = deal.get("categories") or []
    return cats[0] if cats else "Other"


def _confidence_label(deal: dict) -> str:
    confidence = deal.get("value_confidence") or ""
    if confidence == "explicit_title_or_description":
        return "Explicit price text"
    if confidence == "market_lookup":
        return "Market lookup"
    if confidence == "llm_estimate":
        return "AI estimate"
    return "Parsed saving"


def _chip(text: str, bg: str = "#f6f8fa", color: str = INK) -> str:
    if not text:
        return ""
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'border:1px solid #eaecf0;border-radius:12px;padding:3px 8px;'
        f'font-size:11px;line-height:16px;margin:0 4px 4px 0;">{escape(str(text))}</span>'
    )


def _button(label: str, href: str, bg: str = BRAND, color: str = "#ffffff") -> str:
    if not href:
        return ""
    return (
        f'<a href="{escape(href, quote=True)}" '
        f'style="display:inline-block;background:{bg};color:{color};'
        f'text-decoration:none;border-radius:6px;padding:9px 13px;'
        f'font-size:13px;font-weight:700;line-height:16px;margin-right:8px;">'
        f'{escape(label)}</a>'
    )


def _summary_cell(label: str, value: str, color: str = INK) -> str:
    return f"""
      <td style="width:33.33%;padding:12px;border-right:1px solid #eaecf0;" valign="top">
        <div style="font-size:11px;line-height:14px;color:{MUTED};font-weight:700;text-transform:uppercase;">
          {escape(label)}
        </div>
        <div style="font-size:22px;line-height:28px;color:{color};font-weight:800;margin-top:3px;">
          {escape(value)}
        </div>
      </td>"""


def _deal_card(deal: dict) -> str:
    title = escape(deal.get("title", "No title"))
    ozb_link = deal.get("link", "#")
    ext_url = deal.get("external_url", "")
    merchant = deal.get("merchant_name", "")
    savings = int(deal.get("savings", 0) or 0)
    savings_percent = deal.get("savings_percent", 0) or 0
    market_price = int(deal.get("market_price", 0) or 0)
    deal_price = int(deal.get("deal_price", 0) or 0)
    explanation = escape(deal.get("explanation", "") or "Saving parsed from deal text")
    votes = int(deal.get("votes", 0) or 0)
    comments = int(deal.get("comments", 0) or 0)
    expiry = deal.get("expiry_label", "") or ""
    age = _age_label(deal)

    pct = f" · {savings_percent:.1f}% off" if savings_percent else ""
    price_line = []
    if deal_price:
        price_line.append(f"Deal {_money(deal_price)}")
    if market_price:
        price_line.append(f"Market {_money(market_price)}")
    price_text = " · ".join(price_line)

    meta = []
    if merchant:
        meta.append(merchant)
    if age:
        meta.append(age)
    if expiry and expiry != "No expiry date listed":
        meta.append(expiry)
    meta_text = " · ".join(meta)

    confidence = _chip(_confidence_label(deal), "#ecfdf3", GREEN)
    category = _chip(_category(deal), "#eef4ff", "#175cd3")
    engagement = _chip(f"{votes} votes · {comments} comments", "#f8fafc", MUTED)
    cashback = ""
    if deal.get("cashback_platform"):
        cashback = _chip(f"Cashback likely via {deal['cashback_platform']}", "#fff7ed", "#c2410c")

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="border:1px solid {BORDER};border-radius:8px;background:#ffffff;margin:0 0 12px 0;border-collapse:separate;">
      <tr>
        <td width="52" valign="top" style="padding:16px 0 16px 16px;font-size:30px;line-height:34px;">
          {_deal_icon(deal.get("title", ""))}
        </td>
        <td valign="top" style="padding:15px 16px 15px 12px;">
          <div style="font-size:15px;line-height:21px;font-weight:800;margin-bottom:6px;">
            <a href="{escape(ozb_link, quote=True)}" style="color:{INK};text-decoration:none;">{title}</a>
          </div>
          <div style="font-size:12px;line-height:17px;color:{MUTED};margin-bottom:9px;">
            {escape(meta_text)}
          </div>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                 style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:7px;border-collapse:separate;margin-bottom:10px;">
            <tr>
              <td style="padding:10px 12px;">
                <div style="font-size:24px;line-height:28px;font-weight:900;color:{GREEN};">
                  Save ~{_money(savings)} AUD<span style="font-size:13px;font-weight:800;">{escape(pct)}</span>
                </div>
                <div style="font-size:12px;line-height:17px;color:#166534;margin-top:3px;">
                  {escape(price_text)}
                </div>
                <div style="font-size:12px;line-height:17px;color:#344054;margin-top:5px;">
                  {explanation}
                </div>
              </td>
            </tr>
          </table>
          <div style="margin-bottom:8px;">
            {category}{confidence}{cashback}{engagement}
          </div>
          <div>
            {_button("View on OzBargain", ozb_link)}
            {_button("Merchant", ext_url, "#ffffff", INK)}
          </div>
        </td>
      </tr>
    </table>"""


def _section(title: str, deals: list[dict]) -> str:
    if not deals:
        return ""
    total = sum(int(d.get("savings", 0) or 0) for d in deals)
    cards = "\n".join(_deal_card(d) for d in deals)
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:18px 0 0 0;">
      <tr>
        <td style="background:{INK};color:#ffffff;border-radius:8px 8px 0 0;padding:12px 14px;">
          <div style="font-size:16px;line-height:20px;font-weight:900;">{escape(title)}</div>
          <div style="font-size:12px;line-height:17px;color:#d0d5dd;margin-top:2px;">
            {len(deals)} deal(s) · ~{_money(total)} AUD savings
          </div>
        </td>
      </tr>
      <tr>
        <td style="background:#ffffff;border:1px solid {BORDER};border-top:none;border-radius:0 0 8px 8px;padding:12px;">
          {cards}
        </td>
      </tr>
    </table>"""


def _briefing_section(briefing: dict) -> str:
    if not briefing or not briefing.get("actions"):
        return ""
    rows = ""
    for i, action in enumerate(briefing.get("actions", [])[:5], 1):
        rows += f"""
          <tr>
            <td style="padding:8px 0;border-top:1px solid #dcfce7;" valign="top">
              <div style="font-size:12px;line-height:17px;color:{GREEN};font-weight:900;">#{i} {_money(action.get("value", 0))}</div>
              <div style="font-size:13px;line-height:18px;color:{INK};font-weight:800;">
                {escape(action.get("icon", ""))} {escape(action.get("title", ""))}
              </div>
              <div style="font-size:12px;line-height:17px;color:{MUTED};">
                {escape(action.get("one_liner", ""))}
              </div>
            </td>
          </tr>"""
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;margin:0 0 16px 0;border-collapse:separate;">
      <tr>
        <td style="padding:14px 16px;">
          <div style="font-size:16px;line-height:21px;font-weight:900;color:#14532d;">
            Top deal opportunities
          </div>
          <div style="font-size:12px;line-height:17px;color:#166534;margin-top:2px;">
            {briefing.get("action_count", 0)} highlighted · ~{_money(briefing.get("total_value", 0))} combined savings
          </div>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;">
            {rows}
          </table>
        </td>
      </tr>
    </table>"""


def _group_deals(deals: list[dict]) -> list[tuple[str, list[dict]]]:
    grouped = defaultdict(list)
    for deal in deals:
        grouped[_category(deal)].append(deal)
    return sorted(
        grouped.items(),
        key=lambda item: sum(int(d.get("savings", 0) or 0) for d in item[1]),
        reverse=True,
    )


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
    financial_deals = financial_deals or []
    cc_travel_deals = cc_travel_deals or []
    food_deals = food_deals or []
    home_deals = home_deals or []
    extra_deals = extra_deals or []
    briefing = briefing or {}

    all_deals = deals + financial_deals + cc_travel_deals + food_deals + home_deals + extra_deals
    all_deals = sorted(all_deals, key=lambda d: int(d.get("savings", 0) or 0), reverse=True)
    total_savings = sum(int(d.get("savings", 0) or 0) for d in all_deals)
    top_saving = int(all_deals[0].get("savings", 0) or 0) if all_deals else 0
    now_str = datetime.now().strftime("%d %b %Y %H:%M")

    sections = "\n".join(_section(category, category_deals) for category, category_deals in _group_deals(all_deals))
    briefing_html = _briefing_section(briefing)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OzBargain Deal Alert</title>
</head>
<body style="margin:0;padding:0;background:{BG};font-family:Arial,Helvetica,sans-serif;color:{INK};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{BG};">
    <tr>
      <td align="center" style="padding:18px 10px;">
        <table role="presentation" width="680" cellspacing="0" cellpadding="0"
               style="width:100%;max-width:680px;background:{BG};border-collapse:separate;">
          <tr>
            <td style="background:{BRAND};border-radius:10px 10px 0 0;padding:20px 22px;color:#ffffff;">
              <div style="font-size:23px;line-height:29px;font-weight:900;">OzBargain Savings Digest</div>
              <div style="font-size:13px;line-height:18px;margin-top:4px;color:#fff3e8;">
                {escape(now_str)} · deals with quantified savings
              </div>
            </td>
          </tr>
          <tr>
            <td style="background:#ffffff;border:1px solid {BORDER};border-top:none;border-radius:0 0 10px 10px;padding:0;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                <tr>
                  {_summary_cell("Deals", str(len(all_deals)))}
                  {_summary_cell("Total Savings", f"~{_money(total_savings)}", GREEN)}
                  {_summary_cell("Top Saving", f"~{_money(top_saving)}", GREEN)}
                </tr>
              </table>
              <div style="padding:10px 16px 14px 16px;font-size:12px;line-height:18px;color:{MUTED};border-top:1px solid #eaecf0;">
                Inclusion: quantified savings of at least {_money(min_savings)}. Votes, comments and clicks are shown as context only.
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding-top:16px;">
              {briefing_html}
              {sections}
            </td>
          </tr>
          <tr>
            <td style="padding:18px 4px 6px 4px;text-align:center;font-size:11px;line-height:17px;color:{MUTED};">
              Market price and percentage-off values are inferred from explicit title or description prices when available.
              <br>
              <a href="https://www.ozbargain.com.au/deals" style="color:{BRAND};text-decoration:none;font-weight:700;">Open OzBargain Deals</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
