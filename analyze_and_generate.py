#!/usr/bin/env python3
"""
Stap 2: analyseert nieuws via GitHub Models (gpt-4o-mini) en genereert email_final.html.
Vereist: GITHUB_TOKEN env var.
"""

import json
import os
import time
import hashlib
from datetime import datetime
from openai import OpenAI

NL_DAYS = [
    "maandag", "dinsdag", "woensdag", "donderdag",
    "vrijdag", "zaterdag", "zondag",
]
NL_MONTHS = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}

BADGE_COLORS = [
    "#1e3a5f", "#b03a2e", "#5b2c6f", "#1a5276",
    "#145a32", "#7d6608", "#1b4f72", "#784212",
]

SENTIMENT_CSS = {
    "BULLISH":  "background:#d5f5e3;color:#1d8348;",
    "BEARISH":  "background:#fadbd8;color:#922b21;",
    "NEUTRAAL": "background:#eaecee;color:#566573;",
}

# Maps portfolio tickers to SPDR sector ETF names for rule-based context
TICKER_SECTOR = {
    "NVDA": "Technologie", "ADBE": "Technologie", "SMH": "Technologie",
    "ORCL": "Technologie", "PLTR": "Technologie", "QLYS": "Technologie",
    "HPQ": "Technologie",  "FIGMA": "Technologie",
    "GOOGL": "Communicatie", "NFLX": "Communicatie", "DIS": "Communicatie",
    "ESPO": "Communicatie", "DUOL": "Communicatie", "T": "Communicatie",
    "PINS": "Communicatie", "SNAP": "Communicatie",
    "AMZN": "Cons. discr.", "NKE": "Cons. discr.", "SBUX": "Cons. discr.",
    "VOW3": "Cons. discr.", "NIO": "Cons. discr.",
    "KO": "Cons. basis", "ULVR": "Cons. basis",
    "SHELL": "Energie",
    "NVO": "Zorg",
    "ALFEN": "Industrie",
    "PYPL": "Financieel", "COIN": "Financieel",
}


def get_client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN niet gevonden")
    return OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)


def chat(client, prompt, max_tokens=200, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  GitHub Models fout (poging {attempt + 1}): {e}")
            if attempt < retries:
                time.sleep(3)
    return None


def extract_json(text, array=False):
    if not text:
        return None
    open_ch, close_ch = ("[", "]") if array else ("{", "}")
    start = text.find(open_ch)
    end = text.rfind(close_ch)
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


# ── AI functions ──────────────────────────────────────────────────────────────

def generate_day_summary(client, indices, macro, sectors, market_news,
                         portfolio_news, earnings, portfolio_prices):
    """AI writes a 3-4 sentence Dutch market summary personal to this portfolio."""
    index_lines = []
    for idx in indices.values():
        if idx:
            arrow = "▲" if idx["change_pct"] >= 0 else "▼"
            index_lines.append(f"{idx['name']}: {arrow}{abs(idx['change_pct']):.2f}%")

    macro_lines = []
    if macro.get("vix"):
        v = macro["vix"]["value"]
        label = "Lage spanning" if v < 15 else "Normaal" if v < 20 else "Verhoogd" if v < 25 else "Hoog — marktonrust"
        macro_lines.append(f"VIX: {v} ({label})")
    if macro.get("us10y"):
        v = macro["us10y"]["value"]
        label = "laag (goed voor tech)" if v < 3 else "neutraal" if v < 4 else "hoog (druk op groeiaandelen)"
        macro_lines.append(f"US 10Y rente: {v}% — {label}")
    if macro.get("eurusd"):
        macro_lines.append(f"EUR/USD: {macro['eurusd']['value']}")

    sector_lines = []
    if sectors:
        sorted_s = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        top2 = [(n, s["change_pct"]) for n, s in sorted_s[:2] if s["change_pct"] > 0]
        bot2 = [(n, s["change_pct"]) for n, s in sorted_s[-2:] if s["change_pct"] < 0]
        if top2:
            sector_lines.append("Koploper: " + ", ".join(f"{n} {c:+.1f}%" for n, c in top2))
        if bot2:
            sector_lines.append("Achterblijver: " + ", ".join(f"{n} {c:+.1f}%" for n, c in bot2))

    # Top movers in portfolio
    if portfolio_prices:
        sorted_p = sorted(portfolio_prices.items(), key=lambda x: x[1], reverse=True)
        top3 = [(t, c) for t, c in sorted_p[:3] if c > 0]
        bot3 = [(t, c) for t, c in sorted_p[-3:] if c < 0]
        if top3:
            sector_lines.append("Portfolio best: " + ", ".join(f"{t} {c:+.1f}%" for t, c in top3))
        if bot3:
            sector_lines.append("Portfolio zwakst: " + ", ".join(f"{t} {c:+.1f}%" for t, c in bot3))

    news_str = "\n".join(f"- {n['title']}" for n in market_news[:3]) or "Geen"
    alerts_str = "\n".join(f"- {t}: {i['title']}" for t, i in portfolio_news.items()) or "Geen"
    earn_str = ", ".join(f"{e['ticker']} ({e['date']})" for e in earnings) if earnings else "Geen"

    result = chat(client, (
        "Schrijf een dagelijkse marktsamenvatting in 3-4 zinnen in het Nederlands. "
        "Schrijf als persoonlijke financieel adviseur die spreekt tot een belegger met "
        "een tech-zwaar portfolio (NVDA, COIN, ADBE, GOOGL, NFLX, PLTR, SMH). "
        "Verwijs naar concrete cijfers. Eindig met één concrete tip voor vandaag.\n\n"
        f"INDICES: {', '.join(index_lines) or 'n.v.t.'}\n"
        f"MACRO: {'; '.join(macro_lines) or 'n.v.t.'}\n"
        f"SECTOREN: {'; '.join(sector_lines) or 'n.v.t.'}\n"
        f"MARKTNIEUWS:\n{news_str}\n"
        f"PORTFOLIO-ALERTS:\n{alerts_str}\n"
        f"EARNINGS DEZE WEEK: {earn_str}\n\n"
        "Samenvatting:"
    ), max_tokens=300)
    return result


def summarize_market_news(client, news_items):
    """Batch-summarize all market news in one AI call."""
    if not news_items:
        return
    lines = []
    for i, n in enumerate(news_items, 1):
        lines.append(f"{i}. {n['title']}\n   {(n.get('content') or '')[:350]}")

    time.sleep(1)
    raw = chat(client, (
        "Geef per bericht een samenvatting van 2 zinnen in het Nederlands. "
        "Focus op wat het betekent voor een belegger. Direct en concreet.\n"
        "Uitsluitend JSON-array:\n"
        '[{"index":1,"samenvatting":"..."}]\n\n'
        + "\n\n".join(lines)
    ), max_tokens=500)

    result = extract_json(raw, array=True)
    if result:
        mapping = {item.get("index"): item.get("samenvatting") for item in result}
        for i, n in enumerate(news_items, 1):
            if mapping.get(i):
                n["summary"] = mapping[i]


def analyze_positions_with_news(client, portfolio_news, sectors, market_news):
    """AI analysis for positions that have their own news article (usually 0-5)."""
    if not portfolio_news:
        return {}

    # Build macro context
    macro_ctx = ""
    if sectors:
        sorted_s = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        macro_ctx = "SECTOREN: " + ", ".join(
            f"{n} {s['change_pct']:+.1f}%" for n, s in sorted_s
        )
    if market_news:
        macro_ctx += "\nMARKTNIEUWS: " + "; ".join(n["title"] for n in market_news[:2])

    results = {}
    for ticker, info in portfolio_news.items():
        time.sleep(1)
        raw = chat(client, (
            f"Analyseer dit nieuws over {info['company']} ({ticker}), positie {info['pct']}% portfolio.\n"
            f"TITEL: {info['title']}\n"
            f"INHOUD: {(info.get('content') or info['title'])[:600]}\n"
            f"{macro_ctx}\n\n"
            "Uitsluitend JSON (geen uitleg, geen markdown):\n"
            '{"sentiment":"BULLISH/BEARISH/NEUTRAAL","wat":"1-2 zinnen wat er speelt","advies":"HOLD/MONITOR/BUY/SELL — 1 zin reden"}'
        ), max_tokens=200)

        data = extract_json(raw)
        if data:
            sent = str(data.get("sentiment", "NEUTRAAL")).upper()
            if sent not in SENTIMENT_CSS:
                sent = "NEUTRAAL"
            results[ticker] = {
                "sentiment": sent,
                "wat": data.get("wat", ""),
                "advies": data.get("advies", ""),
            }
        print(f"  {ticker}: {results.get(ticker, {}).get('sentiment', 'FOUT')}")
    return results


def macro_context_for_position(ticker, sectors, portfolio_prices, extremes_52w):
    """Rule-based context for positions without their own news."""
    notes = []

    # Sector movement
    sector = TICKER_SECTOR.get(ticker)
    if sector and sectors.get(sector):
        chg = sectors[sector]["change_pct"]
        if abs(chg) >= 1.0:
            direction = "steeg" if chg > 0 else "daalde"
            notes.append(f"{sector}sector {direction} {abs(chg):.1f}% vandaag")

    # Price movement
    price_chg = portfolio_prices.get(ticker)
    if price_chg is not None and abs(price_chg) >= 2.0:
        direction = "steeg" if price_chg > 0 else "daalde"
        notes.append(f"Koers {direction} {abs(price_chg):.1f}%")

    # 52-week extreme
    extreme = extremes_52w.get(ticker)
    if extreme:
        if extreme["type"] == "HIGH":
            notes.append(f"Nabij 52-weeks high ({extreme['pct']:+.1f}%)")
        else:
            notes.append(f"Nabij 52-weeks low ({extreme['pct']:+.1f}%)")

    return "; ".join(notes) if notes else ""


def build_watchlist(client, portfolio_news, portfolio_analyses,
                    market_news, sectors, portfolio_prices, extremes_52w):
    """AI picks top 3 positions to watch based on all available signals."""
    lines = []

    for t, i in portfolio_news.items():
        an = portfolio_analyses.get(t, {})
        lines.append(f"- {t} ({i['pct']}%): {i['title']} [{an.get('sentiment', '')}]")

    # Positions with big price moves
    if portfolio_prices:
        big_movers = [(t, c) for t, c in portfolio_prices.items()
                      if abs(c) >= 2.0 and t not in portfolio_news]
        big_movers.sort(key=lambda x: abs(x[1]), reverse=True)
        for t, c in big_movers[:4]:
            lines.append(f"- {t}: koers {c:+.1f}% vandaag")

    # 52-week extremes
    for t, e in extremes_52w.items():
        if t not in portfolio_news:
            label = "nabij 52w HIGH" if e["type"] == "HIGH" else "nabij 52w LOW"
            lines.append(f"- {t}: {label} ({e['pct']:+.1f}%)")

    if sectors:
        sorted_s = sorted(sectors.items(), key=lambda x: abs(x[1]["change_pct"]), reverse=True)
        movers = [f"{n} {s['change_pct']:+.1f}%" for n, s in sorted_s[:3]]
        lines.append("Sectorbewegingen: " + ", ".join(movers))

    if market_news:
        lines += [f"Markt: {n['title']}" for n in market_news[:2]]

    if not lines:
        return []

    time.sleep(1)
    raw = chat(client, (
        "Je bent beleggingsadviseur. Kies 3 posities die vandaag de meeste aandacht verdienen.\n"
        "Uitsluitend JSON-array:\n"
        '[{"ticker":"COIN","pct":7.6,"categorie":"Crypto",'
        '"beschrijving":"2-3 zinnen waarom","actie":"concrete actie voor vandaag"}]\n\n'
        "Kies precies 3:\n" + "\n".join(lines)
    ), max_tokens=500)

    result = extract_json(raw, array=True)
    return result[:3] if result else []


# ── HTML rendering ─────────────────────────────────────────────────────────────

def badge_color(ticker):
    idx = int(hashlib.md5(ticker.encode()).hexdigest(), 16) % len(BADGE_COLORS)
    return BADGE_COLORS[idx]


def nl_price(val):
    if val is None:
        return "—"
    return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def nl_pct(val):
    return f"{abs(val):.2f}".replace(".", ",")


def today_long():
    n = datetime.now()
    return f"{NL_DAYS[n.weekday()]} {n.day} {NL_MONTHS[n.month]} {n.year}"


def render_index(key, idx):
    labels = {"sp500": "S&P 500", "nasdaq": "NASDAQ", "aex": "AEX"}
    label = labels.get(key, key.upper())
    if not idx:
        return (f'<div class="ix"><div class="ix-label">{label}</div>'
                f'<div class="ix-val">—</div>'
                f'<div class="ix-chg" style="color:#aaa">N/B</div></div>')
    chg = idx["change_pct"]
    color = "green" if chg >= 0 else "red"
    arrow = "▲" if chg >= 0 else "▼"
    return (f'<div class="ix"><div class="ix-label">{label}</div>'
            f'<div class="ix-val">{nl_price(idx["price"])}</div>'
            f'<div class="ix-chg {color}">{arrow} {nl_pct(chg)}%</div></div>')


def render_macro_bar(macro):
    if not macro:
        return ""
    parts = []

    if macro.get("vix"):
        v = macro["vix"]["value"]
        chg = macro["vix"]["change_pct"]
        col = "#1d8348" if v < 15 else "#566573" if v < 20 else "#e67e22" if v < 25 else "#c0392b"
        arrow = "▲" if chg >= 0 else "▼"
        label = "rustig" if v < 15 else "normaal" if v < 20 else "verhoogd" if v < 25 else "hoog"
        parts.append(
            f'<span class="mb-item">'
            f'<span class="mb-label">VIX</span>'
            f'<span class="mb-val" style="color:{col}">{v:.1f}</span>'
            f'<span class="mb-sub" style="color:{col}">{arrow}{abs(chg):.1f}% — {label}</span>'
            f'</span>'
        )

    if macro.get("us10y"):
        v = macro["us10y"]["value"]
        chg = macro["us10y"]["change_pct"]
        col = "#1d8348" if v < 3 else "#566573" if v < 4 else "#e67e22" if v < 4.5 else "#c0392b"
        arrow = "▲" if chg >= 0 else "▼"
        parts.append(
            f'<span class="mb-item">'
            f'<span class="mb-label">US 10Y</span>'
            f'<span class="mb-val" style="color:{col}">{v:.2f}%</span>'
            f'<span class="mb-sub">{arrow}{abs(chg):.2f}%</span>'
            f'</span>'
        )

    if macro.get("eurusd"):
        v = macro["eurusd"]["value"]
        chg = macro["eurusd"]["change_pct"]
        arrow = "▲" if chg >= 0 else "▼"
        parts.append(
            f'<span class="mb-item">'
            f'<span class="mb-label">EUR/USD</span>'
            f'<span class="mb-val">{v:.4f}</span>'
            f'<span class="mb-sub">{arrow}{abs(chg):.2f}%</span>'
            f'</span>'
        )

    return '<div class="macro-bar">' + '<span class="mb-sep">•</span>'.join(parts) + '</div>'


def render_portfolio_snapshot(portfolio, prices, extremes_52w):
    """Color-coded chips for all positions sorted best → worst."""
    if not prices:
        return ""

    items = []
    for pos in portfolio:
        t = pos["ticker"]
        chg = prices.get(t)
        extreme = extremes_52w.get(t)
        items.append((t, chg, extreme))

    # Sort: positions with data first (by change), then N/A
    with_data = sorted([(t, c, e) for t, c, e in items if c is not None],
                       key=lambda x: x[1], reverse=True)
    without_data = [(t, None, e) for t, c, e in items if c is None]
    sorted_items = with_data + without_data

    chips = []
    for ticker, chg, extreme in sorted_items:
        if chg is None:
            bg, col = "#eaecee", "#888"
            label = f"{ticker} —"
        elif chg >= 2.0:
            bg, col = "#145a32", "#fff"
            label = f"{ticker} +{chg:.1f}%"
        elif chg >= 0.5:
            bg, col = "#d5f5e3", "#1d8348"
            label = f"{ticker} +{chg:.1f}%"
        elif chg >= -0.5:
            bg, col = "#eaecee", "#566573"
            sign = "+" if chg >= 0 else ""
            label = f"{ticker} {sign}{chg:.1f}%"
        elif chg >= -2.0:
            bg, col = "#fadbd8", "#922b21"
            label = f"{ticker} {chg:.1f}%"
        else:
            bg, col = "#922b21", "#fff"
            label = f"{ticker} {chg:.1f}%"

        suffix = ""
        if extreme:
            suffix = " ▲H" if extreme["type"] == "HIGH" else " ▼L"

        chips.append(
            f'<span class="snap-chip" style="background:{bg};color:{col}" '
            f'title="{ticker}">{label}{suffix}</span>'
        )

    return '<div class="snapshot-row">' + "".join(chips) + "</div>"


def render_sectors(sectors):
    if not sectors:
        return ""
    sorted_s = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
    chips = []
    for name, s in sorted_s:
        chg = s["change_pct"]
        if chg >= 0.5:
            bg, col = "#d5f5e3", "#1d8348"
        elif chg <= -0.5:
            bg, col = "#fadbd8", "#922b21"
        else:
            bg, col = "#eaecee", "#566573"
        arrow = "▲" if chg >= 0 else "▼"
        chips.append(
            f'<span class="sector-chip" style="background:{bg};color:{col}">'
            f'{name} {arrow}{chg:+.2f}%</span>'
        )
    return '<div class="sector-row">' + "".join(chips) + "</div>"


def render_agenda(earnings):
    if not earnings:
        return ""
    badges = []
    for e in earnings:
        days = e.get("days_away", 0)
        if days == 0:
            label, bg, col = "VANDAAG", "#fdebd0", "#935116"
        elif days == 1:
            label, bg, col = "MORGEN", "#fef9e7", "#9a7d0a"
        else:
            label, bg, col = f"over {days}d", "#eaecee", "#566573"
        badges.append(
            f'<span class="agenda-badge" style="background:{bg};color:{col}">'
            f'<b>{e["ticker"]}</b> <span style="opacity:.7">{e["date"][5:]}</span> '
            f'<span class="agenda-tag">{label}</span></span>'
        )
    return '<div class="agenda-row">' + "".join(badges) + "</div>"


def render_alert_row(pos, analysis, link, macro_note):
    ticker = pos["ticker"]
    pct = pos["pct"]
    sent = analysis.get("sentiment", "NEUTRAAL")
    sent_css = SENTIMENT_CSS.get(sent, SENTIMENT_CSS["NEUTRAAL"])
    color = badge_color(ticker)
    pct_str = f"{pct:.1f}".replace(".", ",")
    wat = analysis.get("wat") or macro_note or "—"
    adv = analysis.get("advies") or "—"
    link_btn = f'<a href="{link}" class="btn-link">bericht</a>' if link and link != "#" else ""
    return f"""<tr>
  <td><span class="tbadge" style="background:{color}">{ticker}</span>
      <span class="td-name">{pos['name']}</span></td>
  <td class="td-pct">{pct_str}%</td>
  <td><span class="sent" style="{sent_css}">{sent}</span></td>
  <td class="td-wat">{wat}</td>
  <td class="td-adv">{adv}</td>
  <td>{link_btn}</td>
</tr>"""


def render_watch_item(item):
    ticker = item.get("ticker", "")
    pct = item.get("pct", "")
    cat = item.get("categorie", "")
    cat_str = f" — {cat}" if cat else ""
    desc = item.get("beschrijving", "")
    actie = item.get("actie", "")
    return (f'<div class="watch-item">'
            f'<span class="watch-ticker">{ticker} ({pct}%){cat_str}:</span> '
            f'{desc} {actie}</div>')


CSS = """
body{font-family:Arial,Helvetica,sans-serif;background:#e8e8e8;margin:0;padding:16px}
.wrap{max-width:680px;margin:0 auto;background:#fff;border-radius:4px;overflow:hidden}
.header{background:#1c2340;color:#fff;padding:20px 24px}
.header h1{margin:0 0 4px;font-size:20px;font-weight:700;letter-spacing:-.3px}
.header p{margin:0;font-size:12px;opacity:.65}
.indices{display:table;width:100%;border-collapse:collapse;border-bottom:1px solid #eee}
.ix{display:table-cell;padding:14px 18px;border-right:1px solid #eee;vertical-align:top}
.ix:last-child{border-right:none}
.ix-label{font-size:10px;color:#999;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.ix-val{font-size:20px;font-weight:700;color:#1c2340;letter-spacing:-.5px}
.ix-chg{font-size:12px;font-weight:600;margin-top:2px}
.green{color:#1d8348}.red{color:#c0392b}
.macro-bar{display:flex;flex-wrap:wrap;gap:0;background:#f8f9fa;
           border-bottom:2px solid #eee;padding:8px 18px}
.mb-item{display:flex;align-items:baseline;gap:5px;padding:2px 10px 2px 0}
.mb-sep{color:#ddd;margin:0 4px;align-self:center}
.mb-label{font-size:9px;color:#aaa;text-transform:uppercase;letter-spacing:.08em}
.mb-val{font-size:13px;font-weight:700;color:#1c2340}
.mb-sub{font-size:10px;color:#888}
.content{padding:4px 24px 24px}
h2{font-size:10px;font-weight:700;letter-spacing:.12em;color:#999;
   text-transform:uppercase;margin:20px 0 10px;
   border-bottom:1px solid #eee;padding-bottom:6px}
.day-summary{background:#f4f6fb;border-left:4px solid #1c2340;
             padding:12px 16px;margin:14px 0 4px;border-radius:0 4px 4px 0;
             font-size:13px;color:#333;line-height:1.65}
.snapshot-row{display:flex;flex-wrap:wrap;gap:5px;margin:4px 0 8px}
.snap-chip{font-size:10px;font-weight:700;padding:3px 7px;border-radius:10px;
           white-space:nowrap;letter-spacing:-.01em}
.sector-row{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:4px}
.sector-chip{font-size:11px;font-weight:600;padding:3px 8px;border-radius:10px;white-space:nowrap}
.agenda-row{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:4px}
.agenda-badge{font-size:11px;padding:4px 9px;border-radius:4px;white-space:nowrap}
.agenda-tag{font-size:9px;font-weight:700;text-transform:uppercase;margin-left:4px;opacity:.85}
.news-item{margin-bottom:13px}
.news-title{font-weight:700;color:#1c2340;font-size:13px;margin-bottom:3px}
.news-body{color:#444;font-size:12px;line-height:1.55;margin-bottom:3px}
.news-src{color:#aaa;font-size:11px}
.news-src a{color:#aaa;text-decoration:none}
.news-src a:hover{text-decoration:underline}
table.pt{width:100%;border-collapse:collapse;font-size:11px}
table.pt th{text-align:left;font-size:9px;font-weight:700;color:#aaa;
            text-transform:uppercase;letter-spacing:.08em;
            border-bottom:2px solid #eee;padding:5px 6px 5px 0}
table.pt td{padding:7px 6px 7px 0;border-bottom:1px solid #f4f4f4;vertical-align:top}
.tbadge{display:inline-block;color:#fff;font-size:9px;font-weight:700;
        padding:2px 6px;border-radius:3px;white-space:nowrap;margin-right:4px}
.td-name{color:#888;font-size:10px}
.sent{display:inline-block;font-size:9px;font-weight:700;
      padding:2px 6px;border-radius:3px;white-space:nowrap}
.td-pct{color:#777;white-space:nowrap}
.td-wat{color:#333;font-size:11px;line-height:1.4;max-width:220px}
.td-adv{color:#333;font-size:11px;line-height:1.4;max-width:160px}
.btn-link{display:inline-block;font-size:9px;color:#555;border:1px solid #d0d0d0;
           padding:2px 7px;border-radius:3px;text-decoration:none;white-space:nowrap}
.btn-link:hover{background:#f4f4f4}
.watchbox{background:#f8f9fa;border-left:4px solid #1c2340;
           padding:13px 16px;margin-top:8px;border-radius:0 4px 4px 0}
.watch-item{font-size:12px;color:#333;line-height:1.6;margin-bottom:10px}
.watch-item:last-child{margin-bottom:0}
.watch-ticker{font-weight:700;color:#1c2340}
.footer{border-top:1px solid #eee;padding:12px 24px;font-size:11px;
        color:#bbb;text-align:center}
"""


def generate_html(data, portfolio_analyses, watchlist, day_summary):
    today = today_long()
    indices = data.get("indices", {})
    macro = data.get("macro", {})
    market_news = data.get("market_news", [])
    portfolio = data.get("portfolio", [])
    portfolio_news = data.get("portfolio_news", {})
    sectors = data.get("sectors", {})
    earnings = data.get("earnings_agenda", [])
    prices = data.get("portfolio_prices", {})
    extremes_52w = data.get("extremes_52w", {})

    index_html = "".join(render_index(k, indices.get(k)) for k in ("sp500", "nasdaq", "aex"))
    macro_html = render_macro_bar(macro)

    summary_block = (
        f'<div class="day-summary">{day_summary}</div>'
        if day_summary else ""
    )

    snapshot_html = render_portfolio_snapshot(portfolio, prices, extremes_52w)
    snapshot_section = (
        f'<h2>Portfolio — Vandaag</h2>{snapshot_html}'
        if snapshot_html else ""
    )

    sector_html = render_sectors(sectors)
    sector_section = f'<h2>Sectorrotatie</h2>{sector_html}' if sector_html else ""

    agenda_html = render_agenda(earnings)
    agenda_section = f'<h2>Agenda deze week</h2>{agenda_html}' if agenda_html else ""

    if market_news:
        news_html = "\n".join(
            f'<div class="news-item">'
            f'<div class="news-title">{n["title"]}</div>'
            f'<div class="news-body">{n.get("summary") or n["title"]}</div>'
            f'<div class="news-src">{n.get("source", "")} &mdash; '
            f'<a href="{n.get("link","#")}">lees meer</a></div>'
            f'</div>'
            for n in market_news[:5]
        )
    else:
        news_html = '<p style="color:#aaa;font-size:12px">Geen significant marktnieuws vandaag.</p>'

    # Alert table: positions with news OR significant signals
    rows = []
    shown = set()
    for pos in portfolio:
        ticker = pos["ticker"]
        analysis = portfolio_analyses.get(ticker, {})
        link = portfolio_news.get(ticker, {}).get("link", "")
        macro_note = macro_context_for_position(ticker, sectors, prices, extremes_52w)

        in_news = ticker in portfolio_news
        has_analysis = bool(analysis.get("wat"))
        has_macro_note = bool(macro_note)

        if in_news or has_analysis or has_macro_note:
            rows.append(render_alert_row(pos, analysis, link, macro_note))
            shown.add(ticker)

    if rows:
        alert_section = f"""<h2>Posities om te volgen</h2>
<table class="pt">
<thead><tr>
  <th>Positie</th><th>%</th><th>Sentiment</th><th>Bevinding</th><th>Actie</th><th></th>
</tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>"""
    else:
        alert_section = (
            '<h2>Posities om te volgen</h2>'
            '<p style="color:#aaa;font-size:12px">Geen bijzonderheden in het portfolio vandaag.</p>'
        )

    watch_section = ""
    if watchlist:
        watch_items = "\n".join(render_watch_item(w) for w in watchlist)
        watch_section = f'<h2>Vandaag in de gaten houden</h2><div class="watchbox">{watch_items}</div>'

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dagelijkse beursupdate</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<div class="header">
  <h1>Dagelijkse beursupdate</h1>
  <p>{today}</p>
</div>

<div class="indices">
{index_html}
</div>

{macro_html}

<div class="content">

{summary_block}

{snapshot_section}

{sector_section}

{agenda_section}

<h2>Marktoverzicht</h2>
{news_html}

{alert_section}

{watch_section}

</div>

<div class="footer">
  Volgende update: morgen 08:00 CEST &nbsp;&bull;&nbsp; alfendirk@gmail.com
</div>

</div>
</body>
</html>
"""


def main():
    with open("data/market_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    client = get_client()
    portfolio_news = data.get("portfolio_news", {})
    sectors = data.get("sectors", {})
    market_news = data.get("market_news", [])
    portfolio = data.get("portfolio", [])
    indices = data.get("indices", {})
    macro = data.get("macro", {})
    earnings = data.get("earnings_agenda", [])
    prices = data.get("portfolio_prices", {})
    extremes_52w = data.get("extremes_52w", {})

    print("AI-samenvatting marktnieuws...")
    summarize_market_news(client, market_news)

    print(f"AI-analyse posities met nieuws ({len(portfolio_news)})...")
    portfolio_analyses = analyze_positions_with_news(
        client, portfolio_news, sectors, market_news
    )

    print("AI-dagsamenvatting...")
    time.sleep(1)
    day_summary = generate_day_summary(
        client, indices, macro, sectors, market_news,
        portfolio_news, earnings, prices
    )
    if day_summary:
        print(f"  OK ({len(day_summary)} tekens)")
    else:
        print("  Mislukt — geen dagsamenvatting")

    print("Watchlist genereren...")
    time.sleep(1)
    watchlist = build_watchlist(
        client, portfolio_news, portfolio_analyses,
        market_news, sectors, prices, extremes_52w
    )
    print(f"  In de gaten houden: {[w.get('ticker') for w in watchlist]}")

    print("Genereren email_final.html...")
    html = generate_html(data, portfolio_analyses, watchlist, day_summary)
    with open("email_final.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ email_final.html aangemaakt")


if __name__ == "__main__":
    main()
