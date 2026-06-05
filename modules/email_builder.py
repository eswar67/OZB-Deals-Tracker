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


def _summary_cell(label: str, value: str, color: str = INK, href: str = "") -> str:
    tone = " good" if color == GREEN else ""
    value_html = escape(value)
    if href:
        value_html = f'<a href="{escape(href, quote=True)}" class="sumlink">{value_html}</a>'
    return f"""<td class="sum" valign="top">
        <div class="suml">{escape(label)}</div>
        <div class="sumv{tone}">{value_html}</div>
      </td>"""


def _deal_row(deal: dict, rank: int) -> str:
    title = escape(deal.get("title", "No title"))
    ozb_link = deal.get("link", "#")
    ext_url = deal.get("external_url", "")
    merchant = deal.get("merchant_name", "")
    savings = int(deal.get("savings", 0) or 0)
    savings_percent = deal.get("savings_percent", 0) or 0
    market_price = int(deal.get("market_price", 0) or 0)
    deal_price = int(deal.get("deal_price", 0) or 0)
    explanation = escape(deal.get("explanation", "") or "Saving parsed from deal text")
    expiry = deal.get("expiry_label", "") or ""
    age = _age_label(deal)

    pct = f" ({savings_percent:.1f}%)" if savings_percent else ""
    price_line = []
    if deal_price:
        price_line.append(f"Deal {_money(deal_price)}")
    if market_price:
        price_line.append(f"Market {_money(market_price)}")
    price_text = " · ".join(price_line)

    meta = []
    if age:
        meta.append(age)
    if expiry and expiry != "No expiry date listed":
        meta.append(expiry)
    meta_text = " · ".join(meta)

    proof = _confidence_label(deal)
    if deal.get("cashback_platform"):
        proof += f" · Cashback likely via {deal['cashback_platform']}"
    if deal.get("is_flash"):
        proof = f"⚡ Time-sensitive · {proof}"

    merchant_html = escape(merchant or "Merchant")
    if ext_url:
        merchant_html = (
            f'<a href="{escape(ext_url, quote=True)}" '
            f'style="color:{BRAND};text-decoration:none;font-weight:700;">{merchant_html}</a>'
        )

    meta_html = f"{merchant_html}{escape(' · ' + meta_text if merchant and meta_text else meta_text)}"
    proof_html = f"{escape(price_text)}{escape(' · ' if price_text else '')}{escape(proof)}"
    return (
        f'<tr><td class="num" width="42" valign="top">#{rank}<br>{_deal_icon(deal.get("title", ""))}</td>'
        f'<td class="deal" valign="top"><a class="title" href="{escape(ozb_link, quote=True)}">{title}</a>'
        f'<div class="meta">{meta_html}</div><div class="why">{explanation}</div>'
        f'<div class="proof">{proof_html}</div></td>'
        f'<td class="save" width="104" valign="top">{_money(savings)}<br><span>potential{escape(pct)}</span></td></tr>'
    )


def _section(title: str, deals: list[dict], start_rank: int, section_id: str = "") -> str:
    if not deals:
        return ""
    total = sum(int(d.get("savings", 0) or 0) for d in deals)
    rows = "\n".join(_deal_row(d, start_rank + i) for i, d in enumerate(deals))
    anchor = f'<a id="{escape(section_id, quote=True)}" name="{escape(section_id, quote=True)}"></a>' if section_id else ""
    return f"""{anchor}<table role="presentation" width="100%" cellspacing="0" cellpadding="0" class="sec">
      <tr><td class="sech"><b>{escape(title)}</b><br><span>{len(deals)} deal(s) · ~{_money(total)} AUD potential value</span></td></tr>
      <tr><td class="box"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" class="rows">{rows}</table></td></tr>
    </table>"""


def _briefing_section(briefing: dict) -> str:
    if not briefing or not briefing.get("actions"):
        return ""
    rows = ""
    for i, action in enumerate(briefing.get("actions", [])[:5], 1):
        rows += (
            f'<tr><td class="brrow" valign="top"><b>#{i} {_money(action.get("value", 0))}</b> '
            f'{escape(action.get("icon", ""))} {escape(action.get("title", ""))}'
            f'<br><span>{escape(action.get("one_liner", ""))}</span></td></tr>'
        )
    return f"""<table role="presentation" width="100%" cellspacing="0" cellpadding="0" class="brief">
      <tr><td><b>Top potential opportunities</b><br><span>{briefing.get("action_count", 0)} highlighted · ~{_money(briefing.get("total_value", 0))} combined potential value</span>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">{rows}</table></td></tr>
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
    flash_deals = [d for d in all_deals if d.get("is_flash")]
    non_flash_deals = [d for d in all_deals if not d.get("is_flash")]
    total_savings = sum(int(d.get("savings", 0) or 0) for d in all_deals)
    top_saving = int(all_deals[0].get("savings", 0) or 0) if all_deals else 0
    top_link = all_deals[0].get("link", "#all-deals") if all_deals else "#all-deals"
    now_str = datetime.now().strftime("%d %b %Y %H:%M")

    sections = []
    rank = 1
    sections.append('<a id="all-deals" name="all-deals"></a>')
    if flash_deals:
        sections.append(_section("⚡ Time-sensitive opportunities", flash_deals, rank, "time-sensitive"))
        rank += len(flash_deals)
    for category, category_deals in _group_deals(non_flash_deals):
        sections.append(_section(category, category_deals, rank))
        rank += len(category_deals)
    sections_html = "\n".join(sections)
    briefing_html = _briefing_section(briefing)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OzBargain Deal Alert</title>
  <style>
    body{{margin:0;padding:0;background:{BG};font-family:Arial,Helvetica,sans-serif;color:{INK}}}
    table{{border-collapse:collapse}} a{{color:{BRAND}}}
    .wrap{{width:100%;max-width:660px;background:{BG}}}
    .hero{{background:{BRAND};border-radius:8px 8px 0 0;padding:16px 18px;color:#fff}}
    .hero b{{font-size:22px;line-height:27px}} .hero div{{font-size:13px;line-height:18px;margin-top:3px;color:#fff3e8}}
    .summary{{background:#fff;border:1px solid {BORDER};border-top:0;border-radius:0 0 8px 8px}}
    .sum{{width:33.33%;padding:10px 8px;border-right:1px solid #eaecf0}}
    .suml{{font-size:10px;line-height:13px;color:{MUTED};font-weight:700;text-transform:uppercase}}
    .sumv{{font-size:18px;line-height:23px;color:{INK};font-weight:800;margin-top:2px}} .good{{color:{GREEN}}}
    .sumlink{{color:inherit;text-decoration:none}}
    .note{{padding:9px 14px 12px;font-size:12px;line-height:17px;color:{MUTED};border-top:1px solid #eaecf0}}
    .brief{{background:#f0fdf4;border:1px solid #86efac;border-radius:6px;margin:0 0 16px}}.brief td{{padding:12px 14px;color:#14532d;font-size:14px;line-height:19px}}.brief span{{color:#166534;font-size:12px}}.brrow{{border-top:1px solid #dcfce7}}
    .sec{{margin:18px 0 0}} .sech{{background:{INK};color:#fff;border-radius:6px 6px 0 0;padding:10px 12px;font-size:16px;line-height:20px}} .sech span{{font-size:12px;line-height:17px;color:#d0d5dd}}
    .box{{background:#fff;border:1px solid {BORDER};border-top:0;border-radius:0 0 6px 6px;padding:0}} .rows tr:first-child td{{border-top:0}}
    .num{{padding:10px 8px;border-top:1px solid #eaecf0;text-align:center;color:{MUTED};font-size:11px;line-height:18px;font-weight:800}}
    .deal{{padding:10px 8px;border-top:1px solid #eaecf0}} .title{{color:{INK};text-decoration:none;font-size:14px;line-height:19px;font-weight:800}}
    .meta{{font-size:12px;line-height:17px;color:{MUTED};margin-top:2px}} .meta a{{text-decoration:none;font-weight:700}}
    .why{{font-size:12px;line-height:17px;color:#344054;margin-top:4px}} .proof{{font-size:11px;line-height:15px;color:{MUTED};margin-top:3px}}
    .save{{padding:10px 8px;border-top:1px solid #eaecf0;text-align:right;color:{GREEN};font-size:18px;line-height:22px;font-weight:900}} .save span{{font-size:11px;line-height:14px;font-weight:800}}
    .foot{{padding:18px 4px 6px;text-align:center;font-size:11px;line-height:17px;color:{MUTED}}}
  </style>
</head>
<body>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
    <tr>
      <td align="center" style="padding:18px 10px;">
        <table role="presentation" width="660" cellspacing="0" cellpadding="0" class="wrap">
          <tr>
            <td class="hero">
              <b>OzBargain Opportunity Digest</b>
              <div>{escape(now_str)} · every qualifying deal is listed below</div>
            </td>
          </tr>
          <tr>
            <td class="summary">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  {_summary_cell("Deals", str(len(all_deals)), href="#all-deals")}
                  {_summary_cell("Potential Value", f"~{_money(total_savings)}", GREEN, "#all-deals")}
                  {_summary_cell("Top Opportunity", f"~{_money(top_saving)}", GREEN, top_link)}
                </tr>
              </table>
              <div class="note">
                Inclusion: quantified potential saving opportunities of at least {_money(min_savings)}. Votes, comments and clicks are shown as context only.
                {f'<br><a href="#time-sensitive" style="font-weight:700;">View {len(flash_deals)} time-sensitive deal(s)</a>' if flash_deals else ''}
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding-top:16px;">
              {briefing_html}
              {sections_html}
            </td>
          </tr>
          <tr>
            <td class="foot">
              Potential value and percentage-off values are inferred from explicit title or description prices when available.
              <br>
              <a href="https://www.ozbargain.com.au/deals" style="text-decoration:none;font-weight:700;">Open OzBargain Deals</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
