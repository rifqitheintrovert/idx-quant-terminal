"""Pasar global (tab GLOBAL): indeks dunia, komoditas, kurs, obligasi, kripto. Hanya informasi.

Simbol Yahoo diatur di config.yaml -> global. Satu baris boleh punya beberapa calon simbol
(dipisah "|"); yang pertama yang mengembalikan data dipakai. Simbol yang gagal dilewati dan dicatat di log.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import data

log = logging.getLogger("global")


def _f(x, d=4):
    try:
        x = float(x)
        return round(x, d) if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _rows(cfg):
    out = []
    for grp, items in (cfg.get("global") or {}).items():
        for name, sym in items.items():
            out.append((grp, name, [s.strip() for s in str(sym).split("|") if s.strip()]))
    return out


def _block(closes: dict, rows, ihsg: pd.Series | None, now):
    ih_r = ihsg.pct_change() if ihsg is not None and len(ihsg) > 30 else None
    y0 = pd.Timestamp(datetime(now.year, 1, 1))
    items, miss = [], []
    for grp, name, cands in rows:
        sym = next((s for s in cands if s in closes), None)
        if sym is None:
            miss.append(f"{name} ({'/'.join(cands)})")
            continue
        cl = closes[sym]

        def ret(k):
            return _f(cl.iloc[-1] / cl.iloc[-1 - k] - 1) if len(cl) > k and cl.iloc[-1 - k] > 0 else None

        def dif(k):
            return _f(cl.iloc[-1] - cl.iloc[-1 - k], 4) if len(cl) > k else None

        prev_y = cl[cl.index < y0]
        corr = None
        if ih_r is not None:
            j = pd.concat([cl.pct_change(), ih_r], axis=1, join="inner").dropna().iloc[-250:]
            if len(j) >= 60:
                corr = _f(j.iloc[:, 0].corr(j.iloc[:, 1]), 2)
        lo, hi = cl.iloc[-252:].min(), cl.iloc[-252:].max()
        if sym != cands[0]:
            log.info("Pasar global: %s memakai simbol cadangan %s", name, sym)
        items.append({"g": grp, "name": name, "sym": sym, "last": _f(cl.iloc[-1], 4), "date": cl.index[-1].strftime("%Y-%m-%d"),
                      "chg": ret(1), "w1": ret(5), "m1": ret(21), "m3": ret(63), "y1": ret(252),
                      "ytd": _f(cl.iloc[-1] / prev_y.iloc[-1] - 1) if len(prev_y) else None,
                      "abs": {"chg": dif(1), "w1": dif(5), "m1": dif(21), "m3": dif(63), "y1": dif(252),
                              "ytd": _f(cl.iloc[-1] - prev_y.iloc[-1], 4) if len(prev_y) else None},
                      "hi52": _f(hi, 4), "lo52": _f(lo, 4), "corr": corr,
                      "spark": [_f(x, 4) for x in cl.iloc[-90:].values]})
    return items, miss


def build(cfg, ihsg: pd.Series | None, now, demo: bool = False) -> dict:
    rows = _rows(cfg)
    if not rows:
        return {}
    closes = {}
    if demo:
        rng = np.random.default_rng(7)
        idx = pd.bdate_range(end=pd.Timestamp(now.date()), periods=300)
        for _, name, cands in rows:
            base = {"Kurs": 15000.0, "Obligasi": 4.2}.get(_, 1000.0)
            closes[cands[0]] = pd.Series(base * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(idx)))), index=idx)
    else:
        syms = sorted({s for _, _, c in rows for s in c})
        start = (now - timedelta(days=420)).strftime("%Y-%m-%d")
        try:
            got = data.fetch_yahoo(syms, start, max_single_retry=len(syms))
        except Exception as e:  # noqa: BLE001
            log.warning("Pasar global gagal diambil: %s", e)
            got = {}
        for s, df in got.items():
            if df is not None and "Close" in df:
                cl = df["Close"].dropna()
                cl = cl[cl > 0]
                if len(cl) >= 5:
                    closes[s] = cl
    items, miss = _block(closes, rows, ihsg, now)
    log.info("Pasar global: %d dari %d instrumen tersedia%s", len(items), len(rows), f"; tidak ada data: {', '.join(miss)}" if miss else "")
    return {"items": items, "missing": miss, "source": "SIMULASI" if demo else "Yahoo Finance"}
