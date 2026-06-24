#!/usr/bin/env python3
"""
Stap 2: analyseert nieuws via GitHub Models (gpt-4o-mini) en genereert email_final.html.
Vereist: GITHUB_TOKEN env var.
"""

import json
import os
from datetime import datetime
from openai import OpenAI

DUTCH_MONTHS = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}


def get_client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN niet gevonden")
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )


def chat(client, messages, max_tokens=200):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  GitHub Models fout: {e}")
        return None


def summarize_market_item(client, title, content):
    return chat(client, [{
        "role": "user",
        "content": (
            "Geef een bondige samenvatting (2-3 zinnen, Nederlands) van dit marktbericht. "
            "Focus op wat het betekent voor een particuliere belegger. Wees direct.\n\n"
            f"Titel: {title}\n\nInhoud: {content or 'Niet beschikbaar'}\n\nSamenvatting:"
        ),
    }], max_tokens=150)


def analyze_stock(client, ticker, company, pct, title, content):
    return chat(client, [{
        "role": "user",
        "content": (
            f"Je bent een beleggingsadviseur. Analyseer dit nieuws over {company} ({ticker}), "
            f"positie {pct}% van portfolio.\n\n"
            f"TITEL: {title}\n\nINHOUD: {content or title}\n\n"
            "Geef analyse in dit exacte format:\n\n"
            "Wat gebeurde: [1 zin]\n\n"
            "Impact: [BULLISH/BEARISH/NEUTRAAL] - [kort waarom]\n\n"
            "Voor jouw positie: [1 zin relevantie]\n\n"
            "Advies: [HOLD/BUY/SELL/MONITOR] - [1 zin]\n\n"
            "Wees praktisch en direct, geen fluff."
        ),
    }], max_tokens=280)


def today_nl():
    n = datetime.now()
    return f"{n.day} {DUTCH_MONTHS[n.month]} {n.year}"


def render_index_card(info):
    if not info:
        return '<div class="index-card"><div class="index-value">N/B</div></div>'
    chg = info["change_pct"]
    color = "#16a34a" if chg >= 0 else "#dc2626"
    arrow = "▲" if chg >= 0 else "▼"
    return (
        f'<div class="index-card">'
        f'<div class="index-name">{info["name"]}</div>'
        f'<div class="index-value">{info["price"]:,.2f}</div>'
        f'<div class="index-change" style="color:{color}">{arrow} {abs(chg):.2f}%</div>'
        f'</div>'
    )


def render_analysis(analysis):
    if not analysis:
        return ""
    rows = []
    for line in analysis.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            label, _, rest = line.partition(":")
            rows.append(
                f'<div class="a-row"><span class="a-label">{label}:</span> {rest.strip()}</div>'
            )
        else:
            rows.append(f'<div class="a-row">{line}</div>')
    return "\n".join(rows)


def generate_html(data, indices):
    today = today_nl()
    market_news = data.get("market_news", [])
    portfolio_news = data.get("portfolio_news", {})

    index_cards = "".join(render_index_card(indices.get(k)) for k in ("sp500", "nasdaq", "aex"))

    # Market news blocks
    if market_news:
        mblocks = []
        for item in market_news[:5]:
            summary = item.get("summary") or item["title"]
            link = item.get("link", "#")
            source = item.get("source", "")
            mblocks.append(
                f'<div class="card">'
                f'<div class="card-title">{item["title"]}</div>'
                f'<div class="card-body">{summary}</div>'
                f'<div class="card-meta">{source} &nbsp;·&nbsp; <a href="{link}">Lees meer →</a></div>'
                f'</div>'
            )
        market_html = "\n".join(mblocks)
    else:
        market_html = '<p class="empty">Geen significant marktnieuws vandaag.</p>'

    # Portfolio blocks
    if portfolio_news:
        pblocks = []
        for ticker, info in portfolio_news.items():
            analysis_html = render_analysis(info.get("analysis", ""))
            link = info.get("link", "#")
            pblocks.append(
                f'<div class="card">'
                f'<div class="card-title">'
                f'<span class="badge">{ticker}</span> {info["company"]}'
                f'<span class="pct">({info.get("pct", 0)}% portfolio)</span>'
                f'</div>'
                f'<div class="card-body">{info["title"]}</div>'
                f'<div class="analysis">{analysis_html}</div>'
                f'<div class="card-meta"><a href="{link}">Lees originele artikel →</a></div>'
                f'</div>'
            )
        portfolio_html = "\n".join(pblocks)
    else:
        portfolio_html = '<p class="empty">Geen materieel portfolionieuws vandaag.</p>'

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dagelijkse Beursupdate {today}</title>
<style>
  body{{font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#1e293b;
       max-width:640px;margin:0 auto;padding:12px;background:#f8fafc}}
  .header{{background:linear-gradient(135deg,#1e3a5f,#2563eb);color:#fff;
           padding:22px 20px;border-radius:10px;margin-bottom:20px}}
  .header h1{{margin:0 0 4px;font-size:20px}}
  .header p{{margin:0;opacity:.85;font-size:13px}}
  .indices{{display:flex;gap:10px;margin-bottom:22px}}
  .index-card{{flex:1;background:#fff;border:1px solid #e2e8f0;border-radius:8px;
              padding:14px;text-align:center}}
  .index-name{{font-size:10px;color:#64748b;text-transform:uppercase;
               letter-spacing:.06em;margin-bottom:4px}}
  .index-value{{font-size:17px;font-weight:700;color:#1e293b}}
  .index-change{{font-size:12px;margin-top:3px;font-weight:600}}
  h2{{color:#1e3a5f;border-bottom:2px solid #2563eb;padding-bottom:7px;
      font-size:15px;margin:22px 0 14px}}
  .card{{background:#fff;border-left:4px solid #2563eb;border-radius:4px;
         padding:14px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
  .card-title{{font-weight:700;color:#1e293b;font-size:14px;margin-bottom:6px}}
  .card-body{{color:#475569;font-size:13px;margin-bottom:6px}}
  .card-meta{{color:#94a3b8;font-size:11px}}
  .card-meta a{{color:#2563eb;text-decoration:none}}
  .badge{{background:#2563eb;color:#fff;padding:2px 7px;border-radius:4px;
          font-size:11px;font-weight:700}}
  .pct{{font-size:11px;color:#94a3b8;margin-left:6px}}
  .analysis{{background:#eff6ff;border-radius:4px;padding:10px 12px;
             margin:8px 0;font-size:12px;line-height:1.65}}
  .a-row{{margin-bottom:4px}}
  .a-label{{font-weight:700;color:#1d4ed8}}
  .empty{{color:#94a3b8;font-style:italic;font-size:13px}}
  .footer{{color:#94a3b8;font-size:11px;margin-top:24px;padding-top:12px;
           border-top:1px solid #e2e8f0;text-align:center}}
</style>
</head>
<body>
<div class="header">
  <h1>📈 Dagelijkse Beursupdate</h1>
  <p>{today}</p>
</div>

<div class="indices">
{index_cards}
</div>

<h2>📰 Marktnieuws</h2>
{market_html}

<h2>🎯 Portfolio Nieuws</h2>
{portfolio_html}

<div class="footer">
  <p>Update van {today} &nbsp;·&nbsp; Volgende update morgen om 08:00 CEST (werkdagen)</p>
</div>
</body>
</html>
"""


def main():
    with open("data/market_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    client = get_client()

    print("AI-analyse marktnieuws...")
    for item in data.get("market_news", []):
        item["summary"] = summarize_market_item(client, item["title"], item.get("content"))

    print("AI-analyse portfolionieuws...")
    for ticker, info in data.get("portfolio_news", {}).items():
        print(f"  Analyseren: {ticker}")
        info["analysis"] = analyze_stock(
            client, ticker, info["company"], info["pct"],
            info["title"], info.get("content")
        )

    print("Genereren email_final.html...")
    html = generate_html(data, data.get("indices", {}))

    with open("email_final.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("✅ email_final.html aangemaakt")


if __name__ == "__main__":
    main()
