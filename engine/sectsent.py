"""Sentimen tiap sektor BEI (IDX-IC) — panel di F5 SENT.

Indeks sektor = rata-rata return harian saham likuid sektor itu (bobot sama, likuid di hari sebelumnya).
Skor 0–100 = rata-rata persentil 3 tahun (sektor itu sendiri) dari 8 komponen:
  harga vs MA125, RSI 14, jarak ke puncak 52 minggu, volatilitas 20 hari (dibalik), return 20 hari,
  % saham di atas MA50, % saham diakumulasi (CMF 20 > 0), % di puncak − % di dasar 52 minggu.
Ditambah ringkasan sentimen per saham (sentimen v2: skor PCA, ridge, lotre, ⚡) dan bukti historis:
return sektor 20/60 hari ke depan DIKURANGI pasar (semua saham likuid) per zona, dengan cek dua paruh.
"""
from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

ZONES = [(0, 25, "Takut ekstrem"), (25, 45, "Takut"), (45, 55, "Netral"), (55, 75, "Serakah"), (75, 101, "Serakah ekstrem")]


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


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

log = logging.getLogger("sectsent")
LABEL = {"mom": "Harga vs MA125", "rsi": "RSI 14", "hi": "Dekat puncak 52 mgg", "vol": "Tenang (vol dibalik)", "r20": "Return 20H",
         "brd": "Saham > MA50", "cmf": "Saham diakumulasi", "hilo": "Puncak − dasar 52 mgg"}


def build(F: dict, universe: dict, s2_stocks: dict | None = None, nhist=504) -> dict:
    t0 = time.time()
    c = F["c"]
    liq = F["liquid"].fillna(False).astype(bool)
    prev = liq.shift(1, fill_value=False)
    r = c.pct_change().where(prev).clip(-0.35, 0.35)
    ma50 = c.rolling(50, min_periods=40).mean()
    hi252 = c.rolling(252, min_periods=200).max()
    lo252 = c.rolling(252, min_periods=200).min()
    cmf = F.get("cmf20")
    secs = {}
    for t in c.columns:
        s = (universe.get(t) or {}).get("sector")
        if s:
            secs.setdefault(s, []).append(t)
    mkt_r = r.mean(axis=1)
    mkt = (1 + mkt_r.fillna(0)).cumprod()
    out, scores, idxs = {}, {}, {}
    for sec, ts in secs.items():
        L = liq[ts]
        n = L.sum(axis=1)
        if n.iloc[-250:].median() < 3:
            continue
        rr = r[ts].mean(axis=1).where(r[ts].notna().sum(axis=1) >= 2)
        ix = (1 + rr.fillna(0)).cumprod()
        live = L.sum(axis=1) >= 3
        parts = {
            "mom": ix / ix.rolling(125).mean() - 1, "rsi": _rsi(ix), "hi": ix / ix.rolling(252, min_periods=120).max(),
            "vol": -rr.rolling(20).std(), "r20": ix / ix.shift(20) - 1,
            "brd": (c[ts] > ma50[ts]).where(L).sum(axis=1) / n.replace(0, np.nan),
            "hilo": ((c[ts] >= hi252[ts] * 0.98).where(L).sum(axis=1) - (c[ts] <= lo252[ts] * 1.02).where(L).sum(axis=1)) / n.replace(0, np.nan),
        }
        if cmf is not None:
            parts["cmf"] = (cmf[ts] > 0).where(L).sum(axis=1) / n.replace(0, np.nan)
        P = pd.DataFrame({k: v.where(live).rolling(756, min_periods=250).rank(pct=True) for k, v in parts.items()})
        sc = (P.mean(axis=1).where(P.notna().sum(axis=1) >= 6) * 100).where(live)
        s_ = sc.dropna()
        if not len(s_):
            continue
        scores[sec], idxs[sec] = sc, ix
        h = sc.iloc[-nhist:]
        rel = ix / mkt

        def ch(k, x=ix):
            return _f(x.iloc[-1] / x.iloc[-1 - k] - 1) if len(x) > k else None
        row = {"n": int(L.iloc[-1].sum()), "s": _f(s_.iloc[-1], 1), "z": _zone(s_.iloc[-1]),
               "w1": _f(sc.iloc[-6], 1), "m1": _f(sc.iloc[-22], 1), "m3": _f(sc.iloc[-64], 1),
               "parts": {k: _f(P[k].iloc[-1] * 100, 0) for k in P},
               "raw": {"brd": _f(parts["brd"].iloc[-1], 3), "cmf": _f(parts["cmf"].iloc[-1], 3) if "cmf" in parts else None, "hilo": _f(parts["hilo"].iloc[-1], 3)},
               "r1": ch(1), "r5": ch(5), "r21": ch(21), "r63": ch(63), "x21": ch(21, rel), "x63": ch(63, rel),
               "h": [_f(x, 0) for x in h.values],
               "px": [_f(x, 4) for x in ix.iloc[-nhist:].values]}
        if s2_stocks:                                          # agregat sentimen per saham (sentimen v2)
            xs = [s2_stocks[t] for t in ts if t in s2_stocks]
            if xs:
                def avg(k):
                    v = [x.get(k) for x in xs if x.get(k) is not None]
                    return _f(np.mean(v), 1) if v else None
                row["stk"] = {"n": len(xs), "sc": avg("sc"), "rdg": avg("rdg"), "lot": avg("lot"),
                              "lot80": int(sum(1 for x in xs if (x.get("lot") or 0) >= 80)),
                              "spike": int(sum(1 for x in xs if (x.get("extp") or 0) >= 90 and (x.get("ext") or 0) >= 2)),
                              "top": [t for t, x in sorted(((t, s2_stocks[t]) for t in ts if t in s2_stocks), key=lambda z: -(z[1].get("rdg") or 0))[:3]]}
        out[sec] = row
    # bukti historis gabungan: return sektor dikurangi pasar, per zona
    rows = []
    for sec, sc in scores.items():
        ix = idxs[sec]
        ex20 = ix.shift(-20) / ix - mkt.shift(-20) / mkt
        ex60 = ix.shift(-60) / ix - mkt.shift(-60) / mkt
        rows.append(pd.DataFrame({"s": sc, "x20": ex20, "x60": ex60}).dropna(subset=["s"]))
    ev = {}
    if rows:
        big = pd.concat(rows)
        mid = big.index.sort_values()[len(big) // 2]
        ev = {"mid": str(mid.date()), "zones": {}, "start": str(big.index.min().date())}
        for lo, hi, z in ZONES:
            sub = big[(big.s >= lo) & (big.s < hi)]
            row = {"n": int(len(sub))}
            for k in ("x20", "x60"):
                x = sub[k].dropna()
                if len(x) < 40:
                    continue
                h = [x[x.index < mid], x[x.index >= mid]]
                hm = [hh.mean() if len(hh) >= 15 else np.nan for hh in h]
                row[k] = {"m": _f(x.mean()), "pos": _f((x > 0).mean(), 3), "h": [_f(hm[0]), _f(hm[1])],
                          "ok": bool(np.isfinite(hm[0]) and np.isfinite(hm[1]) and np.sign(hm[0]) == np.sign(hm[1]) != 0)}
            ev["zones"][z] = row
    res = {"sectors": out, "ev": ev, "labels": LABEL, "asof": str(c.index[-1].date()), "hd": [str(d.date()) for d in c.index[-nhist:]]}
    log.info("Sentimen sektor (%.1f dtk): %s | bukti 60H per zona %s", time.time() - t0,
             sorted([(k, v["s"], v["z"]) for k, v in out.items()], key=lambda x: -(x[1] or 0)),
             {z: ((v.get("x60") or {}).get("m"), (v.get("x60") or {}).get("ok")) for z, v in ev.get("zones", {}).items()})
    return res
