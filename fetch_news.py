#!/usr/bin/env python3
"""
Stap 1: haalt koersen, sectordata, earnings-agenda en nieuws op.
Slaat resultaat op in data/market_data.json voor de volgende stap.
"""

import json
import os
import re
import feedparser
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

INDICES = {
    "sp500":  {"ticker": "^GSPC", "name": "S&P 500"},
    "nasdaq": {"ticker": "^IXIC", "name": "Nasdaq"},
    "aex":    {"ticker": "^AEX",  "name": "AEX"},
}

# SPDR sector ETFs (US market)
SECTOR_ETFS = {
    "Technologie":   "XLK",
    "Communicatie":  "XLC",
    "Cons. discr.":  "XLY",
    "Financieel":    "XLF",
    "Zorg":          "XLV",
    "Industrie":     "XLI",
    "Energie":       "XLE",
    "Cons. basis":   "XLP",
    "Grondstoffen":  "XLB",
    "Vastgoed":      "XLRE",
    "Nutsbedrijven": "XLU",
}

MARKET_FEEDS = [
    ("https://news.google.com/rss/topics/CAAqJAgKIh5CVVNIX0dveHZSRkFTVkhRPQ?hl=en&gl=US&ceid=US:en",
     "Google News"),
    ("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch"),
    ("https://feeds.reuters.com/reuters/businessNews", "Reuters"),
]

MARKET_RELEVANCE_WORDS = [
    "stock", "market", "shares", "trading", "investor", "fed", "federal reserve",
    "interest rate", "inflation", "economy", "gdp", "earnings", "revenue", "profit",
    "loss", "index", "dow", "nasdaq", "s&p", "oil", "gold", "bond", "yield",
    "recession", "growth", "ipo", "acquisition", "merger", "dividend", "buyback",
    "central bank", "ecb", "fomc", "cpi", "pce", "jobs report", "employment",
    "beurs", "koers", "rente", "aandelen", "economie",
]

MATERIAL_KEYWORDS = [
    "earnings beat", "earnings miss", "beat estimates", "missed estimates",
    "guidance raised", "guidance lowered", "outlook increased", "outlook cut",
    "ceo resigns", "ceo replaced", "new ceo", "new cfo",
    "acquisition", "merger", "acquired by", "buyout",
    "bankruptcy", "restructuring",
    "analyst upgrade", "analyst downgrade", "price target",
    "lawsuit", "sec investigation", "regulatory",
    "dividend increase", "dividend cut", "stock split",
    "product launch", "major deal", "partnership", "contract win",
]


def load_portfolio():
    with open("portfolio.json", "r") as f:
        return json.load(f)["portfolio"]


def now_utc():
    return datetime.now(timezone.utc)


def fetch_index(ticker, name):
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        hist = hist[hist["Volume"] > 0]
        if len(hist) >= 2:
            prev, curr = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
            change_pct = ((curr - prev) / prev) * 100
        elif len(hist) == 1:
            curr = hist["Close"].iloc[-1]
            change_pct = 0.0
        else:
            return None
        return {"name": name, "ticker": ticker,
                "price": round(float(curr), 2),
                "change_pct": round(float(change_pct), 2)}
    except Exception as e:
        print(f"  Fout bij ophalen {ticker}: {e}")
        return None


def fetch_sector_performance():
    """Fetch % change for each SPDR sector ETF."""
    results = {}
    tickers = list(SECTOR_ETFS.values())
    try:
        data = yf.download(tickers, period="2d", progress=False, auto_adjust=True)
        close = data["Close"]
        for name, etf in SECTOR_ETFS.items():
            try:
                col = close[etf].dropna()
                if len(col) >= 2:
                    chg = ((col.iloc[-1] - col.iloc[-2]) / col.iloc[-2]) * 100
                    results[name] = {"etf": etf, "change_pct": round(float(chg), 2)}
                elif len(col) == 1:
                    results[name] = {"etf": etf, "change_pct": 0.0}
            except Exception:
                pass
    except Exception as e:
        print(f"  Fout bij sectoren: {e}")
    return results


def fetch_earnings_calendar(portfolio, days_ahead=7):
    """Fetch upcoming earnings dates for portfolio stocks."""
    upcoming = []
    today = now_utc().date()
    cutoff = today + timedelta(days=days_ahead)

    for pos in portfolio:
        ticker = pos["ticker"]
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None:
                continue

            # yfinance returns calendar as dict or DataFrame depending on version
            if hasattr(cal, "to_dict"):
                cal = cal.to_dict()

            # Try to extract earnings date
            earn_date = None
            if isinstance(cal, dict):
                for key in ("Earnings Date", "earningsDate"):
                    val = cal.get(key)
                    if val is not None:
                        if hasattr(val, "__iter__") and not isinstance(val, str):
                            val = list(val)
                            if val:
                                val = val[0]
                        if hasattr(val, "date"):
                            earn_date = val.date()
                        elif isinstance(val, str):
                            try:
                                earn_date = datetime.strptime(val[:10], "%Y-%m-%d").date()
                            except Exception:
                                pass
                        break

            if earn_date and today <= earn_date <= cutoff:
                upcoming.append({
                    "ticker": ticker,
                    "company": pos["name"],
                    "pct": pos["pct"],
                    "date": earn_date.isoformat(),
                    "days_away": (earn_date - today).days,
                })
        except Exception:
            pass

    upcoming.sort(key=lambda x: x["date"])
    return upcoming


def fetch_article(url):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))
        return text[:2500] if len(text) > 120 else None
    except Exception:
        return None


def _is_market_relevant(title):
    tl = title.lower()
    return any(kw in tl for kw in MARKET_RELEVANCE_WORDS)


def fetch_market_news():
    items = []
    for url, source in MARKET_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                pd = entry.get("published_parsed")
                if not pd:
                    continue
                pub = datetime(*pd[:6], tzinfo=timezone.utc)
                if now_utc() - pub > timedelta(hours=24):
                    continue
                title = re.sub(
                    r"\s*[-–]\s*(Reuters|Bloomberg|MarketWatch|Google News|AP|AFP|Yahoo|CNBC).*$",
                    "", entry.title.strip(), flags=re.IGNORECASE,
                )
                if not _is_market_relevant(title):
                    continue
                link = entry.get("link", "")
                items.append({
                    "title": title,
                    "link": link,
                    "source": source,
                    "content": fetch_article(link),
                    "date": pub.isoformat(),
                })
        except Exception as e:
            print(f"  Fout bij {source}: {e}")

    seen, unique = set(), []
    for item in items:
        if item["title"] not in seen:
            seen.add(item["title"])
            unique.append(item)
            if len(unique) >= 5:
                break
    return unique


def fetch_portfolio_news(portfolio):
    results = {}
    for pos in portfolio:
        ticker = pos["ticker"]
        name = pos["name"]
        try:
            feed = feedparser.parse(
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}"
            )
            for entry in feed.entries[:3]:
                pd = entry.get("published_parsed")
                if not pd:
                    continue
                pub = datetime(*pd[:6], tzinfo=timezone.utc)
                if now_utc() - pub > timedelta(hours=24):
                    continue
                if any(kw in entry.title.lower() for kw in MATERIAL_KEYWORDS):
                    link = entry.get("link", "")
                    results[ticker] = {
                        "ticker": ticker,
                        "company": name,
                        "pct": pos["pct"],
                        "title": entry.title,
                        "link": link,
                        "content": fetch_article(link) if link else None,
                    }
                    break
        except Exception:
            pass
    return results


def main():
    os.makedirs("data", exist_ok=True)
    portfolio = load_portfolio()

    print("Ophalen indices...")
    indices = {k: fetch_index(v["ticker"], v["name"]) for k, v in INDICES.items()}
    for k, v in indices.items():
        if v:
            arrow = "▲" if v["change_pct"] >= 0 else "▼"
            print(f"  {v['name']}: {v['price']} {arrow}{abs(v['change_pct']):.2f}%")

    print("Ophalen sectorprestaties...")
    sectors = fetch_sector_performance()
    print(f"  {len(sectors)} sectoren opgehaald")

    print("Ophalen earnings-agenda...")
    earnings = fetch_earnings_calendar(portfolio, days_ahead=7)
    print(f"  {len(earnings)} earnings komende week: {[e['ticker'] for e in earnings]}")

    print("Ophalen marktnieuws...")
    market_news = fetch_market_news()
    print(f"  {len(market_news)} berichten gevonden")

    print("Ophalen portfolionieuws...")
    portfolio_news = fetch_portfolio_news(portfolio)
    print(f"  {len(portfolio_news)} portfolio-alerts: {list(portfolio_news.keys())}")

    with open("data/market_data.json", "w", encoding="utf-8") as f:
        json.dump({
            "date": now_utc().isoformat(),
            "indices": indices,
            "sectors": sectors,
            "earnings_agenda": earnings,
            "market_news": market_news,
            "portfolio_news": portfolio_news,
            "portfolio": portfolio,
        }, f, indent=2, ensure_ascii=False)

    print("✅ data/market_data.json opgeslagen")


if __name__ == "__main__":
    main()
