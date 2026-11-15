"""Data profil & fundamental per saham (untuk tab DES / FA di dashboard).

Sumber: Yahoo Finance (`Ticker.info` + laporan laba rugi tahunan). Data ini berubah lambat, jadi:
  - disimpan di cache (.cache/fundamentals.json) dan baru diambil ulang setelah `max_age_days`,
  - tiap run hanya mengambil selama `budget_s` detik (sisanya dilanjutkan run berikutnya),
  - berhenti kalau Yahoo menolak beberapa kali berturut-turut (cache lama tetap dipakai).
Tidak dipakai untuk sinyal atau backtest — hanya informasi.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

log = logging.getLogger("fund")

INFO = {  # nama di file -> kunci Yahoo
    "mcap": "marketCap", "shares": "sharesOutstanding", "float": "floatShares",
    "pe": "trailingPE", "fpe": "forwardPE", "pbv": "priceToBook", "ps": "priceToSalesTrailing12Months",
    "ev_ebitda": "enterpriseToEbitda", "eps": "trailingEps", "bvps": "bookValue",
    "roe": "returnOnEquity", "roa": "returnOnAssets", "npm": "profitMargins", "opm": "operatingMargins", "gpm": "grossMargins",
    "rev_g": "revenueGrowth", "eps_g": "earningsGrowth", "der": "debtToEquity", "cr": "currentRatio",
    "dps": "dividendRate", "payout": "payoutRatio", "beta": "beta", "rev": "totalRevenue", "ni": "netIncomeToCommon",
    "emp": "fullTimeEmployees",
}
TEXT = {"industry": "industry", "ysector": "sector", "web": "website", "cur": "financialCurrency", "city": "city"}


def _num(x):
    try:
        x = float(x)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _one(sym: str) -> dict | None:
    import yfinance as yf

    tk = yf.Ticker(sym)
    info = tk.info or {}
    if not info or (info.get("marketCap") is None and info.get("longName") is None and info.get("shortName") is None):
        return None
    out = {k: _num(info.get(y)) for k, y in INFO.items()}
    out.update({k: (str(info[y])[:120] if info.get(y) else None) for k, y in TEXT.items()})
    desc = info.get("longBusinessSummary")
    out["desc"] = (desc[:900].rsplit(" ", 1)[0] + "…") if desc and len(desc) > 900 else desc
    ex = info.get("exDividendDate")
    out["exdiv"] = datetime.fromtimestamp(ex, tz=timezone.utc).strftime("%Y-%m-%d") if isinstance(ex, (int, float)) and ex > 0 else None
    if out.get("der") is not None:
        out["der"] = out["der"] / 100.0            # Yahoo memberi DER dalam persen
    years = []
    try:
        inc = tk.income_stmt
        if inc is not None and len(inc.columns):
            def row(*names):
                for n in names:
                    if n in inc.index:
                        return inc.loc[n]
                return None
            rev, ni = row("Total Revenue", "Operating Revenue"), row("Net Income", "Net Income Common Stockholders")
            for col in list(inc.columns)[:5]:
                years.append({"y": int(col.year), "rev": _num(rev[col]) if rev is not None else None,
                              "ni": _num(ni[col]) if ni is not None else None})
            years = [y for y in years if y["rev"] is not None or y["ni"] is not None]
            years.sort(key=lambda z: z["y"])
    except Exception as e:  # noqa: BLE001 — laporan tahunan opsional
        log.debug("income_stmt %s: %s", sym, e)
    out["years"] = years
    out["t"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return out


def load(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def refresh(tickers: list[str], path, max_age_days: int = 7, budget_s: float = 240, fetch: bool = True) -> dict:
    """tickers diurutkan dari yang terpenting. Mengembalikan {KODE: data} (gabungan cache + yang baru diambil)."""
    cache = load(path)
    if not fetch:
        return cache
    today = datetime.now(timezone.utc).date()

    def age(t):
        try:
            return (today - datetime.strptime(cache[t]["t"], "%Y-%m-%d").date()).days
        except Exception:  # noqa: BLE001
            return 10**6

    todo = [t for t in tickers if age(t) >= max_age_days]
    t0, ok, fail, streak = time.time(), 0, 0, 0
    for t in todo:
        if time.time() - t0 > budget_s:
            break
        try:
            d = _one(t + ".JK")
        except Exception as e:  # noqa: BLE001
            d = None
            log.debug("fundamental %s gagal: %s", t, e)
        if d:
            cache[t] = d
            ok, streak = ok + 1, 0
        else:
            fail, streak = fail + 1, streak + 1
            if t in cache:                           # jangan dicoba terus tiap run
                cache[t]["t"] = today.strftime("%Y-%m-%d")
            if streak >= 8:
                log.warning("Fundamental: Yahoo menolak %d kali berturut-turut — berhenti, pakai cache", streak)
                break
        time.sleep(0.15)
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("cache fundamental gagal disimpan: %s", e)
    log.info("Fundamental: %d diambil, %d gagal, %d antre; tersedia %d dari %d saham (%.0f dtk)",
             ok, fail, max(0, len(todo) - ok - fail), sum(1 for t in tickers if (cache.get(t) or {}).get("mcap")), len(tickers), time.time() - t0)
    return cache


def demo(tickers: list[str], last: dict, seed: int = 11) -> dict:
    """Angka acak untuk mode demo (uji tampilan)."""
    rng = np.random.default_rng(seed)
    out = {}
    for t in tickers:
        px = float(last.get(t) or 1000)
        sh = float(rng.uniform(2e9, 120e9))
        pe, pbv = float(rng.uniform(5, 30)), float(rng.uniform(0.6, 5))
        eps, bv = px / pe, px / pbv
        ni = eps * sh
        npm = float(rng.uniform(0.04, 0.3))
        rev = ni / npm
        g = rng.uniform(-0.1, 0.25, 4)
        years = []
        r, n = rev, ni
        for i, y in enumerate(range(2025, 2021, -1)):
            years.append({"y": y, "rev": r, "ni": n})
            r, n = r / (1 + g[i]), n / (1 + g[i] * 1.3)
        dps = eps * float(rng.uniform(0, 0.6))
        out[t] = {"mcap": px * sh, "shares": sh, "float": sh * float(rng.uniform(0.15, 0.6)), "pe": pe, "fpe": pe * 0.9, "pbv": pbv,
                  "ps": px * sh / rev, "ev_ebitda": float(rng.uniform(4, 15)), "eps": eps, "bvps": bv, "roe": eps / bv,
                  "roa": eps / bv * 0.4, "npm": npm, "opm": npm * 1.4, "gpm": npm * 2.2, "rev_g": float(g[0]), "eps_g": float(g[0] * 1.3),
                  "der": float(rng.uniform(0, 2)), "cr": float(rng.uniform(0.8, 3)), "dps": dps, "payout": dps / eps,
                  "beta": float(rng.uniform(0.4, 1.8)), "rev": rev, "ni": ni, "emp": float(rng.integers(300, 40000)),
                  "industry": "Contoh industri (simulasi)", "ysector": None, "web": None, "cur": "IDR", "city": "Jakarta",
                  "desc": "[SIMULASI] Deskripsi perusahaan akan tampil di sini pada data live (sumber: Yahoo Finance).",
                  "exdiv": None, "years": sorted(years, key=lambda z: z["y"]), "t": "2026-11-13"}
    return out
