"""Lapis MAKRO global → mikro (menu MAKRO). Semua dari harga pasar Yahoo (auto-adjust = total return).

1. Rezim makro bulanan (walk-forward, z-score 60 bulan ke belakang, min 24):
   pertumbuhan  = tembaga/emas, siklikal/defensif AS, kemiringan yield 10th−3bln, saham kecil/besar AS (perubahan 6 bln)
   inflasi      = TIP/IEF (proxy breakeven), komoditas DBC, pangan DBA (perubahan 6 bln)
   → Goldilocks (G+, I−) · Reflasi (G+, I+) · Stagflasi (G−, I+) · Resesi/Deflasi (G−, I−)
   likuiditas   = −DXY, TIP (real yield turun), −yield 3 bln (perubahan 3 bln)
   stres        = persentil VIX, MOVE, −HYG/IEF (spread kredit) 3 tahun
2. Performa tiap aset di bulan BERIKUTNYA per rezim (sinyal akhir bulan t, return bulan t+1), cek dua paruh.
3. Lintas aset, negara, sektor AS: return, momentum, tren, volatilitas, kekuatan relatif, korelasi dengan IHSG.
4. Driver makro → sektor & saham BEI: korelasi return mingguan 2 tahun (mingguan agar beda zona waktu tidak mengganggu).

Hanya informasi + riset; tidak mengubah sinyal IDX. spot=True = bisa dipegang sebagai posisi spot (ETF / saham / koin).
"""
from __future__ import annotations

import logging
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("macro")

# simbol, nama, kelas, grup, spot
ASSETS = [
    ("ACWI", "Saham dunia", "eq", "Global", True), ("SPY", "S&P 500", "eq", "AS", True), ("QQQ", "Nasdaq 100", "eq", "AS", True),
    ("IWM", "Russell 2000", "eq", "AS", True), ("EFA", "Negara maju ex-AS", "eq", "Global", True), ("EEM", "Emerging markets", "eq", "Global", True),
    ("VGK", "Eropa", "eq", "Negara", True), ("EWJ", "Jepang", "eq", "Negara", True), ("MCHI", "China", "eq", "Negara", True),
    ("INDA", "India", "eq", "Negara", True), ("EIDO", "Indonesia", "eq", "Negara", True), ("EWS", "Singapura", "eq", "Negara", True),
    ("EWM", "Malaysia", "eq", "Negara", True), ("THD", "Thailand", "eq", "Negara", True), ("EPHE", "Filipina", "eq", "Negara", True),
    ("VNM", "Vietnam", "eq", "Negara", True), ("EWY", "Korea Selatan", "eq", "Negara", True), ("EWT", "Taiwan", "eq", "Negara", True),
    ("EWZ", "Brasil", "eq", "Negara", True),
    ("SHY", "Obligasi AS 1–3 th", "bd", "Obligasi", True), ("IEF", "Obligasi AS 7–10 th", "bd", "Obligasi", True),
    ("TLT", "Obligasi AS 20+ th", "bd", "Obligasi", True), ("TIP", "Obligasi AS terindeks inflasi", "bd", "Obligasi", True),
    ("LQD", "Obligasi korporasi IG", "bd", "Obligasi", True), ("HYG", "Obligasi high yield", "bd", "Obligasi", True),
    ("EMB", "Obligasi EM (USD)", "bd", "Obligasi", True), ("BNDX", "Obligasi global ex-AS", "bd", "Obligasi", True),
    ("GLD", "Emas", "cm", "Komoditas", True), ("SLV", "Perak", "cm", "Komoditas", True), ("USO", "Minyak WTI", "cm", "Komoditas", True),
    ("DBC", "Komoditas luas", "cm", "Komoditas", True), ("CPER", "Tembaga", "cm", "Komoditas", True), ("DBA", "Pertanian/pangan", "cm", "Komoditas", True),
    ("URA", "Uranium", "cm", "Komoditas", True), ("COPX", "Penambang tembaga", "cm", "Komoditas", True), ("PICK", "Penambang logam", "cm", "Komoditas", True),
    ("REMX", "Logam tanah jarang", "cm", "Komoditas", True),
    ("BTC-USD", "Bitcoin", "cr", "Crypto", True), ("ETH-USD", "Ethereum", "cr", "Crypto", True),
    ("XLK", "Teknologi", "sec", "Sektor AS", True), ("XLF", "Keuangan", "sec", "Sektor AS", True), ("XLE", "Energi", "sec", "Sektor AS", True),
    ("XLV", "Kesehatan", "sec", "Sektor AS", True), ("XLI", "Industri", "sec", "Sektor AS", True), ("XLY", "Konsumsi siklikal", "sec", "Sektor AS", True),
    ("XLP", "Konsumsi primer", "sec", "Sektor AS", True), ("XLU", "Utilitas", "sec", "Sektor AS", True), ("XLB", "Bahan baku", "sec", "Sektor AS", True),
    ("XLRE", "Properti", "sec", "Sektor AS", True), ("XLC", "Komunikasi", "sec", "Sektor AS", True),
    ("^JKSE", "IHSG", "ix", "Indeks", False), ("^GSPC", "S&P 500 (indeks)", "ix", "Indeks", False), ("000001.SS", "Shanghai", "ix", "Indeks", False),
    ("^HSI", "Hang Seng", "ix", "Indeks", False), ("^STI", "STI Singapura", "ix", "Indeks", False), ("^N225", "Nikkei 225", "ix", "Indeks", False),
    ("DX-Y.NYB", "Indeks dolar (DXY)", "fx", "Kurs", False), ("USDIDR=X", "USD/IDR", "fx", "Kurs", False), ("EURUSD=X", "EUR/USD", "fx", "Kurs", False),
    ("USDJPY=X", "USD/JPY", "fx", "Kurs", False), ("USDCNY=X", "USD/CNY", "fx", "Kurs", False), ("AUDUSD=X", "AUD/USD", "fx", "Kurs", False),
    ("^IRX", "Yield AS 3 bln", "rt", "Yield & volatilitas", False), ("^FVX", "Yield AS 5 th", "rt", "Yield & volatilitas", False),
    ("^TNX", "Yield AS 10 th", "rt", "Yield & volatilitas", False), ("^TYX", "Yield AS 30 th", "rt", "Yield & volatilitas", False),
    ("^VIX", "VIX (volatilitas saham)", "rt", "Yield & volatilitas", False), ("^MOVE", "MOVE (volatilitas obligasi)", "rt", "Yield & volatilitas", False),
    ("HG=F", "Tembaga (futures)", "cm", "Futures (info)", False), ("GC=F", "Emas (futures)", "cm", "Futures (info)", False),
    ("BZ=F", "Minyak Brent (futures)", "cm", "Futures (info)", False), ("CL=F", "Minyak WTI (futures)", "cm", "Futures (info)", False),
    ("NG=F", "Gas alam (futures)", "cm", "Futures (info)", False), ("MTF=F", "Batu bara Newcastle (futures)", "cm", "Futures (info)", False),
]
NAME = {a[0]: a[1] for a in ASSETS}
LEVEL = {"^IRX", "^FVX", "^TNX", "^TYX", "^VIX", "^MOVE"}       # yield/indeks vol: ubah dalam poin, bukan %
REGIMES = ["Goldilocks", "Reflasi", "Stagflasi", "Resesi/Deflasi"]
DRIVERS = [("usd", "Dolar (DXY)", "DX-Y.NYB", "ret"), ("idr", "USD/IDR", "USDIDR=X", "ret"), ("y10", "Yield AS 10 th", "^TNX", "diff"),
           ("oil", "Minyak Brent", "BZ=F", "ret"), ("coal", "Batu bara", "MTF=F", "ret"), ("gold", "Emas", "GC=F", "ret"),
           ("cu", "Tembaga", "HG=F", "ret"), ("em", "Saham EM", "EEM", "ret"), ("us", "Saham AS", "SPY", "ret"), ("vix", "VIX", "^VIX", "diff")]
COMP_LABEL = {"cu_au": "Tembaga / emas", "cyc": "Siklikal / defensif AS", "slope": "Kemiringan yield 10th − 3bln", "smb": "Saham kecil / besar AS",
              "be": "TIP / IEF (ekspektasi inflasi)", "cmd": "Komoditas luas (DBC)", "agri": "Pangan (DBA)",
              "usd": "Dolar melemah (−DXY)", "ry": "Real yield turun (TIP)", "st": "Suku bunga pendek turun",
              "vix": "VIX", "move": "MOVE", "credit": "Spread kredit (−HYG/IEF)"}


def _f(x, d=4):
    try:
        x = float(x)
        return round(x, d) if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ data
def _download(syms, **span) -> dict[str, pd.Series]:
    import yfinance as yf
    out = {}
    for i in range(0, len(syms), 40):
        part = syms[i:i + 40]
        for att in range(3):
            try:
                df = yf.download(part, **span, interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False, timeout=30)
                for s in part:
                    try:
                        c = df[s]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]
                        c = c.dropna()
                        if len(c):
                            out[s] = c
                    except KeyError:
                        pass
                break
            except Exception as e:  # noqa: BLE001
                log.info("Makro: unduh gagal (%s), ulang", e)
                time.sleep(3 * (att + 1))
    for s in [s for s in syms if s not in out]:
        try:
            one = yf.download(s, **span, interval="1d", auto_adjust=True, progress=False, threads=False, timeout=30)
            c = one["Close"]
            c = (c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c).dropna()
            if len(c):
                out[s] = c
        except Exception:  # noqa: BLE001
            pass
    res = {}
    for s, c in out.items():
        c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
        res[s] = c[~c.index.duplicated(keep="last")].sort_index().astype(float)
    return res


def _splice(old: pd.Series, new: pd.Series) -> pd.Series:
    """Gabung histori lama + ekor baru. Harga adjusted bisa berskala ulang (dividen) -> skala histori lama ke tanggal tumpang tindih."""
    if old is None or not len(old):
        return new
    ov = old.index.intersection(new.index)
    if len(ov) and old.loc[ov[0]] > 0:
        old = old * (new.loc[ov[0]] / old.loc[ov[0]])
    return pd.concat([old[old.index < new.index[0]], new]).sort_index()


def load_prices(cache_dir, today: str, demo=False) -> pd.DataFrame:
    if demo:
        return demo_prices()
    syms = [a[0] for a in ASSETS]
    path = Path(cache_dir) / "macro.pkl" if cache_dir else None
    cache = None
    if path and path.exists():
        try:
            cache = pd.read_pickle(path)
        except Exception:  # noqa: BLE001
            cache = None
    if cache is not None and cache.get("full") == today:
        new = _download(syms, period="5d")
        px = {s: _splice(cache["px"].get(s), new[s]) if s in new else cache["px"].get(s) for s in syms}
        full = today
    else:
        px = _download(syms, start="2000-01-01")
        if cache is not None:                   # simbol yang gagal hari ini pakai cache lama
            for s in syms:
                if s not in px and cache["px"].get(s) is not None:
                    px[s] = cache["px"][s]
        full = today
    px = {s: v for s, v in px.items() if v is not None and len(v)}
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle({"full": full, "px": px}, path)
    log.info("Makro: %d/%d simbol | tidak ada: %s", len(px), len(syms), [s for s in syms if s not in px])
    return pd.DataFrame(px).sort_index()


def demo_prices(start="2005-01-03") -> pd.DataFrame:
    """Data simulasi (uji tampilan) dengan siklus pertumbuhan & inflasi bersama."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(start, pd.Timestamp.today().normalize())
    n = len(idx)
    cyc_g = np.cumsum(rng.normal(0, 0.012, n)); cyc_g -= pd.Series(cyc_g).rolling(500, min_periods=1).mean().values
    cyc_i = np.cumsum(rng.normal(0, 0.012, n)); cyc_i -= pd.Series(cyc_i).rolling(700, min_periods=1).mean().values
    dg, di = np.diff(cyc_g, prepend=0), np.diff(cyc_i, prepend=0)
    out = {}
    for s, _, cls, grp, _ in ASSETS:
        h = zlib.crc32(s.encode()) % 1000 / 1000
        if s in LEVEL:
            base = {"^IRX": 2.0, "^FVX": 2.6, "^TNX": 3.0, "^TYX": 3.4, "^VIX": 18, "^MOVE": 90}[s]
            x = base + np.cumsum(rng.normal(0, 0.03 if s not in ("^VIX", "^MOVE") else 0.6, n) + (0.8 * dg + 0.5 * di) * (8 if s in ("^VIX", "^MOVE") else 1) * (-1 if s in ("^VIX", "^MOVE") else 1))
            x = pd.Series(x).clip(lower=0.05 if s not in ("^VIX", "^MOVE") else 9).values
            out[s] = pd.Series(x, idx)
            continue
        bg = {"eq": 1.2, "sec": 1.1, "cm": 0.4, "bd": -0.5, "cr": 2.0, "ix": 1.0, "fx": -0.3}.get(cls, 0.5)
        bi = {"cm": 1.5, "bd": -0.8, "eq": -0.3, "sec": -0.2, "cr": 0.2, "ix": -0.2, "fx": 0.3}.get(cls, 0)
        vol = {"eq": 0.012, "sec": 0.013, "cm": 0.016, "bd": 0.005, "cr": 0.035, "ix": 0.011, "fx": 0.005}.get(cls, 0.01) * (0.8 + 0.5 * h)
        r = 0.0002 + bg * dg + bi * di + rng.normal(0, vol, n)
        base = {"USDIDR=X": 15000, "USDJPY=X": 140, "USDCNY=X": 7, "DX-Y.NYB": 100, "^JKSE": 7000, "^GSPC": 5000}.get(s, 50 + 100 * h)
        out[s] = pd.Series(base * np.exp(np.cumsum(r)), idx)
    return pd.DataFrame(out)


# ------------------------------------------------------------------ rezim
def _z(x: pd.Series, win=60, minp=24):
    mu = x.rolling(win, min_periods=minp).mean().shift(1)     # pakai distribusi masa lalu saja
    sd = x.rolling(win, min_periods=minp).std().shift(1)
    return ((x - mu) / sd.replace(0, np.nan)).clip(-3, 3)


def _lg(px, a, b=None):
    if a not in px or (b is not None and b not in px):
        return None
    x = px[a] if b is None else px[a] / px[b]
    return np.log(x.where(x > 0))


def components(M: pd.DataFrame) -> dict[str, dict[str, pd.Series]]:
    """Komponen bulanan mentah (belum z)."""
    g, i, l = {}, {}, {}
    if {"HG=F", "GC=F"} <= set(M):
        g["cu_au"] = _lg(M, "HG=F", "GC=F").diff(6)
    if {"XLY", "XLI", "XLP", "XLU"} <= set(M):
        g["cyc"] = np.log((M["XLY"] + M["XLI"]) / (M["XLP"] + M["XLU"])).diff(6)
    if {"^TNX", "^IRX"} <= set(M):
        g["slope"] = (M["^TNX"] - M["^IRX"]).diff(6)
    if {"IWM", "SPY"} <= set(M):
        g["smb"] = _lg(M, "IWM", "SPY").diff(6)
    if {"TIP", "IEF"} <= set(M):
        i["be"] = _lg(M, "TIP", "IEF").diff(6)
    if "DBC" in M:
        i["cmd"] = _lg(M, "DBC").diff(6)
    if "DBA" in M:
        i["agri"] = _lg(M, "DBA").diff(6)
    if "DX-Y.NYB" in M:
        l["usd"] = -_lg(M, "DX-Y.NYB").diff(3)
    if "TIP" in M:
        l["ry"] = _lg(M, "TIP").diff(3)
    if "^IRX" in M:
        l["st"] = -M["^IRX"].diff(3)
    return {"g": g, "i": i, "l": l}


def _score(d: dict) -> tuple[pd.Series, dict]:
    Z = {k: _z(v) for k, v in d.items() if v is not None}
    if not Z:
        return None, {}
    zf = pd.DataFrame(Z)
    s = zf.mean(axis=1).where(zf.notna().sum(axis=1) >= min(2, zf.shape[1]))
    return s, Z


def regime_code(g, i):
    return np.where(g.isna() | i.isna(), np.nan, np.where(g > 0, np.where(i > 0, 1, 0), np.where(i > 0, 2, 3)))


def stress(px: pd.DataFrame) -> tuple[pd.Series, dict]:
    parts = {}
    pr = lambda x: x.rolling(756, min_periods=250).rank(pct=True)  # noqa: E731
    if "^VIX" in px:
        parts["vix"] = pr(px["^VIX"].ffill())
    if "^MOVE" in px:
        parts["move"] = pr(px["^MOVE"].ffill())
    if {"HYG", "IEF"} <= set(px):
        parts["credit"] = pr(-np.log(px["HYG"] / px["IEF"]).ffill().diff(63))
    if not parts:
        return None, {}
    return pd.DataFrame(parts).mean(axis=1) * 100, parts


def regime_perf(M: pd.DataFrame, code: pd.Series, syms) -> dict:
    """Return bulan berikutnya per rezim (sinyal akhir bulan t -> return bulan t+1)."""
    fwd = M.pct_change().shift(-1)
    ok = code.notna() & fwd.index.isin(code.dropna().index)
    idx = code.index[ok][:-1]                                   # bulan terakhir belum punya return ke depan
    if len(idx) < 36:
        return {"n": 0, "assets": {}}
    mid = idx[len(idx) // 2]
    out = {}
    for s in syms:
        if s not in fwd or s in LEVEL:
            continue
        r = fwd.loc[idx, s]
        c = code.loc[idx]
        v = r.notna()
        if v.sum() < 36:
            continue
        r, c = r[v], c[v]
        all_m = r.mean()
        h_all = [r[r.index < mid].mean(), r[r.index >= mid].mean()]
        row = {"all": _f(all_m), "n_all": int(len(r)), "since": str(r.index[0].date())[:7]}
        for k, lab in enumerate(REGIMES):
            x = r[c == k]
            if len(x) < 6:
                row[lab] = {"n": int(len(x))}
                continue
            h = [x[x.index < mid], x[x.index >= mid]]
            hm = [hh.mean() if len(hh) >= 3 else np.nan for hh in h]
            cons = all(np.isfinite(hm[j]) and np.isfinite(h_all[j]) for j in (0, 1)) and \
                np.sign(hm[0] - h_all[0]) == np.sign(hm[1] - h_all[1]) != 0
            row[lab] = {"n": int(len(x)), "m": _f(x.mean()), "hit": _f((x > 0).mean(), 3), "h": [_f(hm[0]), _f(hm[1])],
                        "ok": bool(cons), "t": _f(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else None, 2)}
        out[s] = row
    return {"n": int(len(idx)), "start": str(idx[0].date())[:7], "mid": str(mid.date())[:7], "assets": out}


def transitions(code: pd.Series) -> dict:
    c = code.dropna().astype(int)
    if len(c) < 24:
        return {}
    T = np.zeros((4, 4))
    for a, b in zip(c.values[:-1], c.values[1:]):
        T[a, b] += 1
    P = T / np.maximum(T.sum(axis=1, keepdims=True), 1)
    runs, cur, n = [], c.iloc[0], 0
    for v in c.values:
        if v == cur:
            n += 1
        else:
            runs.append((cur, n)); cur, n = v, 1
    runs.append((cur, n))
    dur = {REGIMES[k]: _f(np.mean([r for q, r in runs if q == k]), 1) if any(q == k for q, _ in runs) else None for k in range(4)}
    share = {REGIMES[k]: _f((c == k).mean(), 3) for k in range(4)}
    return {"P": [[_f(x, 3) for x in row] for row in P], "dur": dur, "share": share, "run_now": int(runs[-1][1])}


# ------------------------------------------------------------------ tabel aset
def _ret(c: pd.Series, k):
    c = c.dropna()
    return _f(c.iloc[-1] / c.iloc[-1 - k] - 1) if len(c) > k and c.iloc[-1 - k] > 0 else None


def asset_rows(px: pd.DataFrame, perf: dict, cur_reg: str | None, now) -> list[dict]:
    W = px.resample("W-FRI").last()
    jk = W["^JKSE"].pct_change() if "^JKSE" in W else None
    y0 = pd.Timestamp(now.year, 1, 1)
    rows = []
    for s, name, cls, grp, spot in ASSETS:
        if s not in px:
            continue
        c = px[s].dropna()
        if len(c) < 30:
            continue
        lev = s in LEVEL
        last = c.iloc[-1]

        def chg(k):
            if len(c) <= k:
                return None
            return _f(last - c.iloc[-1 - k], 3) if lev else _ret(c, k)
        prev = c[c.index < y0]
        ytd = None if not len(prev) else (_f(last - prev.iloc[-1], 3) if lev else _f(last / prev.iloc[-1] - 1))
        ma50, ma200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
        lr = np.log(c).diff()
        corr = None
        if jk is not None and s != "^JKSE":
            w = (W[s].diff() if lev else W[s].pct_change())
            j = pd.concat([w, jk], axis=1).dropna().iloc[-104:]
            if len(j) >= 52:
                corr = _f(j.iloc[:, 0].corr(j.iloc[:, 1]), 2)
        pf = (perf.get("assets") or {}).get(s, {})
        fit = None
        if cur_reg and pf.get(cur_reg, {}).get("m") is not None:
            o = pf[cur_reg]
            fit = {"d": _f(o["m"] - pf["all"]), "m": o["m"], "ok": o["ok"], "n": o["n"]}
        sp = c.iloc[-260:].iloc[::5]
        rows.append({
            "s": s, "n": name, "cls": cls, "g": grp, "spot": spot, "lev": lev, "last": _f(last, 4), "d": str(c.index[-1].date()),
            "stale": bool((pd.Timestamp(now.date()) - c.index[-1]).days > 10),
            "r1": chg(1), "r5": chg(5), "r21": chg(21), "r63": chg(63), "r126": chg(126), "ytd": ytd, "r252": chg(252),
            "mom": None if lev or len(c) < 253 else _f(c.iloc[-22] / c.iloc[-253] - 1),
            "up": None if lev or not np.isfinite(ma200) else bool(last > ma200), "gx": None if lev or not np.isfinite(ma200) else bool(ma50 > ma200),
            "vol": None if lev else _f(lr.iloc[-60:].std() * np.sqrt(252), 3),
            "dd": None if lev else _f(last / c.iloc[-252:].max() - 1),
            "cj": corr, "fit": fit, "sp": [_f(x, 4) for x in sp.values],
        })
    return rows


def rel_strength(px: pd.DataFrame, syms, bench) -> list[dict]:
    if bench not in px:
        return []
    out = []
    for s in syms:
        if s not in px or s == bench:
            continue
        j = px[[s, bench]].dropna()
        if len(j) < 260:
            continue
        rs = j[s] / j[bench]
        row = {"s": s, "n": NAME.get(s, s)}
        for k in (21, 63, 126, 252):
            row[f"rs{k}"] = _f(rs.iloc[-1] / rs.iloc[-1 - k] - 1)
        row["rs_up"] = bool(rs.iloc[-1] > rs.rolling(200).mean().iloc[-1])
        out.append(row)
    for k in (63, 126):
        vals = sorted([r[f"rs{k}"] for r in out if r[f"rs{k}"] is not None], reverse=True)
        for r in out:
            r[f"rk{k}"] = vals.index(r[f"rs{k}"]) + 1 if r[f"rs{k}"] is not None else None
    return out


# ------------------------------------------------------------------ driver makro -> BEI
def _drv_weekly(px: pd.DataFrame, now) -> tuple[pd.DataFrame, dict]:
    W = px.resample("W-FRI").last()
    cols, info = {}, {}
    for k, lab, s, kind in DRIVERS:
        if s not in W:
            continue
        last = px[s].dropna().index[-1]
        stale = (pd.Timestamp(now.date()) - last).days > 30
        info[k] = {"label": lab, "s": s, "stale": bool(stale), "last": str(last.date())}
        if stale:
            continue
        cols[k] = W[s].diff() if kind == "diff" else W[s].pct_change()
    return pd.DataFrame(cols), info


def idx_links(px: pd.DataFrame, F: dict | None, universe: dict | None, ihsg: pd.Series | None, now, weeks=104) -> dict:
    D, info = _drv_weekly(px, now)
    if D.empty or F is None:
        return {"drivers": info}
    c = F["c"]
    liq = F["liquid"].fillna(False).astype(bool)
    Wc = c.resample("W-FRI").last()
    Wl = liq.resample("W-FRI").last().reindex(Wc.index).fillna(False).astype(bool)
    Wr = Wc.pct_change().where(Wl.shift(1).fillna(False).astype(bool))
    Wr = Wr.iloc[-(weeks + 1):]
    Dw = D.reindex(Wr.index)

    def corrs(y: pd.Series):
        out = {}
        for k in Dw:
            j = pd.concat([y, Dw[k]], axis=1).dropna()
            if len(j) < 40:
                continue
            h = len(j) // 2
            c1, c2 = j.iloc[:h, 0].corr(j.iloc[:h, 1]), j.iloc[h:, 0].corr(j.iloc[h:, 1])
            cc = j.iloc[:, 0].corr(j.iloc[:, 1])
            b = np.polyfit(j.iloc[:, 1], j.iloc[:, 0], 1)[0] if j.iloc[:, 1].std() > 0 else np.nan
            out[k] = {"c": _f(cc, 2), "b": _f(b, 3), "h": [_f(c1, 2), _f(c2, 2)],
                      "ok": bool(np.sign(c1) == np.sign(c2) and abs(cc) * np.sqrt(len(j)) >= 2.0)}
        return out
    res = {"drivers": info, "weeks": int(len(Wr)), "start": str(Wr.index[0].date()), "end": str(Wr.index[-1].date())}
    if ihsg is not None:
        res["ihsg"] = corrs(ihsg.resample("W-FRI").last().pct_change().reindex(Wr.index))
    secs = {}
    for t in Wr.columns:
        sec = ((universe or {}).get(t) or {}).get("sector")
        if sec:
            secs.setdefault(sec, []).append(t)
    res["sectors"] = {sec: {"n": len(ts), **corrs(Wr[ts].mean(axis=1, skipna=True).where(Wr[ts].notna().sum(axis=1) >= 2))}
                      for sec, ts in secs.items() if len(ts) >= 3}
    live = [t for t in liq.columns if bool(liq[t].iloc[-1])]
    stk = {}
    for t in live:
        y = Wr[t]
        if y.notna().sum() < 52:
            continue
        cc = corrs(y)
        stk[t] = {k: v["c"] for k, v in cc.items()}
    res["keys"] = list(Dw.columns)
    res["stocks"] = stk
    res["dchg"] = {k: {"r4": _f(D[k].iloc[-4:].sum()), "r13": _f(D[k].iloc[-13:].sum())} for k in D}   # perubahan driver 1 & 3 bulan
    return res


# ------------------------------------------------------------------ build
def build(F=None, universe=None, ihsg=None, cache_dir=None, now=None, demo=False) -> dict:
    t0 = time.time()
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    if now.tzinfo is not None:
        now = now.tz_localize(None)
    px = load_prices(cache_dir, str(pd.Timestamp(now).date()), demo=demo)
    px = px[px.index <= pd.Timestamp(now).normalize()]
    M = px.resample("ME").last()
    comp = components(M)
    G, Zg = _score(comp["g"])
    I, Zi = _score(comp["i"])
    L, Zl = _score(comp["l"])
    code = pd.Series(regime_code(G, I), index=M.index)
    S, Sp = stress(px)
    Sm = S.resample("ME").last() if S is not None else None
    perf = regime_perf(M, code, [a[0] for a in ASSETS])
    # IHSG dalam USD
    if {"^JKSE", "USDIDR=X"} <= set(px):
        ju = (px["^JKSE"] / px["USDIDR=X"]).dropna()
        Mj = pd.DataFrame({"IHSG_USD": ju.resample("ME").last()})
        pj = regime_perf(Mj.reindex(M.index), code, ["IHSG_USD"])
        if pj.get("assets"):
            perf["assets"]["IHSG_USD"] = pj["assets"]["IHSG_USD"]
    cur = code.dropna()
    cur_k = int(cur.iloc[-1]) if len(cur) else None
    cur_reg = REGIMES[cur_k] if cur_k is not None else None

    def last(s):
        return _f(s.dropna().iloc[-1], 2) if s is not None and s.notna().any() else None
    comps = []
    for grp, Z, raw in (("g", Zg, comp["g"]), ("i", Zi, comp["i"]), ("l", Zl, comp["l"])):
        for k, z in Z.items():
            comps.append({"k": k, "grp": grp, "label": COMP_LABEL.get(k, k), "z": last(z), "raw": last(raw[k]),
                          "z3": _f(z.dropna().iloc[-4], 2) if z.notna().sum() > 4 else None})
    for k, p in Sp.items():
        comps.append({"k": k, "grp": "s", "label": COMP_LABEL.get(k, k), "pct": _f(p.dropna().iloc[-1] * 100, 1) if p.notna().any() else None})
    hist_idx = M.index[(G.notna() | I.notna())] if G is not None and I is not None else M.index
    H = pd.DataFrame({"g": G, "i": I, "l": L, "code": code,
                      "s": Sm.reindex(M.index) if Sm is not None else np.nan,
                      "acwi": M["ACWI"] if "ACWI" in M else np.nan, "jk": M["^JKSE"] if "^JKSE" in M else np.nan}).loc[hist_idx]
    hist = {"d": [str(d.date())[:7] for d in H.index]}
    for k in H:
        hist[k] = [_f(x, 3) if k != "code" else (None if not np.isfinite(x) else int(x)) for x in H[k].values]
    # performa rezim untuk stres tinggi/rendah & likuiditas naik/turun (aset utama)
    cond = {}
    fwd = M.pct_change().shift(-1)
    for key, sig in (("liq", L), ("stress", Sm)):
        if sig is None:
            continue
        sg = sig.reindex(M.index)
        valid = sg.dropna().index[:-1]
        if len(valid) < 36:
            continue
        hi = sg.loc[valid] > (0 if key == "liq" else 70)
        lo = sg.loc[valid] <= (0 if key == "liq" else 30) if key == "stress" else ~hi
        mid = valid[len(valid) // 2]
        rows = {}
        for s in ["ACWI", "SPY", "EEM", "EIDO", "^JKSE", "TLT", "IEF", "HYG", "GLD", "DBC", "BTC-USD", "SHY"]:
            if s not in fwd:
                continue
            r = fwd.loc[valid, s]
            def st(m):
                x = r[m].dropna()
                h = [x[x.index < mid], x[x.index >= mid]]
                return {"n": int(len(x)), "m": _f(x.mean()) if len(x) >= 6 else None, "h": [_f(hh.mean()) if len(hh) >= 3 else None for hh in h]}
            rows[s] = {"hi": st(hi), "lo": st(lo)}
        cond[key] = rows
    now_ = {"regime": cur_reg, "code": cur_k, "g": last(G), "i": last(I), "l": last(L), "stress": last(S),
            "asof": str(px.index[-1].date()), "month": str(M.index[-1].date())[:7],
            "path": [{"d": str(d.date())[:7], "g": _f(G.loc[d], 2), "i": _f(I.loc[d], 2)} for d in M.index[-13:] if G is not None and np.isfinite(G.loc[d]) and np.isfinite(I.loc[d])]}
    rows = asset_rows(px, perf, cur_reg, now)
    countries = rel_strength(px, [a[0] for a in ASSETS if a[3] == "Negara"] + ["SPY", "EEM", "EFA"], "ACWI")
    sectors = rel_strength(px, [a[0] for a in ASSETS if a[3] == "Sektor AS"], "SPY")
    links = idx_links(px, F, universe, ihsg, now) if F is not None else {}
    out = {"now": now_, "comps": comps, "hist": hist, "perf": perf, "trans": transitions(code), "cond": cond,
           "assets": rows, "countries": countries, "us_sectors": sectors, "idx": links, "regimes": REGIMES,
           "source": "Yahoo Finance (harga total return ETF)", "demo": bool(demo)}
    try:
        spot = {a[0] for a in ASSETS if a[4]} | {"IHSG_USD", "^JKSE"}
        fl = [(s_, o[cur_reg]["m"] - o["all"], o[cur_reg]["ok"], o[cur_reg]["n"]) for s_, o in perf["assets"].items()
              if s_ in spot and cur_reg and (o.get(cur_reg) or {}).get("m") is not None]
        gd = sorted([x for x in fl if x[1] > 0 and x[2]], key=lambda x: -x[1])[:8]
        bd = sorted([x for x in fl if x[1] < 0 and x[2]], key=lambda x: x[1])[:8]
        log.info("MAKRO rezim %s: unggul %s | tertinggal %s | Indonesia %s", cur_reg, [(a, round(b * 100, 2), n) for a, b, _, n in gd],
                 [(a, round(b * 100, 2), n) for a, b, _, n in bd], [(a, round(b * 100, 2), ok, n) for a, b, ok, n in fl if a in ("EIDO", "IHSG_USD", "^JKSE")])
        log.info("MAKRO negara 6B: %s | sektor AS 3B: %s | komponen %s | durasi %s run %s bertahan %s", [(c["s"], c["rk126"], c["rs126"]) for c in sorted(countries, key=lambda c: c.get("rk126") or 99)],
                 [(c["s"], c["rk63"]) for c in sorted(sectors, key=lambda c: c.get("rk63") or 99)][:5], [(c["k"], c.get("z", c.get("pct"))) for c in comps],
                 (out["trans"] or {}).get("dur"), (out["trans"] or {}).get("run_now"), ((out["trans"] or {}).get("P") or [[None] * 4] * 4)[cur_k][cur_k] if cur_k is not None else None)
        log.info("MAKRO kondisi: %s", {k: {s_: (v["hi"]["m"], v["lo"]["m"], v["hi"]["h"], v["lo"]["h"]) for s_, v in rows_.items() if s_ in ("EIDO", "^JKSE", "GLD", "TLT", "ACWI")} for k, rows_ in cond.items()})
    except Exception as e:  # noqa: BLE001
        log.info("MAKRO ringkasan log gagal: %s", e)
    log.info("MAKRO (%.1f dtk): rezim %s (G %s I %s) likuiditas %s stres %s | %d aset | perf %s bln sejak %s | driver BEI %s",
             time.time() - t0, cur_reg, now_["g"], now_["i"], now_["l"], now_["stress"], len(rows), perf.get("n"), perf.get("start"),
             {k: (v.get("c"), v.get("ok")) for k, v in (links.get("ihsg") or {}).items()})
    return out
