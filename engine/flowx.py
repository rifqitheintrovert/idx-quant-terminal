"""Inflow lanjutan — empat sudut pandang yang tidak ada di skor flow biasa.

1. Modal pemegang (cost basis / "chip distribution"): tiap hari sebagian saham beredar berpindah tangan
   (turnover = volume ÷ free float). Bagian yang berpindah "dibeli ulang" di kisaran harga hari itu, sisanya tetap
   di harga beli lamanya. Hasilnya: perkiraan harga rata-rata modal pemegang sekarang, persen pemegang yang untung,
   dan zona harga tempat modal menumpuk (calon support / resistance).
2. Return siang vs semalam (Lou, Polk & Skouras): return close->open (order sebelum bursa buka) dipisah dari
   return open->close (selama jam bursa). Naik di siang hari tapi turun semalam = pembeli di jam bursa (cenderung
   institusi) menyerap penjual pembukaan.
3. Rotasi free float: sudah berapa kali seluruh free float berpindah tangan sejak harga terendah 120 hari.
4. Effort vs result (Wyckoff): hari bervolume besar tapi rentang harga sempit = ada yang menyerap. Ditutup di
   paruh atas rentang = serapan beli, paruh bawah = serapan jual.
Semua dihitung dari OHLCV harian; free float dari data fundamental (kalau tidak ada: perkiraan dari volume).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def float_shares(F, fund: dict | None) -> tuple[pd.Series, pd.Series]:
    """Free float per saham (lembar). Kalau tidak ada data: perkiraan = median volume 250 hari × 120 (asumsi float
    berputar sekali dalam ±120 hari bursa). Mengembalikan (float, apakah_perkiraan)."""
    cols = F["c"].columns
    med = F["v"].iloc[-250:].median()
    est = med * 120
    fl = pd.Series(np.nan, index=cols)
    for t in cols:
        q = (fund or {}).get(t) or {}
        f, sh = q.get("float"), q.get("shares")
        v = f if f and f > 0 else (sh * 0.35 if sh and sh > 0 else None)
        if v:
            fl[t] = v
    isest = fl.isna()
    fl = fl.fillna(est).where(lambda x: x > 0)
    return fl, isest


def compute(F, fund: dict | None = None):
    c, o, h, l, v = F["c"], F["o"], F["h"], F["l"], F["v"]
    fl, isest = float_shares(F, fund)
    tau = (v / fl).clip(upper=1.0).fillna(0.0)
    F["tau"] = tau
    F["fl_est"] = isest
    # 1) harga rata-rata modal pemegang (EMA berbobot turnover dari harga tipikal)
    tp = ((h + l + c) / 3).values
    T = tau.values
    cost = np.full(tp.shape, np.nan)
    cur = np.full(tp.shape[1], np.nan)
    for i in range(tp.shape[0]):
        x = tp[i]
        ok = np.isfinite(x)
        fresh = ok & ~np.isfinite(cur)
        cur[fresh] = x[fresh]
        upd = ok & ~fresh
        cur[upd] = cur[upd] * (1 - T[i][upd]) + x[upd] * T[i][upd]
        cost[i] = cur
    F["cost"] = pd.DataFrame(cost, index=c.index, columns=c.columns).where(c.notna())
    F["prem"] = c / F["cost"] - 1                                  # premi harga di atas modal rata-rata pemegang
    # 2) siang vs semalam
    on = np.log(o / c.shift(1)).where((o > 0) & (c.shift(1) > 0))
    idr = np.log(c / o).where((o > 0) & (c > 0))
    for k in (20, 60):
        F[f"on{k}"] = on.rolling(k, min_periods=int(k * 0.7)).sum()
        F[f"id{k}"] = idr.rolling(k, min_periods=int(k * 0.7)).sum()
    F["tug60"] = F["id60"] - F["on60"]
    # 3) rotasi free float sejak low 120 hari
    W = 120
    cv = c.ffill().values
    cs = np.nancumsum(np.nan_to_num(tau.values), axis=0)
    rot = np.full(cv.shape, np.nan)
    rotd = np.full(cv.shape, np.nan)
    if cv.shape[0] >= W:
        win = sliding_window_view(np.where(np.isfinite(cv), cv, np.inf), W, axis=0)       # (n-W+1, m, W)
        am = win.argmin(axis=2)                                                            # posisi low di jendela
        idx = np.arange(W - 1, cv.shape[0])[:, None] - (W - 1) + am                        # indeks baris low
        rows = np.arange(W - 1, cv.shape[0])[:, None]
        colsi = np.arange(cv.shape[1])[None, :]
        rot[W - 1:] = cs[rows, colsi] - cs[idx, colsi]
        rotd[W - 1:] = rows - idx
    F["rot"] = pd.DataFrame(rot, index=c.index, columns=c.columns).where(c.notna())
    F["rot_d"] = pd.DataFrame(rotd, index=c.index, columns=c.columns).where(c.notna())
    # 4) effort vs result
    volr = v / v.rolling(20, min_periods=15).mean()
    rng = (h - l) / F["atr14"].replace(0, np.nan)
    clv = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    absorb = (volr >= 1.5) & (rng <= 0.8)
    F["abs_b"] = (absorb & (clv >= 0)).astype(float).rolling(20, min_periods=10).sum()
    F["abs_s"] = (absorb & (clv < 0)).astype(float).rolling(20, min_periods=10).sum()
    F["absb"] = F["abs_b"] - F["abs_s"]
    F["absorb"] = absorb
    F["absclv"] = clv
    return F


def chip(F, t, n=250, bins=60):
    """Distribusi modal pemegang satu saham (untuk tampilan): bobot per kisaran harga, 250 hari terakhir."""
    c, h, l, tau = F["c"][t].iloc[-n:], F["h"][t].iloc[-n:], F["l"][t].iloc[-n:], F["tau"][t].iloc[-n:]
    ok = c.notna() & h.notna() & l.notna()
    if ok.sum() < 60:
        return None
    lo, hi = float(l[ok].min()), float(h[ok].max())
    if not (hi > lo > 0):
        return None
    edges = np.linspace(lo, hi, bins + 1)
    mid = (edges[:-1] + edges[1:]) / 2
    d = np.zeros(bins)
    for ci, hh, ll, tt in zip(c[ok].values, h[ok].values, l[ok].values, tau[ok].values):
        add = np.clip(np.minimum(edges[1:], hh) - np.maximum(edges[:-1], ll), 0, None)
        if add.sum() <= 0:
            add = np.zeros(bins)
            add[min(bins - 1, max(0, int((ci - lo) / (hi - lo) * bins)))] = 1.0
        add = add / add.sum()
        if d.sum() == 0:
            d = add.copy()
        else:
            d = d * (1 - tt) + add * tt
    d = d / d.sum()
    last = float(c[ok].iloc[-1])
    cdf = np.cumsum(d)
    band = (float(mid[np.searchsorted(cdf, 0.15)]), float(mid[min(bins - 1, np.searchsorted(cdf, 0.85))]))
    peaks = [float(mid[i]) for i in np.argsort(d)[::-1][:12] if (i == 0 or d[i] >= d[i - 1]) and (i == bins - 1 or d[i] >= d[i + 1])][:3]
    return {"p": [round(float(x), 2) for x in mid], "w": [round(float(x), 5) for x in d], "avg": round(float((mid * d).sum()), 2),
            "profit": round(float(d[mid <= last].sum()), 4), "band": [round(band[0], 2), round(band[1], 2)], "peaks": [round(x, 2) for x in peaks]}


def latest(F, t):
    """Angka terakhir per saham untuk snapshot."""
    def g(k, d=4):
        try:
            x = float(F[k][t].iloc[-1])
            return round(x, d) if np.isfinite(x) else None
        except (KeyError, ValueError, TypeError):
            return None
    days = []
    try:
        ab, cl = F["absorb"][t].iloc[-20:], F["absclv"][t].iloc[-20:]
        days = [[d.strftime("%Y-%m-%d"), 1 if cl[d] >= 0 else -1] for d in ab.index[ab.fillna(False).values]]
    except KeyError:
        pass
    return {"cost": g("cost", 2), "prem": g("prem"), "on20": g("on20"), "id20": g("id20"), "on60": g("on60"), "id60": g("id60"),
            "tug": g("tug60"), "rot": g("rot", 3), "rotd": g("rot_d", 0), "absb": g("absb", 0), "abs_b": g("abs_b", 0), "abs_s": g("abs_s", 0),
            "absdays": days, "est": bool(F["fl_est"].get(t, True))}
