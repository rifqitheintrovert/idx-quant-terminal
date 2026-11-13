"""Pengambilan data: harga (Yahoo Finance), foreign flow (situs BEI, opsional), data demo."""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime

import numpy as np
import pandas as pd
import requests

log = logging.getLogger("data")
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


# ------------------------------------------------------------------ Yahoo
def _split_download(df: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Pecah output yf.download (MultiIndex kolom, urutan level apa pun) per simbol."""
    out = {}
    if df is None or df.empty:
        return out
    if not isinstance(df.columns, pd.MultiIndex):
        if len(symbols) == 1:
            out[symbols[0]] = df[[c for c in FIELDS if c in df.columns]].copy()
        return out
    lv0 = set(df.columns.get_level_values(0))
    for s in symbols:
        try:
            sub = df[s] if s in lv0 else df.xs(s, axis=1, level=1)
        except KeyError:
            continue
        sub = sub[[c for c in FIELDS if c in sub.columns]].copy()
        sub = sub.dropna(subset=["Close"])
        if len(sub):
            out[s] = sub
    return out


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_yahoo(symbols: list[str], period: str = "5y", retries: int = 3, chunk: int = 120,
                max_single_retry: int = 80) -> dict[str, pd.DataFrame]:
    """Unduh OHLCV harian. Ratusan simbol dipecah per `chunk` agar ramah rate-limit Yahoo."""
    import yfinance as yf

    res: dict[str, pd.DataFrame] = {}
    last_err = None
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        for attempt in range(retries):
            try:
                df = yf.download(part, period=period, interval="1d", group_by="ticker",
                                 auto_adjust=False, threads=True, progress=False, timeout=30)
                got = _split_download(df, part)
                if got:
                    res.update(got)
                    break
            except Exception as e:  # noqa: BLE001
                last_err = e
            _time.sleep(4 * (attempt + 1))
        if i + chunk < len(symbols):
            _time.sleep(1.0)
    missing = [s for s in symbols if s not in res]
    if res and missing:  # cache sqlite yfinance kadang 'database is locked' saat paralel -> ulang satu per satu
        _time.sleep(2)
        for s in missing[:max_single_retry]:
            try:
                one = yf.download(s, period=period, interval="1d", auto_adjust=False,
                                  threads=False, progress=False, timeout=30)
                if one is not None and not one.empty:
                    if isinstance(one.columns, pd.MultiIndex):
                        one.columns = one.columns.get_level_values(0)
                    one = one[[c for c in FIELDS if c in one.columns]].dropna(subset=["Close"])
                    if len(one):
                        res[s] = one
            except Exception:  # noqa: BLE001
                pass
    if not res:
        raise RuntimeError(f"Yahoo download gagal: {last_err}")
    return {k: _norm(v) for k, v in res.items()}


# ------------------------------------------------------------------ cache histori (hemat request Yahoo)
def load_cache(path) -> dict | None:
    try:
        obj = pd.read_pickle(path)
        return obj if isinstance(obj, dict) and obj.get("frames") else None
    except Exception:  # noqa: BLE001
        return None


def save_cache(path, obj: dict):
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(obj, path)


def merge_frames(old: dict[str, pd.DataFrame], new: dict[str, pd.DataFrame]) -> list[str]:
    """Tempel bar terbaru ke histori cache. Return ticker yang harganya tidak nyambung
    (indikasi stock split / koreksi data) dan perlu diunduh ulang penuh."""
    broken = []
    for t, df in new.items():
        if df.empty:
            continue
        if t not in old:
            old[t] = df
            continue
        o, d0 = old[t], df.index.min()
        if d0 in o.index:
            a, b = float(o.at[d0, "Close"]), float(df.at[d0, "Close"])
            if a > 0 and b > 0 and abs(a / b - 1) > 0.02:
                broken.append(t)
        old[t] = pd.concat([o[o.index < d0], df])
    return broken


def avg_value(df: pd.DataFrame, n: int = 20) -> float:
    v = (df["Close"] * df["Volume"]).tail(n).mean()
    return float(v) if v == v else 0.0


def build_panels(frames: dict[str, pd.DataFrame], tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Gabungkan per-saham menjadi panel per field (tanggal x ticker)."""
    panels = {}
    for f in FIELDS:
        cols = {t: frames[t][f] for t in tickers if t in frames and f in frames[t]}
        panels[f] = pd.DataFrame(cols).sort_index()
    # buang tanggal "nyasar" (bar yang hanya muncul di segelintir saham, mis. hari libur bursa)
    cnt = panels["Close"].notna().sum(axis=1)
    idx = cnt[cnt >= max(1, min(5, len(tickers)), int(0.03 * len(tickers)))].index
    for f in FIELDS:
        panels[f] = panels[f].reindex(idx)
    # Hari tanpa transaksi: harga = close sebelumnya, volume = 0
    c = panels["Close"].ffill()
    for f in ["Open", "High", "Low"]:
        panels[f] = panels[f].fillna(c)
    panels["Close"] = c
    panels["Volume"] = panels["Volume"].fillna(0)
    # Yahoo kadang mengirim high/low = 0 untuk bar terakhir intraday
    for f in ["Open", "High", "Low"]:
        panels[f] = panels[f].where(panels[f] > 0, c)
    panels["High"] = np.maximum(panels["High"], panels["Close"])
    panels["Low"] = np.minimum(panels["Low"], panels["Close"])
    return panels


# ------------------------------------------------------------------ BEI foreign flow
IDX_URL = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
IDX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/",
}


def fetch_foreign_flow(dates: list[pd.Timestamp], tickers: list[str]) -> pd.DataFrame | None:
    """Net beli asing (Rp, perkiraan = (lembar beli - jual asing) x close). None jika diblokir."""
    rows = {}
    s = requests.Session()
    for d in dates:
        try:
            r = s.get(IDX_URL, params={"length": 9999, "start": 0, "date": d.strftime("%Y%m%d")},
                      headers=IDX_HEADERS, timeout=15)
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                log.warning("BEI foreign flow tidak tersedia (HTTP %s)", r.status_code)
                return None if not rows else pd.DataFrame(rows).T.sort_index()
            data = r.json().get("data", [])
            day = {}
            for it in data:
                code = it.get("StockCode")
                if code in tickers:
                    fb, fs = float(it.get("ForeignBuy") or 0), float(it.get("ForeignSell") or 0)
                    px = float(it.get("Close") or 0)
                    day[code] = (fb - fs) * px
            if day:
                rows[d] = day
            _time.sleep(0.6)
        except Exception as e:  # noqa: BLE001
            log.warning("BEI foreign flow error: %s", e)
            return None if not rows else pd.DataFrame(rows).T.sort_index()
    return pd.DataFrame(rows).T.sort_index() if rows else None


def fetch_previous(site_url: str | None) -> dict | None:
    if not site_url:
        return None
    try:
        r = requests.get(site_url.rstrip("/") + "/data/latest.json", timeout=20,
                         params={"t": int(_time.time())})
        if r.status_code == 200:
            js = r.json()
            if isinstance(js, dict) and js.get("enc"):
                from . import crypto
                c = crypto.creds()
                return crypto.decrypt(js, *c) if c else None
            return js
    except Exception:  # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------------ DEMO
def demo_data(universe: dict, macro: dict, days: int = 1260, seed: int = 7, end: datetime | None = None):
    """Data SIMULASI untuk pratinjau (bukan harga pasar)."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end or datetime.now()).normalize()
    idx = pd.bdate_range(end=end, periods=days)
    n = len(idx)
    tickers = list(universe)
    sectors = sorted({v["sector"] for v in universe.values()})

    # faktor pasar dengan rezim (bull / chop / bear)
    regime = np.zeros(n)
    state, i = 0, 0
    while i < n:
        length = rng.integers(60, 200)
        regime[i:i + length] = state
        state = rng.choice([0, 1, 2], p=[0.45, 0.35, 0.20])
        i += length
    mu = np.select([regime == 0, regime == 1, regime == 2], [0.0006, 0.0, -0.0009])
    sig = np.select([regime == 0, regime == 1, regime == 2], [0.008, 0.009, 0.014])
    mkt = mu + sig * rng.standard_normal(n)
    sec_f = {s: 0.0002 * rng.standard_normal() + 0.006 * rng.standard_normal(n) for s in sectors}
    for s in sectors:  # sedikit autokorelasi sektor (rotasi)
        sec_f[s] = pd.Series(sec_f[s]).ewm(span=3).mean().values * 1.6

    base_px = {"BBCA": 8200, "BBRI": 3900, "BMRI": 5100, "BBNI": 4300, "TLKM": 2900, "ASII": 4800,
               "UNTR": 24000, "ICBP": 10500, "INDF": 7000, "AMMN": 7500, "GOTO": 70, "BUMI": 120,
               "ADRO": 2300, "PTBA": 2600, "ITMG": 24000, "UNVR": 1900, "KLBF": 1350, "CPIN": 4700}
    out = {f: {} for f in FIELDS}
    for k, t in enumerate(tickers):
        sec = universe[t]["sector"]
        beta = rng.uniform(0.6, 1.5)
        idio_vol = rng.uniform(0.012, 0.028)
        # fase akumulasi/distribusi: drift + bias CLV
        phase = np.zeros(n)
        j = 0
        while j < n:
            L = rng.integers(25, 90)
            phase[j:j + L] = rng.choice([-1, 0, 1], p=[0.25, 0.4, 0.35])
            j += L
        drift = phase * rng.uniform(0.0006, 0.0018)
        r = beta * mkt + sec_f[sec] + drift + idio_vol * rng.standard_normal(n)
        r = np.clip(r, -0.069, 0.24)
        p0 = base_px.get(t, float(rng.choice([300, 600, 900, 1500, 2500, 4000, 6000])))
        close = p0 * np.exp(np.cumsum(r) - np.cumsum(r)[-1] * rng.uniform(0.2, 1.0))
        rng_pct = np.abs(r) + idio_vol * rng.uniform(0.4, 1.0, n)
        hi_ext = rng.uniform(0.15, 1.0, n) * rng_pct
        lo_ext = rng.uniform(0.15, 1.0, n) * rng_pct
        # tutup dekat high saat akumulasi
        bias = 0.25 * phase + 3 * r
        loc = np.clip(0.5 + 0.5 * np.tanh(bias * 2 + 0.6 * rng.standard_normal(n)), 0, 1)
        high = close * (1 + hi_ext * (1 - loc) + 0.001)
        low = close * (1 - lo_ext * loc - 0.001)
        opn = low + (high - low) * rng.uniform(0.2, 0.8, n)
        avg_val = rng.choice([15e9, 40e9, 90e9, 200e9, 450e9], p=[0.2, 0.3, 0.25, 0.15, 0.10])
        val = avg_val * np.exp(0.35 * rng.standard_normal(n)) * (1 + 18 * np.abs(r)) * (1 + 0.3 * (phase != 0))
        vol = val / close
        from .idx_rules import round_tick
        rt = np.vectorize(round_tick)
        out["Close"][t] = rt(close)
        out["High"][t] = rt(high, "up")
        out["Low"][t] = rt(low, "down")
        out["Open"][t] = rt(opn)
        out["Volume"][t] = np.round(vol / 100) * 100
    panels = {f: pd.DataFrame(out[f], index=idx) for f in FIELDS}
    panels["High"] = np.maximum(np.maximum(panels["High"], panels["Close"]), panels["Open"])
    panels["Low"] = np.minimum(np.minimum(panels["Low"], panels["Close"]), panels["Open"])

    # makro
    m = {}
    ihsg = 7000 * np.exp(np.cumsum(mkt) - mkt.sum() * 0.6)
    m["IHSG"] = pd.DataFrame({"Close": ihsg, "High": ihsg * 1.004, "Low": ihsg * 0.996,
                              "Open": ihsg, "Volume": 0}, index=idx)
    m["LQ45"] = m["IHSG"] * (800 / 7000)
    for name, lvl, vol_ in [("USDIDR", 16400, 0.003), ("GOLD", 3900, 0.011), ("BRENT", 68, 0.018),
                            ("US10Y", 4.2, 0.02), ("DXY", 99, 0.004), ("EIDO", 18, 0.012)]:
        s = lvl * np.exp(np.cumsum(vol_ * rng.standard_normal(n)) * 0.6)
        if name == "USDIDR":
            s = s * np.exp(-0.5 * np.cumsum(mkt) + 0.5 * np.cumsum(mkt)[-1])
        m[name] = pd.DataFrame({"Close": s, "High": s, "Low": s, "Open": s, "Volume": 0}, index=idx)
    return panels, m
