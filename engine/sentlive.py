"""Sentimen v2 untuk dashboard: level pasar & per saham (proxy, model PCA/PLS/Kalman) + metrik uji yang dihitung
ulang sekali per hari bursa (disimpan di .cache/sent_metrics.json). Rumus & proxy = engine/sentres.py."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import sentres as SR

MKT_LABEL = {"ext": "Lonjakan ekstrem (naik ≥10% − turun ≥6,9%)", "turn": "Nilai transaksi vs normal", "bigsm": "Big caps vs saham kecil",
             "gor": "Porsi transaksi saham < Rp200", "ad": "Saham naik vs turun", "hilo": "Puncak vs dasar 52 minggu",
             "brd": "Saham di atas MA50", "mom": "Momentum IHSG", "vol": "Ketenangan IHSG (volatilitas dibalik)",
             "flow": "Saham diakumulasi (CMF > 0)", "fx": "Rupiah (USD/IDR dibalik)", "onid": "Return semalam − siang",
             "eido": "EIDO 20 hari (minat asing)", "vix": "VIX (dibalik)", "dxy": "Dolar AS (dibalik)", "eem": "Saham negara berkembang (EEM)"}
STK_LABEL = {"aturn": "Transaksi vs normal", "ext20": "Lonjakan ekstrem 20 hari", "rssec": "Kuat vs sektor",
             "rsmkt": "Kuat vs IHSG", "onid": "Return semalam − siang", "vspk": "Lonjakan volatilitas"}


def _r(x, d=3):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


def _pass(o: dict) -> bool:
    """Lolos = arah IC sama di kedua paruh, searah dengan total, dan |t| ≥ 1,96."""
    if not o or o.get("ic") is None:
        return False
    h = o.get("ic_h") or [None, None]
    t = o.get("t_nw", o.get("t"))
    return bool(h[0] is not None and h[1] is not None and np.sign(h[0]) == np.sign(h[1]) == np.sign(o["ic"]) and t is not None and abs(t) >= 1.96)


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    return x


def metrics(R, mm, ih, Zs, liq, c, log=None) -> dict:
    """Metrik uji lengkap (berat: dihitung sekali per hari)."""
    S = mm["series"]
    start = max(s.first_valid_index() for s in S.values() if s.first_valid_index() is not None)
    Zm = SR._rz(R)
    rr = np.log(ih / ih.shift(1))
    mk = {}
    for name in ["v1", "pca", "pls", "kalman"] + list(R.columns):
        s = S.get(name, Zm[name] if name in Zm else None)
        if s is None:
            continue
        s = s[s.index >= start]
        o = {}
        for h in (20, 60):
            try:
                m = SR.market_metrics(s, ih, h)
            except Exception:  # noqa: BLE001
                m = {}
            m["pass"] = _pass(m)
            o[str(h)] = {k: m.get(k) for k in ("ic", "ic_h", "spread", "t_nw", "r2oos", "q", "pass", "n")}
        fa, pa = SR._granger(rr.reindex(s.index).values, s.values)
        fb, pb = SR._granger(s.values, rr.reindex(s.index).values)
        o["g_s2m"], o["g_m2s"] = pa, pb
        mk[name] = o
    fwd = {h: np.log(c.shift(-h) / c).clip(-1.5, 1.5) for h in (5, 20, 60)}
    sc = SR.stock_scores(Zs, liq, fwd[20])
    st0 = c.index[min(400, len(c.index) - 1)]
    sk = {}
    for name in ["ew", "pca", "pls"] + list(Zs):
        Sx = sc[name] if name in ("ew", "pca", "pls") else Zs[name]
        o = {}
        for h in (5, 20, 60):
            m = SR.stock_metrics(Sx, fwd[h], liq, h, start=st0)
            m["pass"] = _pass(m)
            o[str(h)] = {k: m.get(k) for k in ("ic", "ic_h", "t", "pos", "spread", "t_spread", "q", "pass", "n")}
        sk[name] = o
    return {"market": mk, "stock": sk, "start_mkt": str(start.date()), "start_stk": str(st0.date()),
            "w_mkt": list(mm["loadings"].values())[-1] if mm["loadings"] else None,
            "w_stk": list(sc["w"].values())[-1] if sc["w"] else None, "kalman_q": mm["kalman_q"]}


def build(F: dict, ihsg: pd.Series, macro: dict, universe: dict, cache_dir: str | None, nhist: int = 500, log=None) -> dict:
    c = F["c"]
    idx = c.index
    ih = ihsg.reindex(idx).ffill()
    R = SR.market_proxies(F, ih, macro)
    mm = SR.market_models(R, ih)
    S = mm["series"]
    Zm = SR._rz(R)
    liq = F["liquid"].fillna(False).astype(bool)
    sectors = {t: (universe.get(t) or {}).get("sector") for t in c.columns}
    SP = SR.stock_proxies(F, ih, sectors)
    Zs = {k: SR._xs_z(v, liq) for k, v in SP.items()}

    # ---- metrik uji: pakai simpanan bila sudah dihitung untuk bar terakhir ----
    day = str(idx[-1].date())
    path = Path(cache_dir) / "sent_metrics.json" if cache_dir else None
    M = None
    if path and path.exists():
        try:
            old = json.loads(path.read_text())
            if old.get("day") == day and old.get("v") == 1:
                M = old["m"]
        except Exception:  # noqa: BLE001
            M = None
    if M is None:
        M = _clean(metrics(R, mm, ih, Zs, liq, c, log))
        if path:
            try:
                path.write_text(json.dumps({"v": 1, "day": day, "m": M}))
            except Exception:  # noqa: BLE001
                pass

    # ---- kondisi pasar sekarang ----
    def pctl(s, n=750):
        x = s.dropna().iloc[-n:]
        return _r((x < x.iloc[-1]).mean() * 100, 1) if len(x) > 100 else None
    now = {k: {"z": _r(S[k].iloc[-1], 3), "pct": pctl(S[k])} for k in ("pca", "pls", "kalman") if S[k].notna().any()}
    now["v1"] = {"z": None, "pct": _r(S["v1"].iloc[-1], 1)}
    prox = {k: {"label": MKT_LABEL.get(k, k), "z": _r(Zm[k].iloc[-1], 2), "raw": _r(R[k].iloc[-1], 4)} for k in R.columns}
    tail = idx[-nhist:]
    hist = {"d": [str(d.date()) for d in tail]}
    for k in ("pca", "kalman", "v1"):
        x = S[k].reindex(tail)
        if k != "v1":                      # persentil bergulir 750 hari agar sebanding dengan v1 (0–100)
            x = (S[k].rolling(750, min_periods=250).rank(pct=True) * 100).reindex(tail)
        hist[k] = [_r(v, 1) for v in x.values]

    # ---- per saham sekarang ----
    last = idx[-1]
    lq = liq.iloc[-1]
    zl = pd.DataFrame({k: Zs[k].iloc[-1] for k in Zs})
    ew = zl.mean(axis=1, skipna=True).where(lq)
    w = (M.get("w_stk") or {}).get("pca")
    pca = (zl[list(w)] * pd.Series(w)).sum(axis=1, min_count=3).where(lq) if w else ew
    pca_pct = pca.rank(pct=True)
    ew_pct = ew.rank(pct=True)
    ext_pct = SP["ext20"].iloc[-1].where(lq).rank(pct=True) if "ext20" in SP else None
    stocks = {}
    for t in c.columns:
        if not bool(lq.get(t, False)) or not np.isfinite(pca.get(t, np.nan)):
            continue
        e20 = SP["ext20"].iloc[-1].get(t) if "ext20" in SP else None
        stocks[t] = {"sc": _r(pca_pct[t] * 100, 1), "ew": _r(ew_pct[t] * 100, 1),
                     "z": {k: _r(zl.at[t, k], 2) for k in zl.columns},
                     "ext": _r(e20, 0), "extp": _r(ext_pct[t] * 100, 1) if ext_pct is not None and np.isfinite(ext_pct.get(t, np.nan)) else None,
                     "q1": bool(ew_pct[t] <= 0.2)}
    return {"market": {"now": now, "prox": prox, "hist": hist, "metrics": M["market"], "start": M["start_mkt"],
                       "w": M.get("w_mkt"), "kalman_q": M.get("kalman_q"), "day": day},
            "stock_metrics": M["stock"], "stock_start": M["start_stk"], "stock_w": M.get("w_stk"),
            "labels": {"mkt": MKT_LABEL, "stk": STK_LABEL}, "stocks": stocks}
