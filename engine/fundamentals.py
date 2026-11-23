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
    # untuk valuasi harga wajar (DCF, EV/EBITDA) — dalam mata uang laporan
    "fcf": "freeCashflow", "ocf": "operatingCashflow", "ebitda": "ebitda", "debt": "totalDebt", "cash": "totalCash",
    # konsensus analis (kalau ada) — tab EE
    "tgt": "targetMeanPrice", "tgt_hi": "targetHighPrice", "tgt_lo": "targetLowPrice", "n_an": "numberOfAnalystOpinions",
    "feps": "forwardEps", "rec_m": "recommendationMean",
}
# Laporan keuangan (tab FS / EE): kunci pendek -> calon nama baris Yahoo (yang pertama ada dipakai)
FS_ROWS = {
    "is": {"rev": ["Total Revenue", "Operating Revenue"], "nii": ["Net Interest Income"], "gp": ["Gross Profit"],
           "op": ["Operating Income", "Total Operating Income As Reported"], "ebitda": ["EBITDA", "Normalized EBITDA"],
           "intx": ["Interest Expense"], "pbt": ["Pretax Income"], "tax": ["Tax Provision"],
           "ni": ["Net Income Common Stockholders", "Net Income"], "eps": ["Diluted EPS", "Basic EPS"],
           "cogs": ["Cost Of Revenue", "Reconciled Cost Of Revenue"], "sga": ["Selling General And Administration"],
           "dep": ["Reconciled Depreciation"]},
    "bs": {"ta": ["Total Assets"], "ca": ["Current Assets"], "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
           "rec": ["Accounts Receivable", "Receivables"], "inv": ["Inventory"], "tl": ["Total Liabilities Net Minority Interest"],
           "cl": ["Current Liabilities"], "debt": ["Total Debt"], "eq": ["Stockholders Equity", "Common Stock Equity"],
           "ppe": ["Net PPE"], "ltd": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]},
    "cf": {"ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], "capex": ["Capital Expenditure"], "fcf": ["Free Cash Flow"],
           "div": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
           "da": ["Depreciation And Amortization", "Depreciation Amortization Depletion"]},
}
SCHEMA = 5      # naikkan kalau kolom bertambah, supaya cache lama diambil ulang
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
    out["rec_k"] = str(info.get("recommendationKey"))[:20] if info.get("recommendationKey") not in (None, "none") else None
    fs = statements(tk, sym)
    out["fs"] = fs
    out.update(events(tk, sym))
    a = fs.get("a") or {}
    years = [{"y": int(str(p)[:4]), "rev": a.get("rev", [None] * 9)[i], "ni": a.get("ni", [None] * 9)[i],
              "ebitda": a.get("ebitda", [None] * 9)[i], "fcf": a.get("fcf", [None] * 9)[i]} for i, p in enumerate(a.get("p", []))]
    out["years"] = [y for y in years if y["rev"] is not None or y["ni"] is not None]
    out["t"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out["v"] = SCHEMA
    return out


def statements(tk, sym) -> dict:
    """Laba rugi, neraca, arus kas — tahunan ('a', s/d 5 thn) & kuartalan ('q', s/d 6 kuartal), periode lama -> baru."""
    src = {"a": {"is": "income_stmt", "bs": "balance_sheet", "cf": "cashflow"},
           "q": {"is": "quarterly_income_stmt", "bs": "quarterly_balance_sheet", "cf": "quarterly_cashflow"}}
    out = {}
    for fr, parts in src.items():
        cols, rows = set(), {}
        frames = {}
        for part, attr in parts.items():
            try:
                df = getattr(tk, attr)
                if df is not None and len(df.columns):
                    frames[part] = df
                    cols.update(df.columns)
            except Exception as e:  # noqa: BLE001 — tiap laporan opsional
                log.debug("%s %s: %s", attr, sym, e)
        if not cols:
            continue
        per = sorted(cols)[-(5 if fr == "a" else 6):]
        for part, items in FS_ROWS.items():
            df = frames.get(part)
            if df is None:
                continue
            for k, names in items.items():
                n = next((x for x in names if x in df.index), None)
                if n is None:
                    continue
                vals = [_num(df.loc[n].get(c)) if c in df.columns else None for c in per]
                if any(v is not None for v in vals):
                    rows[k] = vals
        if rows:
            lab = [str(c.year) if fr == "a" else f"{c.year}Q{(c.month - 1) // 3 + 1}" for c in per]
            if "ocf" not in rows and "fcf" in rows and "capex" in rows:      # arus kas operasi = FCF − capex
                rows["ocf"] = [f - c if f is not None and c is not None else None for f, c in zip(rows["fcf"], rows["capex"])]
            out[fr] = {"p": lab, "end": [c.strftime("%Y-%m-%d") for c in per], **rows}
    return out


def _d(x):
    try:
        return x.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return str(x)[:10] if x else None


def events(tk, sym) -> dict:
    """Kalender: riwayat dividen, stock split, jadwal laporan & dividen berikutnya (kalau Yahoo punya)."""
    out = {"dvd": [], "split": [], "cal": {}}
    try:
        dv = tk.dividends
        if dv is not None and len(dv):
            out["dvd"] = [[_d(k), _num(v)] for k, v in dv.items() if _num(v)][-24:]
    except Exception as e:  # noqa: BLE001
        log.debug("dividends %s: %s", sym, e)
    try:
        sp = tk.splits
        if sp is not None and len(sp):
            out["split"] = [[_d(k), _num(v)] for k, v in sp.items() if _num(v)][-6:]
    except Exception as e:  # noqa: BLE001
        log.debug("splits %s: %s", sym, e)
    try:
        cal = tk.calendar or {}
        if isinstance(cal, dict):
            earn = cal.get("Earnings Date") or []
            earn = earn if isinstance(earn, (list, tuple)) else [earn]
            out["cal"] = {k: v for k, v in {"earn": [_d(x) for x in earn if x], "exdiv": _d(cal.get("Ex-Dividend Date")) if cal.get("Ex-Dividend Date") else None,
                                            "pay": _d(cal.get("Dividend Date")) if cal.get("Dividend Date") else None}.items() if v}
    except Exception as e:  # noqa: BLE001
        log.debug("calendar %s: %s", sym, e)
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
            if cache[t].get("v") != SCHEMA and not cache[t].get("vt") == SCHEMA:
                return 10**6
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
                cache[t]["vt"] = SCHEMA                 # sudah dicoba dengan skema ini
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
                  "exdiv": None, "years": sorted(years, key=lambda z: z["y"]), "t": "2026-11-13", "v": SCHEMA,
                  "fcf": ni * float(rng.uniform(0.5, 1.2)), "ocf": ni * 1.4, "ebitda": ni * float(rng.uniform(1.6, 2.6)),
                  "debt": ni * float(rng.uniform(0.5, 4)), "cash": ni * float(rng.uniform(0.3, 2))}
        for q in out[t]["years"]:
            q["fcf"], q["ebitda"] = q["ni"] * float(rng.uniform(0.5, 1.2)), q["ni"] * 2.0
        o = out[t]
        o.update({"tgt": px * float(rng.uniform(0.9, 1.4)) if rng.random() < 0.6 else None, "n_an": float(rng.integers(3, 25)),
                  "feps": eps * float(rng.uniform(0.95, 1.25)), "rec_k": "buy", "rec_m": 2.1})
        o["tgt_hi"], o["tgt_lo"] = (o["tgt"] * 1.25, o["tgt"] * 0.8) if o["tgt"] else (None, None)
        ys = o["years"]
        def blk(scale, n):
            g = [float(rng.uniform(0.85, 1.2)) for _ in range(n)]
            return g
        a = {"p": [str(y["y"]) for y in ys], "end": [f"{y['y']}-12-31" for y in ys],
             "rev": [y["rev"] for y in ys], "ni": [y["ni"] for y in ys], "ebitda": [y["ebitda"] for y in ys], "fcf": [y["fcf"] for y in ys]}
        a["gp"] = [r * o["gpm"] for r in a["rev"]]; a["op"] = [r * o["opm"] for r in a["rev"]]
        a["pbt"] = [n * 1.28 for n in a["ni"]]; a["tax"] = [n * 0.28 for n in a["ni"]]; a["eps"] = [n / sh for n in a["ni"]]
        eqv = bv * sh
        a["eq"] = [eqv * (0.8 + 0.07 * i) for i in range(len(ys))]; a["ta"] = [e * (1 + o["der"]) * 1.3 for e in a["eq"]]
        a["tl"] = [x - e for x, e in zip(a["ta"], a["eq"])]; a["debt"] = [e * o["der"] for e in a["eq"]]; a["cash"] = [x * 0.12 for x in a["ta"]]
        a["ca"] = [x * 0.4 for x in a["ta"]]; a["cl"] = [x / o["cr"] for x in a["ca"]]
        a["cogs"] = [r - g for r, g in zip(a["rev"], a["gp"])]; a["sga"] = [r * 0.12 for r in a["rev"]]; a["dep"] = [r * 0.05 for r in a["rev"]]
        a["ppe"] = [x * 0.35 for x in a["ta"]]; a["ltd"] = [d * 0.6 for d in a["debt"]]; a["da"] = a["dep"]
        a["rec"] = [r * 0.15 for r in a["rev"]]
        if rng.random() < 0.1:       # sebagian saham demo dibuat "mencurigakan" untuk menguji tampilan Beneish
            a["rec"] = [r * (0.1 + 0.08 * i * i) for i, r in enumerate(a["rev"])]
        a["ocf"] = [n * 1.4 for n in a["ni"]]; a["capex"] = [f - c for f, c in zip(a["fcf"], a["ocf"])]; a["div"] = [-n * o["payout"] for n in a["ni"]]
        lr, ln = a["rev"][-1], a["ni"][-1]
        qp = ["2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3"]
        qg = [0.93, 0.97, 1.0, 1.02, 1.06, 1.09]
        q = {"p": qp, "end": ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"],
             "rev": [lr / 4 * x for x in qg], "ni": [ln / 4 * x * float(rng.uniform(0.85, 1.15)) for x in qg]}
        q["gp"] = [r * o["gpm"] for r in q["rev"]]; q["op"] = [r * o["opm"] for r in q["rev"]]; q["eps"] = [n / sh for n in q["ni"]]
        for k in ("ta", "tl", "eq", "debt", "cash", "ca", "cl"):
            q[k] = [a[k][-1] * (0.97 + 0.01 * i) for i in range(6)]
        q["ocf"] = [n * 1.3 for n in q["ni"]]; q["fcf"] = [n * 0.8 for n in q["ni"]]; q["capex"] = [f - c for f, c in zip(q["fcf"], q["ocf"])]
        o["fs"] = {"a": a, "q": q}
        if dps > 0:
            o["dvd"] = [[f"{y}-0{int(rng.integers(4, 7))}-{int(rng.integers(10, 28))}", round(dps * (0.8 + 0.06 * (y - 2021)))] for y in range(2021, 2026)]
            if rng.random() < 0.3:
                o["dvd"].append([f"2026-11-{int(rng.integers(3, 20)):02d}", round(dps * 0.4)])
        o["split"] = [["2024-03-15", 5.0]] if rng.random() < 0.05 else []
        o["cal"] = {"earn": [f"2027-0{int(rng.integers(2, 4))}-{int(rng.integers(10, 28))}"]} if rng.random() < 0.5 else {}
        if rng.random() < 0.15:
            o["cal"]["exdiv"] = f"2026-12-{int(rng.integers(1, 20)):02d}"
    return out
