#!/usr/bin/env python3
"""
Stap 1: haalt koersen, sectordata, macro-indicatoren, portfoliokoersen,
earnings-agenda en nieuws op. Slaat op in data/market_data.json.
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

# Some tickers need exchange suffix for yfinance price data
YFINANCE_TICKER_MAP = {
    "VOW3":  "VOW3.DE",
    "ALFEN": "ALFEN.AS",
    "SHELL": "SHEL",
    "ULVR":  "ULVR.L",
    "VWRL":  "VWRL.L",
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
    "rate hike", "rate cut", "crypto", "bitcoin", "tech", "semiconductor",
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


def fetch_macro_indicators():
    """Fetch VIX (fear index), US 10Y Treasury yield, EUR/USD."""
    MACRO = {
        "vix":    {"ticker": "^VIX",     "name": "VIX",      "decimals": 1},
        "us10y":  {"ticker": "^TNX",     "name": "US 10Y",   "decimals": 2},
        "eurusd": {"ticker": "EURUSD=X", "name": "EUR/USD",  "decimals": 4},
    }
    results = {}
    for key, info in MACRO.items():
        try:
            hist = yf.Ticker(info["ticker"]).history(period="5d")
            # VIX and bonds have zero volume — don't filter by volume
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                curr = float(hist["Close"].iloc[-1])
                results[key] = {
                    "name": info["name"],
                    "value": round(curr, info["decimals"]),
                    "change_pct": round((curr - prev) / prev * 100, 2),
                }
            elif len(hist) == 1:
                results[key] = {
                    "name": info["name"],
                    "value": round(float(hist["Close"].iloc[-1]), info["decimals"]),
                    "change_pct": 0.0,
                }
        except Exception as e:
            print(f"  Fout bij {info['ticker']}: {e}")
    return results


def fetch_portfolio_prices(portfolio):
    """Fetch today's % change for every portfolio position."""
    orig_to_yf = {}
    for pos in portfolio:
        t = pos["ticker"]
        orig_to_yf[t] = YFINANCE_TICKER_MAP.get(t, t)

    valid = [yf_t for yf_t in orig_to_yf.values() if yf_t]
    results = {}
    if not valid:
        return results

    try:
        raw = yf.download(valid, period="5d", progress=False, auto_adjust=True)
        close = raw["Close"] if "Close" in raw else raw

        for orig_t, yf_t in orig_to_yf.items():
            if not yf_t:
                continue
            try:
                if len(valid) == 1:
                    col = close.squeeze().dropna()
                elif yf_t in close.columns:
                    col = close[yf_t].dropna()
                else:
                    continue
                if len(col) >= 2:
                    prev, curr = float(col.iloc[-2]), float(col.iloc[-1])
                    results[orig_t] = round((curr - prev) / prev * 100, 2)
            except Exception:
                pass
    except Exception as e:
        print(f"  Fout bij portfoliokoersen: {e}")
    return results


def fetch_52w_extremes(portfolio):
    """Flag positions near 52-week high or low (within 5%)."""
    alerts = {}
    orig_to_yf = {}
    for pos in portfolio:
        t = pos["ticker"]
        orig_to_yf[t] = YFINANCE_TICKER_MAP.get(t, t)

    valid = [yf_t for yf_t in orig_to_yf.values() if yf_t]
    if not valid:
        return alerts

    try:
        raw = yf.download(valid, period="1y", progress=False, auto_adjust=True)
        close = raw["Close"] if "Close" in raw else raw

        for orig_t, yf_t in orig_to_yf.items():
            if not yf_t:
                continue
            try:
                if len(valid) == 1:
                    col = close.squeeze().dropna()
                elif yf_t in close.columns:
                    col = close[yf_t].dropna()
                else:
                    continue
                if len(col) < 10:
                    continue
                high = float(col.max())
                low = float(col.min())
                curr = float(col.iloc[-1])
                pct_from_high = (curr - high) / high * 100
                pct_from_low = (curr - low) / low * 100
                if pct_from_high >= -5:
                    alerts[orig_t] = {"type": "HIGH", "pct": round(pct_from_high, 1)}
                elif pct_from_low <= 5:
                    alerts[orig_t] = {"type": "LOW", "pct": round(pct_from_low, 1)}
            except Exception:
                pass
    except Exception as e:
        print(f"  Fout bij 52-week extremes: {e}")
    return alerts


def fetch_earnings_calendar(portfolio, days_ahead=7):
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
            if hasattr(cal, "to_dict"):
                cal = cal.to_dict()

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

    print("Ophalen macro-indicatoren (VIX, 10Y, EUR/USD)...")
    macro = fetch_macro_indicators()
    for key, m in macro.items():
        print(f"  {m['name']}: {m['value']} ({m['change_pct']:+.2f}%)")

    print("Ophalen sectorprestaties...")
    sectors = fetch_sector_performance()
    print(f"  {len(sectors)} sectoren opgehaald")

    print("Ophalen portfoliokoersen...")
    portfolio_prices = fetch_portfolio_prices(portfolio)
    print(f"  {len(portfolio_prices)} koersen opgehaald")

    print("Ophalen 52-weeks extremes...")
    extremes_52w = fetch_52w_extremes(portfolio)
    print(f"  {len(extremes_52w)} posities nabij 52w extreme: {list(extremes_52w.keys())}")

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
            "macro": macro,
            "sectors": sectors,
            "portfolio_prices": portfolio_prices,
            "extremes_52w": extremes_52w,
            "earnings_agenda": earnings,
            "market_news": market_news,
            "portfolio_news": portfolio_news,
            "portfolio": portfolio,
        }, f, indent=2, ensure_ascii=False)

    print("✅ data/market_data.json opgeslagen")


if __name__ == "__main__":
    main()
