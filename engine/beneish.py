"""Beneish M-score (Beneish 1999) — saringan statistik pola manipulasi laba, dari laporan keuangan tahunan.

    M = −4,84 + 0,92 DSRI + 0,528 GMI + 0,404 AQI + 0,892 SGI + 0,115 DEPI − 0,172 SGAI + 4,679 TATA − 0,327 LVGI

  M > −1,78  -> pola angka mirip perusahaan yang terbukti memanipulasi laporan ("berisiko")
  M > −2,22  -> zona abu-abu
Komponen yang datanya tidak ada dianggap netral (rasio 1, TATA 0). Tidak berlaku untuk bank/keuangan.

Titik-waktu (tanpa mengintip masa depan): skor tahun buku T baru dianggap diketahui
`lag_days` setelah tanggal tutup buku (POJK 14/2022: laporan tahunan paling lambat akhir bulan ke-3).
Rumusnya sama persis dengan versi tampilan di site/app.js (fungsi `beneish`).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

W = {"DSRI": 0.92, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892, "DEPI": 0.115, "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327}
RISK, GREY = -1.78, -2.22
FIN_WORDS = ("financ", "bank", "insurance")


def is_financial(sector: str | None, ysector: str | None = None) -> bool:
    s = f"{sector or ''} {ysector or ''}".lower()
    return any(w in s for w in FIN_WORDS)


def _ok(*x):
    return all(v is not None and isinstance(v, (int, float)) and math.isfinite(v) for v in x)


def mscore(A: dict, i: int) -> dict | None:
    """M-score tahun ke-i vs i−1 dari blok laporan tahunan {'p': [...], 'rev': [...], ...}."""
    if not A or i < 1:
        return None

    def g(k, j):
        v = A.get(k)
        return v[j] if v is not None and j < len(v) else None

    def r(x, y):
        return x / y if _ok(x, y) and y != 0 else None

    def gm(j):
        rv, gp, cg = g("rev", j), g("gp", j), g("cogs", j)
        if gp is None and _ok(rv, cg):
            gp = rv - cg
        return r(gp, rv)

    def soft(j):
        ca, pp, ta = g("ca", j), g("ppe", j), g("ta", j)
        return 1 - (ca + pp) / ta if _ok(ca, pp, ta) and ta > 0 else None

    def depr(j):
        d, p = g("dep", j), g("ppe", j)
        if d is None:
            d = g("da", j)
        return d / (d + p) if _ok(d, p) and d + p > 0 else None

    def lev(j):
        cl, ta, ltd = g("cl", j), g("ta", j), g("ltd", j)
        return (cl + (ltd or 0)) / ta if _ok(cl, ta) and ta > 0 else None

    ni, ocf, ta = g("ni", i), g("ocf", i), g("ta", i)
    v = {"DSRI": r(r(g("rec", i), g("rev", i)), r(g("rec", i - 1), g("rev", i - 1))), "GMI": r(gm(i - 1), gm(i)),
         "AQI": r(soft(i), soft(i - 1)), "SGI": r(g("rev", i), g("rev", i - 1)), "DEPI": r(depr(i - 1), depr(i)),
         "SGAI": r(r(g("sga", i), g("rev", i)), r(g("sga", i - 1), g("rev", i - 1))),
         "TATA": (ni - ocf) / ta if _ok(ni, ocf, ta) and ta > 0 else None, "LVGI": r(lev(i), lev(i - 1))}
    if v["TATA"] is None or v["SGI"] is None:
        return None
    m, neutral = -4.84, []
    for k, w in W.items():
        x = v[k]
        if x is None or not math.isfinite(x) or (k != "TATA" and (x <= 0 or x > 20)) or (k == "TATA" and abs(x) > 2):
            neutral.append(k)
            x = 0.0 if k == "TATA" else 1.0
            v[k] = None
        m += w * x
    ends = A.get("end") or []
    return {"m": m, "v": v, "neutral": neutral, "y": (A.get("p") or [None] * (i + 1))[i],
            "end": ends[i] if i < len(ends) else None}


def history(q: dict, sector: str | None = None) -> list[dict]:
    """Semua M-score yang bisa dihitung untuk satu saham (lama -> baru). Kosong untuk bank/keuangan."""
    if not q or is_financial(sector, q.get("ysector")):
        return []
    A = (q.get("fs") or {}).get("a") or {}
    out = []
    for i in range(1, len(A.get("p") or [])):
        b = mscore(A, i)
        if b:
            out.append(b)
    return out


def level(m: float | None) -> str | None:
    if m is None:
        return None
    return "risk" if m > RISK else "grey" if m > GREY else "ok"


def latest(q: dict, sector: str | None = None, asof: pd.Timestamp | None = None, lag_days: int = 95) -> dict | None:
    """Skor terbaru yang SUDAH terbit pada `asof` (default: sekarang) -> ringkasan untuk dashboard/sinyal."""
    h = history(q, sector)
    if asof is not None:
        h = [b for b in h if b["end"] and pd.Timestamp(b["end"]) + pd.Timedelta(days=lag_days) <= asof]
    if not h:
        return None
    b = h[-1]
    return {"m": round(b["m"], 2), "y": b["y"], "lvl": level(b["m"]), "nn": len(b["neutral"]),
            "prev": round(h[-2]["m"], 2) if len(h) >= 2 else None}


def panel(fund: dict, sectors: dict, index: pd.DatetimeIndex, columns, lag_days: int = 95) -> pd.DataFrame:
    """Panel M-score titik-waktu (tanggal × saham): nilai berlaku sejak laporan dianggap terbit, NaN sebelum ada data."""
    P = pd.DataFrame(np.nan, index=index, columns=list(columns))
    for t in P.columns:
        for b in history(fund.get(t) or {}, sectors.get(t)):
            if not b["end"]:
                continue
            d0 = pd.Timestamp(b["end"]) + pd.Timedelta(days=lag_days)
            P.loc[P.index >= d0, t] = b["m"]          # urutan lama -> baru: skor baru menimpa yang lama
    return P
