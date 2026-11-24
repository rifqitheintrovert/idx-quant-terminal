"""Terminal data GLOBAL (menu HOME, ECO, WSENT).

- Indeks saham dunia sampai frontier: indeks lokal Yahoo bila ada, selain itu ETF negara (USD).
- Komoditas: futures Yahoo (informasi; posisi spot lewat ETF, lihat MAKRO).
- Berita dunia: RSS (Google News, CNBC, BBC, FT, Investing, SCMP, MarketWatch), ditandai wilayah & skor leksikon.
- Proyeksi makro per negara: World Bank Global Economic Prospects (PDB) + OECD Economic Outlook
  (PDB, inflasi, pengangguran, suku bunga, transaksi berjalan, fiskal, utang) + WDI (inflasi aktual).
  IMF DataMapper memblokir server GitHub (403) sehingga tidak dipakai.
- Sentimen: skor per indeks negara 0–100 dari harga (persentil 3 tahun) + peluang naik per zona (cek dua paruh).
  Sentimen sektor BEI ada di engine/sectsent.py.
Semua informasi; tidak mengubah sinyal BEI.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import macro as M_

log = logging.getLogger("world")

# iso3, nama, bendera, klasifikasi, wilayah, indeks lokal, nama indeks, ETF (USD), kurs (simbol, True = USD per 1 unit lokal)
COUNTRIES = [
    ("USA", "Amerika Serikat", "🇺🇸", "DM", "Amerika", "^GSPC", "S&P 500", "SPY", None),
    ("CAN", "Kanada", "🇨🇦", "DM", "Amerika", "^GSPTSE", "TSX", "EWC", ("CAD=X", False)),
    ("GBR", "Inggris", "🇬🇧", "DM", "Eropa", "^FTSE", "FTSE 100", "EWU", ("GBPUSD=X", True)),
    ("DEU", "Jerman", "🇩🇪", "DM", "Eropa", "^GDAXI", "DAX", "EWG", ("EURUSD=X", True)),
    ("FRA", "Prancis", "🇫🇷", "DM", "Eropa", "^FCHI", "CAC 40", "EWQ", ("EURUSD=X", True)),
    ("NLD", "Belanda", "🇳🇱", "DM", "Eropa", "^AEX", "AEX", "EWN", ("EURUSD=X", True)),
    ("ESP", "Spanyol", "🇪🇸", "DM", "Eropa", "^IBEX", "IBEX 35", "EWP", ("EURUSD=X", True)),
    ("ITA", "Italia", "🇮🇹", "DM", "Eropa", "FTSEMIB.MI", "FTSE MIB", "EWI", ("EURUSD=X", True)),
    ("CHE", "Swiss", "🇨🇭", "DM", "Eropa", "^SSMI", "SMI", "EWL", ("CHF=X", False)),
    ("SWE", "Swedia", "🇸🇪", "DM", "Eropa", "^OMX", "OMXS30", "EWD", ("SEK=X", False)),
    ("BEL", "Belgia", "🇧🇪", "DM", "Eropa", "^BFX", "BEL 20", "EWK", ("EURUSD=X", True)),
    ("AUT", "Austria", "🇦🇹", "DM", "Eropa", "^ATX", "ATX", "EWO", ("EURUSD=X", True)),
    ("PRT", "Portugal", "🇵🇹", "DM", "Eropa", "PSI20.LS", "PSI", None, ("EURUSD=X", True)),
    ("IRL", "Irlandia", "🇮🇪", "DM", "Eropa", "^ISEQ", "ISEQ", "EIRL", ("EURUSD=X", True)),
    ("DNK", "Denmark", "🇩🇰", "DM", "Eropa", None, None, "EDEN", ("DKK=X", False)),
    ("NOR", "Norwegia", "🇳🇴", "DM", "Eropa", None, None, "NORW", ("NOK=X", False)),
    ("FIN", "Finlandia", "🇫🇮", "DM", "Eropa", None, None, "EFNL", ("EURUSD=X", True)),
    ("JPN", "Jepang", "🇯🇵", "DM", "Asia-Pasifik", "^N225", "Nikkei 225", "EWJ", ("JPY=X", False)),
    ("AUS", "Australia", "🇦🇺", "DM", "Asia-Pasifik", "^AXJO", "ASX 200", "EWA", ("AUDUSD=X", True)),
    ("NZL", "Selandia Baru", "🇳🇿", "DM", "Asia-Pasifik", "^NZ50", "NZX 50", "ENZL", ("NZDUSD=X", True)),
    ("HKG", "Hong Kong", "🇭🇰", "DM", "Asia-Pasifik", "^HSI", "Hang Seng", "EWH", ("HKD=X", False)),
    ("SGP", "Singapura", "🇸🇬", "DM", "Asia-Pasifik", "^STI", "STI", "EWS", ("SGD=X", False)),
    ("ISR", "Israel", "🇮🇱", "DM", "Timur Tengah & Afrika", "^TA125.TA", "TA-125", "EIS", ("ILS=X", False)),
    ("CHN", "China", "🇨🇳", "EM", "Asia-Pasifik", "000001.SS", "Shanghai Comp.", "MCHI", ("CNY=X", False)),
    ("KOR", "Korea Selatan", "🇰🇷", "EM", "Asia-Pasifik", "^KS11", "KOSPI", "EWY", ("KRW=X", False)),
    ("TWN", "Taiwan", "🇹🇼", "EM", "Asia-Pasifik", "^TWII", "TAIEX", "EWT", ("TWD=X", False)),
    ("IND", "India", "🇮🇳", "EM", "Asia-Pasifik", "^NSEI", "Nifty 50", "INDA", ("INR=X", False)),
    ("IDN", "Indonesia", "🇮🇩", "EM", "Asia-Pasifik", "^JKSE", "IHSG", "EIDO", ("IDR=X", False)),
    ("MYS", "Malaysia", "🇲🇾", "EM", "Asia-Pasifik", "^KLSE", "KLCI", "EWM", ("MYR=X", False)),
    ("THA", "Thailand", "🇹🇭", "EM", "Asia-Pasifik", None, None, "THD", ("THB=X", False)),
    ("PHL", "Filipina", "🇵🇭", "EM", "Asia-Pasifik", None, None, "EPHE", ("PHP=X", False)),
    ("BRA", "Brasil", "🇧🇷", "EM", "Amerika", "^BVSP", "Bovespa", "EWZ", ("BRL=X", False)),
    ("MEX", "Meksiko", "🇲🇽", "EM", "Amerika", "^MXX", "IPC", "EWW", ("MXN=X", False)),
    ("CHL", "Chile", "🇨🇱", "EM", "Amerika", None, None, "ECH", ("CLP=X", False)),
    ("PER", "Peru", "🇵🇪", "EM", "Amerika", None, None, "EPU", ("PEN=X", False)),
    ("COL", "Kolombia", "🇨🇴", "EM", "Amerika", None, None, "COLO", ("COP=X", False)),
    ("ZAF", "Afrika Selatan", "🇿🇦", "EM", "Timur Tengah & Afrika", "^J203.JO", "JSE All Share", "EZA", ("ZAR=X", False)),
    ("TUR", "Turki", "🇹🇷", "EM", "Eropa", "XU100.IS", "BIST 100", "TUR", ("TRY=X", False)),
    ("POL", "Polandia", "🇵🇱", "EM", "Eropa", None, None, "EPOL", ("PLN=X", False)),
    ("GRC", "Yunani", "🇬🇷", "EM", "Eropa", "GD.AT", "Athens General", "GREK", ("EURUSD=X", True)),
    ("SAU", "Arab Saudi", "🇸🇦", "EM", "Timur Tengah & Afrika", None, None, "KSA", None),
    ("QAT", "Qatar", "🇶🇦", "EM", "Timur Tengah & Afrika", None, None, "QAT", None),
    ("ARE", "Uni Emirat Arab", "🇦🇪", "EM", "Timur Tengah & Afrika", None, None, "UAE", None),
    ("KWT", "Kuwait", "🇰🇼", "EM", "Timur Tengah & Afrika", None, None, "KWT", None),
    ("VNM", "Vietnam", "🇻🇳", "FM", "Asia-Pasifik", None, None, "VNM", ("VND=X", False)),
    ("ARG", "Argentina", "🇦🇷", "FM", "Amerika", None, None, "ARGT", ("ARS=X", False)),
    ("AFR", "Afrika (keranjang frontier)", "🌍", "FM", "Timur Tengah & Afrika", None, None, "AFK", None),
]
COMMODITIES = [
    ("CL=F", "Minyak WTI", "Energi"), ("BZ=F", "Minyak Brent", "Energi"), ("NG=F", "Gas alam", "Energi"), ("RB=F", "Bensin", "Energi"),
    ("HO=F", "Diesel/heating oil", "Energi"), ("MTF=F", "Batu bara Newcastle", "Energi"),
    ("GC=F", "Emas", "Logam mulia"), ("SI=F", "Perak", "Logam mulia"), ("PL=F", "Platinum", "Logam mulia"), ("PA=F", "Paladium", "Logam mulia"),
    ("HG=F", "Tembaga", "Logam industri"), ("ALI=F", "Aluminium", "Logam industri"), ("TIO=F", "Bijih besi", "Logam industri"),
    ("ZC=F", "Jagung", "Biji-bijian"), ("ZW=F", "Gandum", "Biji-bijian"), ("ZS=F", "Kedelai", "Biji-bijian"), ("ZM=F", "Bungkil kedelai", "Biji-bijian"),
    ("ZL=F", "Minyak kedelai (≈ minyak nabati)", "Biji-bijian"), ("ZO=F", "Oat", "Biji-bijian"), ("ZR=F", "Beras", "Biji-bijian"),
    ("KC=F", "Kopi", "Softs"), ("SB=F", "Gula", "Softs"), ("CC=F", "Kakao", "Softs"), ("CT=F", "Kapas", "Softs"), ("OJ=F", "Jus jeruk", "Softs"),
    ("LE=F", "Sapi hidup", "Ternak"), ("GF=F", "Sapi bakalan", "Ternak"), ("HE=F", "Babi", "Ternak"), ("DC=F", "Susu", "Ternak"),
]
ZONES = [(0, 25, "Takut ekstrem"), (25, 45, "Takut"), (45, 55, "Netral"), (55, 75, "Serakah"), (75, 101, "Serakah ekstrem")]
FEEDS = [
    ("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en", "Google News Bisnis"),
    ("https://news.google.com/rss/search?q=global+markets+stocks+when:2d&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ("https://news.google.com/rss/search?q=central+bank+interest+rate+when:3d&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ("https://news.google.com/rss/search?q=emerging+markets+stocks+when:3d&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ("https://news.google.com/rss/search?q=asia+stocks+markets+when:2d&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ("https://news.google.com/rss/search?q=europe+stocks+markets+when:2d&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ("https://news.google.com/rss/search?q=oil+gold+commodities+prices+when:2d&hl=en-US&gl=US&ceid=US:en", "Google News"),
    ("https://www.cnbc.com/id/100727362/device/rss/rss.html", "CNBC World"), ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "CNBC Finance"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business"), ("https://www.ft.com/world?format=rss", "Financial Times"),
    ("https://www.investing.com/rss/news_25.rss", "Investing.com"), ("https://www.scmp.com/rss/92/feed", "SCMP Business"),
    ("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch"),
]
REGION_KW = {
    "AS": ["u.s.", "us ", "united states", "fed ", "federal reserve", "wall street", "s&p", "nasdaq", "dow", "treasury", "powell", "trump", "america", "american"],
    "Eropa": ["europe", "european", "ecb", "euro ", "eurozone", "germany", "german", "france", "french", "uk ", "britain", "british", "bank of england", "italy", "spain", "eu "],
    "China": ["china", "chinese", "beijing", "yuan", "pboc", "hong kong", "xi jinping", "shanghai"],
    "Jepang": ["japan", "japanese", "boj", "bank of japan", "yen", "nikkei", "tokyo"],
    "Asia": ["asia", "asian", "india", "indian", "korea", "taiwan", "singapore", "malaysia", "thailand", "vietnam", "philippines", "asean", "australia"],
    "Indonesia": ["indonesia", "jakarta", "rupiah", "bank indonesia", "prabowo"],
    "EM": ["emerging market", "emerging-market", "brazil", "mexico", "argentina", "turkey", "south africa", "nigeria", "egypt", "latin america", "frontier"],
    "Timur Tengah": ["middle east", "iran", "israel", "opec", "saudi", "gulf", "qatar", "uae", "dubai"],
    "Komoditas": ["oil", "crude", "brent", "gold", "copper", "commodit", "wheat", "coal", "natural gas", "metal", "nickel", "palm oil"],
    "Bank sentral": ["central bank", "rate cut", "rate hike", "interest rate", "fed ", "ecb", "boj", "pboc", "monetary policy", "inflation"],
}
EXTRA_EN = {"recession": -1.2, "slowdown": -0.8, "crisis": -1.2, "default": -1.0, "tariff": -0.5, "tariffs": -0.5, "war": -0.8, "sanctions": -0.6,
            "selloff": -1.0, "sell-off": -1.0, "rout": -1.2, "tumble": -1.0, "tumbles": -1.0, "slide": -0.7, "slides": -0.7, "fears": -0.7, "worries": -0.6,
            "record": 0.6, "rebound": 0.8, "rebounds": 0.8, "gains": 0.6, "rallies": 0.9, "soars": 1.0, "boost": 0.6, "optimism": 0.8, "easing": 0.4,
            "beat": 0.6, "upgrade": 0.7, "downgrade": -0.7, "layoffs": -0.7, "bankruptcy": -1.2, "inflation": -0.3, "stimulus": 0.6, "cut": 0.1}


def _f(x, d=4):
    try:
        x = float(x)
        return round(x, d) if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _zone(s):
    if s is None or not np.isfinite(s):
        return None
    return next(z for lo, hi, z in ZONES if lo <= s < hi)


def _chg(c: pd.Series, k):
    c = c.dropna()
    return _f(c.iloc[-1] / c.iloc[-1 - k] - 1) if len(c) > k and c.iloc[-1 - k] > 0 else None


def _ytd(c: pd.Series, now):
    c = c.dropna()
    prev = c[c.index < pd.Timestamp(now.year, 1, 1)]
    return _f(c.iloc[-1] / prev.iloc[-1] - 1) if len(prev) and len(c) else None


def _perf(c: pd.Series, now) -> dict | None:
    c = c.dropna()
    if len(c) < 30:
        return None
    ma200 = c.rolling(200).mean().iloc[-1]
    return {"last": _f(c.iloc[-1], 4), "d": str(c.index[-1].date()), "stale": bool((pd.Timestamp(now.date()) - c.index[-1]).days > 10),
            "r1": _chg(c, 1), "r5": _chg(c, 5), "r21": _chg(c, 21), "r63": _chg(c, 63), "ytd": _ytd(c, now), "r252": _chg(c, 252),
            "up": None if not np.isfinite(ma200) else bool(c.iloc[-1] > ma200), "dd": _f(c.iloc[-1] / c.iloc[-252:].max() - 1),
            "sp": [_f(x, 4) for x in c.iloc[-130:].iloc[::3].values]}


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def idx_sentiment(c: pd.Series) -> tuple[pd.Series, dict]:
    """Skor sentimen 0–100 sebuah indeks dari harganya sendiri (persentil 3 tahun ke belakang)."""
    c = c.dropna()
    parts = {"mom": c / c.rolling(125).mean() - 1, "rsi": _rsi(c), "hi": c / c.rolling(252, min_periods=120).max(),
             "vol": -np.log(c).diff().rolling(20).std(), "r20": c / c.shift(20) - 1}
    P = pd.DataFrame({k: v.rolling(756, min_periods=250).rank(pct=True) for k, v in parts.items()})
    return P.mean(axis=1).where(P.notna().sum(axis=1) >= 4) * 100, {k: _f(P[k].iloc[-1] * 100, 1) for k in P}


def zone_stats(score: pd.Series, price: pd.Series, mid=None) -> dict:
    fwd = {k: price.shift(-k) / price - 1 for k in (20, 60)}
    df = pd.DataFrame({"s": score, "f20": fwd[20], "f60": fwd[60]}).dropna(subset=["s"])
    if len(df) < 200:
        return {}
    mid = mid or df.index[len(df) // 2]
    out = {}
    base = {}
    for k in ("f20", "f60"):
        x = df[k].dropna()
        base[k] = {"up": _f((x > 0).mean(), 3), "m": _f(x.mean()), "h": [_f((x[x.index < mid] > 0).mean(), 3), _f((x[x.index >= mid] > 0).mean(), 3)]}
    for lo, hi, z in ZONES:
        sub = df[(df.s >= lo) & (df.s < hi)]
        row = {"n": int(len(sub))}
        for k in ("f20", "f60"):
            x = sub[k].dropna()
            if len(x) < 20:
                continue
            h = [x[x.index < mid], x[x.index >= mid]]
            hu = [(hh > 0).mean() if len(hh) >= 10 else np.nan for hh in h]
            b = base[k]["h"]
            ok = all(np.isfinite(hu[j]) and b[j] is not None for j in (0, 1)) and np.sign(hu[0] - b[0]) == np.sign(hu[1] - b[1]) != 0
            row[k] = {"up": _f((x > 0).mean(), 3), "m": _f(x.mean()), "n": int(len(x)), "h": [_f(hu[0], 3), _f(hu[1], 3)], "ok": bool(ok)}
        out[z] = row
    return {"base": base, "zones": out, "mid": str(mid.date())}


def pooled_zone_stats(scores: dict, prices: dict) -> dict:
    """Gabungan semua indeks negara: return 20/60 hari setelah tiap zona (cek dua paruh)."""
    rows = []
    for k, s in scores.items():
        p = prices[k].reindex(s.index)
        df = pd.DataFrame({"s": s, "f20": p.shift(-20) / p - 1, "f60": p.shift(-60) / p - 1}).dropna(subset=["s"])
        rows.append(df)
    if not rows:
        return {}
    big = pd.concat(rows)
    mid = big.index.sort_values()[len(big) // 2]
    out = {"zones": {}, "mid": str(mid.date()), "n_idx": len(rows)}
    base = {}
    for k in ("f20", "f60"):
        x = big[k].dropna()
        base[k] = {"up": _f((x > 0).mean(), 3), "m": _f(x.mean()), "h": [_f((x[x.index < mid] > 0).mean(), 3), _f((x[x.index >= mid] > 0).mean(), 3)]}
    out["base"] = base
    for lo, hi, z in ZONES:
        sub = big[(big.s >= lo) & (big.s < hi)]
        row = {"n": int(len(sub))}
        for k in ("f20", "f60"):
            x = sub[k].dropna()
            if len(x) < 50:
                continue
            h = [x[x.index < mid], x[x.index >= mid]]
            hu = [(hh > 0).mean() for hh in h]
            b = base[k]["h"]
            row[k] = {"up": _f((x > 0).mean(), 3), "m": _f(x.mean()), "h": [_f(hu[0], 3), _f(hu[1], 3)],
                      "ok": bool(np.sign(hu[0] - b[0]) == np.sign(hu[1] - b[1]) != 0)}
        out["zones"][z] = row
    return out


# ------------------------------------------------------------------ berita
def _score_en(title: str) -> float:
    from . import sentiment as SE
    base = SE.score_text(title)
    toks = re.sub(r"[^a-z0-9\- ]", " ", title.lower()).split()
    ex = sum(EXTRA_EN.get(t, 0) for t in toks)
    return float(np.clip(base + np.tanh(ex / 2.5), -1, 1))


def _regions(title: str) -> list[str]:
    t = " " + title.lower() + " "
    return [r for r, kws in REGION_KW.items() if any(k in t for k in kws)]


def fetch_news(now_utc=None, hours=72, cap=220) -> list[dict]:
    from . import sentiment as SE
    now_utc = now_utc or datetime.now(timezone.utc)
    seen, out = set(), []
    for url, src in FEEDS:
        try:
            items = SE._parse_feed(url)
        except Exception as e:  # noqa: BLE001
            log.info("Berita dunia gagal %s: %s", src, e)
            continue
        for it in items:
            ttl = (it.get("title") or "").strip()
            key = re.sub(r"[^a-z0-9]", "", ttl.lower())[:80]
            if not ttl or key in seen:
                continue
            ts = it.get("ts")
            if ts is None or (now_utc - ts) > timedelta(hours=hours):
                continue
            seen.add(key)
            out.append({"title": ttl, "source": it.get("source") or src, "feed": src, "link": it.get("link", ""), "ts": ts.isoformat(),
                        "score": _f(_score_en(ttl), 2), "reg": _regions(ttl)})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:cap]


def demo_news(now_utc=None) -> list[dict]:
    now_utc = now_utc or datetime.now(timezone.utc)
    T = ["Global stocks rally as inflation cools", "Oil prices slide on demand worries", "Fed signals rates to stay higher for longer",
         "China stimulus boosts Asian markets", "European shares tumble on tariff fears", "Gold hits record as dollar weakens",
         "Emerging markets see inflows as yields ease", "Bank of Japan holds rates, yen slides", "Indonesia rupiah steadies after Bank Indonesia move",
         "Copper rebounds on supply concerns", "Wall Street ends mixed ahead of jobs data", "OPEC+ weighs output cut"]
    return [{"title": "[SIMULASI] " + t, "source": "Demo", "feed": "Demo", "link": "", "ts": (now_utc - timedelta(hours=3 * i)).isoformat(),
             "score": _f(_score_en(t), 2), "reg": _regions(t)} for i, t in enumerate(T)]


# ------------------------------------------------------------------ proyeksi makro
OECD_MEASURES = {"GDPV_ANNPCT": "gdp", "CPI_YTYPCT": "cpi", "UNR": "unr", "IRS": "irs", "IRL": "irl", "CBGDPR": "ca", "NLGQ": "fiscal", "GGFLQ": "debt"}


def _wb(url):
    import requests
    r = requests.get(url, timeout=60, headers={"User-Agent": "idx-quant-terminal/1.0"})
    j = r.json()
    return j[0], j[1] or []


def fetch_eco(isos: list[str]) -> dict:
    import requests
    out = {"countries": {}, "src": {}, "errors": []}
    C = out["countries"]
    try:                                    # World Bank GEP: PDB riil, aktual + proyeksi
        meta, rows = _wb("https://api.worldbank.org/v2/country/all/indicator/NYGDPMKTPKDZ?source=27&format=json&per_page=5000&date=2019:2028")
        for r in rows:
            iso, v = r.get("countryiso3code"), r.get("value")
            if iso and v is not None:
                C.setdefault(iso, {}).setdefault("wb_gdp", {})[r["date"]] = v
                C[iso].setdefault("name_wb", (r.get("country") or {}).get("value"))
        out["src"]["wb_gep"] = meta.get("lastupdated")
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"WB GEP: {e}")
    try:                                    # WDI: inflasi aktual (semua negara)
        meta, rows = _wb("https://api.worldbank.org/v2/country/all/indicator/FP.CPI.TOTL.ZG?format=json&per_page=20000&date=2019:2026")
        for r in rows:
            iso, v = r.get("countryiso3code"), r.get("value")
            if iso and v is not None:
                C.setdefault(iso, {}).setdefault("wb_cpi", {})[r["date"]] = v
        out["src"]["wdi"] = meta.get("lastupdated")
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"WDI: {e}")
    ok = []
    for m, key in OECD_MEASURES.items():
        try:
            u = f"https://sdmx.oecd.org/public/rest/data/OECD.ECO.MAD,DSD_EO@DF_EO,/.{m}.A?startPeriod=2019&format=csvfilewithlabels"
            r = requests.get(u, timeout=90, headers={"User-Agent": "idx-quant-terminal/1.0"})
            if r.status_code != 200:
                out["errors"].append(f"OECD {m}: HTTP {r.status_code}")
                continue
            df = pd.read_csv(io.StringIO(r.text))
            for _, x in df.iterrows():
                iso, yr, v = x.get("REF_AREA"), str(x.get("TIME_PERIOD")), x.get("OBS_VALUE")
                if isinstance(iso, str) and pd.notna(v):
                    C.setdefault(iso, {}).setdefault("oe_" + key, {})[yr] = round(float(v), 2)
            ok.append(m)
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"OECD {m}: {e}")
    out["src"]["oecd"] = ok
    keep = set(isos) | {"WLD", "OECD", "EA17", "EMU", "EAS", "LCN", "SSF", "MEA", "SAS", "ECS", "EAP", "LAC", "SAR", "MNA", "ECA", "SSA", "EMDE", "AME"}
    out["countries"] = {k: v for k, v in C.items() if k in keep}
    return out


def load_eco(cache_dir, today, isos, demo=False, refresh=True) -> dict:
    if demo:
        rng = np.random.default_rng(5)
        C = {}
        for iso in isos + ["WLD"]:
            g = {str(y): round(float(rng.normal(3, 1.5)), 1) for y in range(2019, 2029)}
            C[iso] = {"wb_gdp": g, "oe_cpi": {str(y): round(float(rng.normal(3, 1)), 1) for y in range(2023, 2028)},
                      "oe_irs": {str(y): round(float(rng.normal(4, 1)), 2) for y in range(2023, 2028)},
                      "oe_unr": {str(y): round(float(rng.normal(5, 1)), 1) for y in range(2023, 2028)}}
        return {"countries": C, "src": {"demo": True}, "errors": [], "fetched": today}
    path = Path(cache_dir) / "world_eco.json" if cache_dir else None
    old = None
    if path and path.exists():
        try:
            old = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            old = None
    if old and (old.get("fetched") == today or not refresh):
        return old
    new = fetch_eco(isos)
    if not new["countries"] and old:
        old["errors"] = new["errors"]
        return old
    new["fetched"] = today
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(new))
    return new


# ------------------------------------------------------------------ build
def build(cache_dir=None, now=None, demo=False, full=True) -> dict:
    t0 = time.time()
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    if now.tzinfo is not None:
        now = now.tz_localize(None)
    today = str(now.date())
    syms = []
    for c in COUNTRIES:
        for s in (c[5], c[7], (c[8] or (None,))[0]):
            if s and s not in syms:
                syms.append(s)
    syms += [c[0] for c in COMMODITIES]
    px = M_.load_prices(cache_dir, today, demo=demo, syms=syms, fname="world.pkl", start="2010-01-01")
    px = px[px.index <= now.normalize()]
    rows, scores, prices = [], {}, {}
    for iso, name, flag, cls, reg, ix, ixn, etf, fx in COUNTRIES:
        r = {"iso": iso, "n": name, "f": flag, "cls": cls, "reg": reg, "ixn": ixn, "ix": ix, "etf": etf}
        r["loc"] = _perf(px[ix], now) if ix and ix in px else None
        r["usd"] = _perf(px[etf], now) if etf and etf in px else None
        if fx and fx[0] in px:
            f = px[fx[0]].dropna()
            f = f if fx[1] else 1 / f                       # nilai 1 unit mata uang lokal dalam USD
            r["fx"] = {"r21": _chg(f, 21), "r252": _chg(f, 252), "ytd": _ytd(f, now)}
        base = ix if (ix and ix in px and r["loc"] and not r["loc"]["stale"]) else etf if etf and etf in px else None
        if base:
            sc, parts = idx_sentiment(px[base])
            s_ = sc.dropna()
            if len(s_):
                scores[iso], prices[iso] = s_, px[base].dropna()
                r["sent"] = {"s": _f(s_.iloc[-1], 1), "z": _zone(s_.iloc[-1]), "w1": _f(s_.iloc[-6], 1) if len(s_) > 6 else None,
                             "m1": _f(s_.iloc[-22], 1) if len(s_) > 22 else None, "parts": parts, "src": base,
                             "h": [_f(x, 0) for x in s_.iloc[-504:].iloc[::5].values], "hd": str(s_.iloc[-504:].index[0].date())}
        rows.append(r)
    cmd = []
    for s, n, g in COMMODITIES:
        if s in px:
            p = _perf(px[s], now)
            if p:
                cmd.append({"s": s, "n": n, "g": g, **p})
    pooled = pooled_zone_stats(scores, prices)
    news = demo_news() if demo else fetch_news()
    eco = load_eco(cache_dir, today, [c[0] for c in COUNTRIES], demo=demo, refresh=full)
    out = {"countries": rows, "cmd": cmd, "isent": pooled, "news": news, "eco": eco, "demo": bool(demo),
           "asof": str(px.index[-1].date()) if len(px) else None,
           "source": "Yahoo Finance (indeks, ETF, kurs, futures) · World Bank GEP & WDI · OECD Economic Outlook · RSS berita"}
    log.info("WORLD (%.1f dtk): %d negara (%d indeks lokal) | %d komoditas | %d berita | ECO %d negara src %s err %s",
             time.time() - t0, len(rows), sum(1 for r in rows if r["loc"]), len(cmd), len(news), len(eco.get("countries", {})), eco.get("src"), eco.get("errors"))
    log.info("WORLD sentimen per zona (gabungan %s indeks): %s", pooled.get("n_idx"),
             {z: (v.get("f60") or {}).get("up") for z, v in (pooled.get("zones") or {}).items()})
    return out
