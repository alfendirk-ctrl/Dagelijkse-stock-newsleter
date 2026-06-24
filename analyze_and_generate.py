#!/usr/bin/env python3
"""
Stap 2: analyseert nieuws via GitHub Models (gpt-4o-mini) en genereert email_final.html.
Vereist: GITHUB_TOKEN env var.
"""

import json
import os
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

DEFAULT_ANALYSIS = {
    "sentiment": "NEUTRAAL",
    "wat": "Geen materieel nieuws vandaag.",
    "advies": "HOLD — Geen actie vereist.",
}


def get_client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN niet gevonden")
    return OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)


def chat(client, prompt, max_tokens=200):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  GitHub Models fout: {e}")
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


def summarize_market_news(client, news_items):
    """Batch-summarize all market news in one AI call."""
    if not news_items:
        return
    lines = []
    for i, n in enumerate(news_items, 1):
        lines.append(f"{i}. TITEL: {n['title']}\n   INHOUD: {(n.get('content') or '')[:500]}")

    raw = chat(client, (
        "Geef voor elk bericht hieronder een bondige samenvatting (2-3 zinnen, Nederlands). "
        "Focus op wat het betekent voor een particuliere belegger. "
        "Wees direct en concreet. Begin meteen met de kern.\n"
        "Antwoord uitsluitend met een JSON-array (geen uitleg, geen markdown):\n"
        '[{"index":1,"samenvatting":"..."},{"index":2,"samenvatting":"..."}]\n\n'
        + "\n\n".join(lines)
    ), max_tokens=600)

    result = extract_json(raw, array=True)
    if result:
        mapping = {item.get("index"): item.get("samenvatting") for item in result}
        for i, n in enumerate(news_items, 1):
            if mapping.get(i):
                n["summary"] = mapping[i]


def analyze_portfolio_batch(client, portfolio, portfolio_news, sectors, market_news):
    """Single AI call analyzing all positions with macro + sector context."""
    sector_lines = []
    if sectors:
        sorted_sectors = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, s in sorted_sectors:
            arrow = "▲" if s["change_pct"] >= 0 else "▼"
            sector_lines.append(f"  {name}: {arrow}{abs(s['change_pct']):.2f}%")

    macro_context = "SECTORPRESTATIES VANDAAG:\n" + "\n".join(sector_lines) if sector_lines else ""
    if market_news:
        macro_context += "\n\nMARKTNIEUWS:\n" + "\n".join(
            f"- {n['title']}" for n in market_news[:3]
        )

    positions_lines = []
    for pos in portfolio:
        ticker = pos["ticker"]
        news = portfolio_news.get(ticker)
        if news:
            positions_lines.append(
                f"- {ticker} ({pos['pct']}%): [NIEUWS] {news['title']}"
            )
        else:
            positions_lines.append(f"- {ticker} ({pos['pct']}%): [geen eigen nieuws]")

    raw = chat(client, (
        "Je bent een ervaren beleggingsadviseur. Analyseer alle onderstaande portfolio-posities.\n"
        "Voor posities MET nieuws: analyseer dat specifieke nieuws.\n"
        "Voor posities ZONDER nieuws: beoordeel op basis van de macro-context en sectorrotatie.\n\n"
        + macro_context + "\n\nPORTFOLIO-POSITIES:\n" + "\n".join(positions_lines) + "\n\n"
        "Antwoord uitsluitend met een JSON-array voor ELKE positie (geen uitleg, geen markdown):\n"
        '[{"ticker":"AAPL","sentiment":"BULLISH of BEARISH of NEUTRAAL",'
        '"wat":"1-2 zinnen wat er speelt",'
        '"advies":"HOLD/MONITOR/BUY/SELL — 1 zin reden"}]'
    ), max_tokens=4000)

    result = extract_json(raw, array=True)
    analyses = {}
    if result:
        for item in result:
            ticker = item.get("ticker", "").upper()
            sent = str(item.get("sentiment", "NEUTRAAL")).upper()
            if sent not in SENTIMENT_CSS:
                sent = "NEUTRAAL"
            analyses[ticker] = {
                "sentiment": sent,
                "wat": item.get("wat", DEFAULT_ANALYSIS["wat"]),
                "advies": item.get("advies", DEFAULT_ANALYSIS["advies"]),
            }
    return analyses


def build_watchlist(client, portfolio_news, market_news, sectors=None):
    """Ask AI to pick top 3 positions to watch today."""
    lines = [f"- {t} ({i['pct']}%): {i['title']}" for t, i in portfolio_news.items()]

    if market_news:
        lines += ["\nMarktnieuws:"] + [f"- {n['title']}" for n in market_news[:3]]

    if sectors:
        sorted_s = sorted(sectors.items(), key=lambda x: abs(x[1]["change_pct"]), reverse=True)
        top_movers = [f"{name} {'+' if s['change_pct']>=0 else ''}{s['change_pct']:.1f}%"
                      for name, s in sorted_s[:3]]
        lines += ["\nSterkste sectorbewegingen vandaag: " + ", ".join(top_movers)]

    if not lines:
        return []

    raw = chat(client, (
        "Je bent een beleggingsadviseur. Welke 3 portfolio-posities verdienen vandaag "
        "de meeste aandacht op basis van dit nieuws en de sectorbeweging? "
        "Antwoord uitsluitend met een JSON-array (geen uitleg, geen markdown):\n"
        '[{"ticker":"COIN","pct":7.6,"categorie":"Crypto",'
        '"beschrijving":"2-3 zinnen wat er speelt",'
        '"actie":"concrete actie voor vandaag"}]\n\n'
        "Kies precies 3 posities:\n" + "\n".join(lines)
    ), max_tokens=500)

    result = extract_json(raw, array=True)
    return result[:3] if result else []


# ── HTML helpers ──────────────────────────────────────────────────────────────

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
        sign = "+" if chg >= 0 else ""
        chips.append(
            f'<span class="sector-chip" style="background:{bg};color:{col}">'
            f'{name} {arrow}{sign}{chg:.2f}%</span>'
        )
    return '<div class="sector-row">' + "".join(chips) + "</div>"


def render_agenda(earnings):
    if not earnings:
        return ""
    badges = []
    for e in earnings:
        days = e.get("days_away", 0)
        if days == 0:
            label = "VANDAAG"
            bg, col = "#fdebd0", "#935116"
        elif days == 1:
            label = "MORGEN"
            bg, col = "#fef9e7", "#9a7d0a"
        else:
            label = f"over {days}d"
            bg, col = "#eaecee", "#566573"
        badges.append(
            f'<span class="agenda-badge" style="background:{bg};color:{col}">'
            f'<b>{e["ticker"]}</b> <span style="opacity:.7">{e["date"][5:]}</span> '
            f'<span class="agenda-tag">{label}</span></span>'
        )
    return '<div class="agenda-row">' + "".join(badges) + "</div>"


def render_portfolio_row(pos, analysis, link):
    ticker = pos["ticker"]
    pct = pos["pct"]
    sent = analysis.get("sentiment", "NEUTRAAL")
    sent_css = SENTIMENT_CSS.get(sent, SENTIMENT_CSS["NEUTRAAL"])
    color = badge_color(ticker)
    pct_str = f"{pct:.1f}".replace(".", ",")
    return f"""<tr>
  <td><span class="tbadge" style="background:{color}">{ticker}</span></td>
  <td class="td-name">{pos['name']}</td>
  <td class="td-pct">{pct_str}%</td>
  <td><span class="sent" style="{sent_css}">{sent}</span></td>
  <td class="td-wat">{analysis.get('wat', '—')}</td>
  <td class="td-adv">{analysis.get('advies', '—')}</td>
  <td><a href="{link or '#'}" class="btn-link">bericht</a></td>
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
.indices{display:table;width:100%;border-collapse:collapse;border-bottom:2px solid #eee}
.ix{display:table-cell;padding:16px 20px;border-right:1px solid #eee;vertical-align:top}
.ix:last-child{border-right:none}
.ix-label{font-size:10px;color:#999;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.ix-val{font-size:21px;font-weight:700;color:#1c2340;letter-spacing:-.5px}
.ix-chg{font-size:12px;font-weight:600;margin-top:3px}
.green{color:#1d8348}.red{color:#c0392b}
.content{padding:4px 24px 24px}
h2{font-size:10px;font-weight:700;letter-spacing:.12em;color:#999;
   text-transform:uppercase;margin:22px 0 10px;
   border-bottom:1px solid #eee;padding-bottom:7px}
.sector-row{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}
.sector-chip{font-size:11px;font-weight:600;padding:4px 9px;border-radius:12px;white-space:nowrap}
.agenda-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:4px}
.agenda-badge{font-size:11px;padding:5px 10px;border-radius:4px;white-space:nowrap}
.agenda-tag{font-size:9px;font-weight:700;text-transform:uppercase;
            margin-left:4px;opacity:.85}
.news-item{margin-bottom:14px}
.news-title{font-weight:700;color:#1c2340;font-size:13px;margin-bottom:4px}
.news-body{color:#444;font-size:12px;line-height:1.55;margin-bottom:4px}
.news-src{color:#aaa;font-size:11px}
.news-src a{color:#aaa;text-decoration:none}
.news-src a:hover{text-decoration:underline}
table.pt{width:100%;border-collapse:collapse;font-size:11px}
table.pt th{text-align:left;font-size:9px;font-weight:700;color:#aaa;
            text-transform:uppercase;letter-spacing:.08em;
            border-bottom:2px solid #eee;padding:5px 6px 5px 0}
table.pt td{padding:7px 6px 7px 0;border-bottom:1px solid #f4f4f4;vertical-align:top}
.tbadge{display:inline-block;color:#fff;font-size:9px;font-weight:700;
        padding:3px 6px;border-radius:3px;white-space:nowrap}
.sent{display:inline-block;font-size:9px;font-weight:700;
      padding:3px 6px;border-radius:3px;white-space:nowrap}
.td-name{color:#333;font-weight:500;white-space:nowrap}
.td-pct{color:#777;white-space:nowrap}
.td-wat{color:#333;font-size:11px;line-height:1.4;max-width:200px}
.td-adv{color:#333;font-size:11px;line-height:1.4;max-width:160px}
.btn-link{display:inline-block;font-size:9px;color:#555;border:1px solid #d0d0d0;
           padding:3px 7px;border-radius:3px;text-decoration:none;white-space:nowrap}
.btn-link:hover{background:#f4f4f4}
.watchbox{background:#f8f9fa;border-left:4px solid #1c2340;
           padding:14px 16px;margin-top:8px;border-radius:0 4px 4px 0}
.watch-item{font-size:12px;color:#333;line-height:1.55;margin-bottom:10px}
.watch-item:last-child{margin-bottom:0}
.watch-ticker{font-weight:700;color:#1c2340}
.footer{border-top:1px solid #eee;padding:13px 24px;font-size:11px;
        color:#bbb;text-align:center}
"""


def generate_html(data, portfolio_analyses, watchlist):
    today = today_long()
    indices = data.get("indices", {})
    market_news = data.get("market_news", [])
    portfolio = data.get("portfolio", [])
    portfolio_news = data.get("portfolio_news", {})
    sectors = data.get("sectors", {})
    earnings = data.get("earnings_agenda", [])

    index_html = "".join(render_index(k, indices.get(k)) for k in ("sp500", "nasdaq", "aex"))

    # Sector rotation
    sector_html = render_sectors(sectors)
    sector_section = (
        f'<h2>Sectorrotatie</h2>{sector_html}'
        if sector_html else ""
    )

    # Earnings agenda
    agenda_html = render_agenda(earnings)
    agenda_section = (
        f'<h2>Agenda deze week</h2>{agenda_html}'
        if agenda_html else ""
    )

    # Market news
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

    # Portfolio rows (all positions)
    rows = []
    for pos in portfolio:
        ticker = pos["ticker"]
        analysis = portfolio_analyses.get(ticker, DEFAULT_ANALYSIS.copy())
        link = portfolio_news.get(ticker, {}).get("link", "#")
        rows.append(render_portfolio_row(pos, analysis, link))
    portfolio_html = "\n".join(rows)

    # Watchlist
    if watchlist:
        watch_items = "\n".join(render_watch_item(w) for w in watchlist)
        watch_section = f'<h2>Vandaag in de gaten houden</h2><div class="watchbox">{watch_items}</div>'
    else:
        watch_section = ""

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

<div class="content">

{sector_section}

{agenda_section}

<h2>Marktoverzicht</h2>
{news_html}

<h2>Portfolio &mdash; Analyse</h2>
<table class="pt">
<thead><tr>
  <th>Ticker</th><th>Naam</th><th>%</th>
  <th>Sentiment</th><th>Wat</th><th>Advies</th><th></th>
</tr></thead>
<tbody>
{portfolio_html}
</tbody>
</table>

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

    print("AI-analyse marktnieuws (batch)...")
    summarize_market_news(client, market_news)

    print(f"AI-analyse portfolio (batch, {len(portfolio)} posities)...")
    portfolio_analyses = analyze_portfolio_batch(
        client, portfolio, portfolio_news, sectors, market_news
    )
    print(f"  Ontvangen analyses: {len(portfolio_analyses)}")

    # Fill missing tickers with default
    for pos in portfolio:
        if pos["ticker"] not in portfolio_analyses:
            portfolio_analyses[pos["ticker"]] = DEFAULT_ANALYSIS.copy()

    print("Genereren watchlist...")
    watchlist = build_watchlist(client, portfolio_news, market_news, sectors)
    print(f"  In de gaten houden: {[w.get('ticker') for w in watchlist]}")

    print("Genereren email_final.html...")
    html = generate_html(data, portfolio_analyses, watchlist)
    with open("email_final.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ email_final.html aangemaakt")


if __name__ == "__main__":
    main()
