"""Backtest: apakah sentimen memperbaiki model momentum + akumulasi? Hanya ANALISIS.

    python -m engine.sentbt --cache .cache/panels.pkl

Model dasar = model sekarang (flowmom BASE). Varian:
  per saham  : blokir sinyal beli bila skor sentimen/lotre/MAX/IVOL/skew/lonjakan ekstrem tinggi, bila kuintil terdingin,
               atau bila ridge memprediksi terburuk; versi "hanya beli bila ridge ≥ 50".
  pasar      : kurangi jumlah slot posisi bila proxy kontrarian (big caps vs kecil, CMF) sedang tinggi.
Aturan adopsi (sama seperti riset sebelumnya): Calmar lebih baik di KEDUA paruh, lalu cek kepekaan ambang di sekitarnya —
dipakai hanya bila mayoritas tetangga juga lebih baik.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, flowx, fundamentals, regime
from . import sentres as SR
from . import universe as uni_mod
from .flowmom import BASE, build, extras, kpi, pc
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("SBT|", *a, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    now = datetime.now(WIB)
    universe, _, _ = uni_mod.load(cfg, refresh=False)
    if a.demo:
        universe = {k: universe[k] for k in list(universe)[:200]}
        panels, macro = data.demo_data(universe, cfg["macro"], days=2600)
        F = extras(features.compute(panels, cfg))
        flowx.compute(F, {})
    else:
        cache = data.load_cache(a.cache)
        cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
        frames = {t: f for t, f in cache["frames"].items() if t in universe and len(f) and f.index[-1] >= cutoff}
        F = extras(features.compute(data.build_panels(frames, list(frames)), cfg))
        try:
            flowx.compute(F, fundamentals.load(Path(a.cache).parent / "fundamentals.json"))
        except Exception as e:  # noqa: BLE001
            P("flowx dilewati", e)
        syms = {"IHSG": "^JKSE", "USDIDR": "IDR=X", "EIDO": "EIDO", "VIX": "^VIX", "DXY": "DX-Y.NYB", "EEM": "EEM"}
        got = data.fetch_yahoo(list(syms.values()), hist_start(cfg, now))
        macro = {k: got.get(s) for k, s in syms.items() if got.get(s) is not None}
    ihs = macro["IHSG"]["Close"]
    ihs.index = pd.to_datetime(ihs.index).tz_localize(None).normalize() if getattr(ihs.index, "tz", None) else pd.to_datetime(ihs.index).normalize()
    ih = ihs[~ihs.index.duplicated(keep="last")].reindex(F["c"].index, method="ffill")
    reg = regime.compute(ih, F, macro["USDIDR"]["Close"] if "USDIDR" in macro else None)
    comp, cond = build(F, cfg, reg, BASE)
    c = F["c"]
    liq = F["liquid"].fillna(False).astype(bool)

    # ---- skor sentimen historis (walk-forward, sama dengan live) ----
    SP = SR.stock_proxies(F, ih, {t: (universe.get(t) or {}).get("sector") for t in c.columns})
    Zs = {k: SR._xs_z(v, liq) for k, v in SP.items()}
    sc = SR.stock_scores(Zs, liq, np.log(c.shift(-20) / c).clip(-1.5, 1.5))
    pct = {k: sc[k].rank(axis=1, pct=True) for k in ("pca", "ew", "lot", "ridge")}
    for k in ("maxr", "ivol", "skew", "attn"):
        pct[k] = SP[k].where(liq).rank(axis=1, pct=True)
    ext = SP["ext20"]
    ext_p = ext.where(liq).rank(axis=1, pct=True)
    R = SR.market_proxies(F, ih, macro)
    Zm = SR._rz(R)
    start = c.index[400]
    P(f"DATA {c.shape[1]} saham {c.index[0].date()}–{c.index[-1].date()} | skor walk-forward mulai {start.date()} | makro {sorted(macro)}")

    def run(c2, label=None):
        _, det = backtest.run(F, comp, c2, reg, cfg, detail=True)
        return kpi(det["df"], len(det["trades"])), det

    q0, d0 = run(cond)
    n_sig = int(cond["entry"].sum().sum())

    def line(lab, q, nb=None, mark=""):
        P(f"{lab:46s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | "
          f"paruh-1 {pc(q['h'][0][0],0)}/{pc(q['h'][0][1],0)} (C {q['h'][0][2]:.2f}) paruh-2 {pc(q['h'][1][0],0)}/{pc(q['h'][1][1],0)} (C {q['h'][1][2]:.2f})"
          f" | trade/thn {q['tpy']:.0f}{'' if nb is None else f' | sinyal diblokir {nb}'} {mark}")
    line("MODEL SEKARANG", q0)

    def better(q):
        return q["h"][0][2] > q0["h"][0][2] and q["h"][1][2] > q0["h"][1][2]

    def blocked(mask):
        m = mask.reindex_like(cond["entry"]).fillna(False).astype(bool)
        c2 = dict(cond)
        c2["entry"] = cond["entry"] & ~m
        c2["strong"] = cond["strong"] & c2["entry"]
        return c2, int((cond["entry"] & m).sum().sum())

    variants = {
        "blok ⚡ lonjakan ekstrem (≥2 & top 10%)": lambda t=None: (ext >= 2) & (ext_p >= (t or 0.9)),
        "blok lonjakan ekstrem ≥ 3": lambda t=None: ext >= (t or 3),
        "blok MAX top 10%": lambda t=None: pct["maxr"] >= (t or 0.9),
        "blok IVOL top 10%": lambda t=None: pct["ivol"] >= (t or 0.9),
        "blok skew top 10%": lambda t=None: pct["skew"] >= (t or 0.9),
        "blok skor lotre top 10%": lambda t=None: pct["lot"] >= (t or 0.9),
        "blok skor lotre top 20%": lambda t=None: pct["lot"] >= (t or 0.8),
        "blok sentimen PCA top 10% (terpanas)": lambda t=None: pct["pca"] >= (t or 0.9),
        "blok kuintil terdingin (rata-rata ≤ 20%)": lambda t=None: pct["ew"] <= (t or 0.2),
        "blok ridge ≤ 20% (prediksi terburuk)": lambda t=None: pct["ridge"] <= (t or 0.2),
        "hanya beli bila ridge ≥ 50%": lambda t=None: pct["ridge"] < (t or 0.5),
        "blok perhatian top 10%": lambda t=None: pct["attn"] >= (t or 0.9),
    }
    neigh = {"blok ⚡ lonjakan ekstrem (≥2 & top 10%)": [0.8, 0.85, 0.95], "blok lonjakan ekstrem ≥ 3": [2, 4, 5],
             "blok MAX top 10%": [0.8, 0.85, 0.95], "blok IVOL top 10%": [0.8, 0.85, 0.95], "blok skew top 10%": [0.8, 0.85, 0.95],
             "blok skor lotre top 10%": [0.8, 0.85, 0.95], "blok skor lotre top 20%": [0.7, 0.75, 0.85],
             "blok sentimen PCA top 10% (terpanas)": [0.8, 0.85, 0.95], "blok kuintil terdingin (rata-rata ≤ 20%)": [0.1, 0.15, 0.25, 0.3],
             "blok ridge ≤ 20% (prediksi terburuk)": [0.1, 0.15, 0.25, 0.3], "hanya beli bila ridge ≥ 50%": [0.3, 0.4, 0.6],
             "blok perhatian top 10%": [0.8, 0.85, 0.95]}
    P(f"== VARIAN PER SAHAM (sinyal beli dasar {n_sig}) ==")
    passed = []
    res = {}
    for lab, fn in variants.items():
        c2, nb = blocked(fn())
        q, _ = run(c2)
        res[lab] = q
        ok = better(q)
        line(lab, q, nb, "✓ lebih baik di kedua paruh" if ok else "")
        if ok:
            passed.append(lab)

    # ---- pasar: kurangi slot saat proxy kontrarian tinggi ----
    P("== VARIAN PASAR (slot posisi dikurangi) ==")
    for lab, mask in (("bigsm z ≥ 1 → slot ×0,5", Zm["bigsm"] >= 1 if "bigsm" in Zm else None),
                      ("CMF luas z ≥ 1 → slot ×0,5", Zm["flow"] >= 1 if "flow" in Zm else None),
                      ("bigsm atau CMF z ≥ 1 → slot ×0,5", ((Zm.get("bigsm", 0) >= 1) | (Zm.get("flow", 0) >= 1)) if "bigsm" in Zm else None),
                      ("bigsm z ≥ 1,5 → slot ×0,5", Zm["bigsm"] >= 1.5 if "bigsm" in Zm else None)):
        if mask is None:
            continue
        c2 = dict(cond)
        c2["slot_mult"] = pd.Series(np.where(mask.reindex(c.index).fillna(False).values, 0.5, 1.0), index=c.index)
        q, _ = run(c2)
        ok = better(q)
        line(lab, q, None, "✓ lebih baik di kedua paruh" if ok else "")
        if ok:
            passed.append(lab)
            neigh[lab] = []

    # ---- kepekaan untuk yang lolos ----
    P("== KEPEKAAN (ambang tetangga) ==")
    for lab in passed:
        if lab not in variants or not neigh.get(lab):
            P(f"{lab}: tanpa uji tetangga")
            continue
        wins = 0
        for t in neigh[lab]:
            c2, nb = blocked(variants[lab](t))
            q, _ = run(c2)
            w = better(q)
            wins += w
            line(f"  {lab} @ {t}", q, nb, "✓" if w else "")
        P(f"{lab}: {wins}/{len(neigh[lab])} tetangga juga lebih baik di kedua paruh -> {'LOLOS' if wins * 2 > len(neigh[lab]) else 'TIDAK STABIL'}")
    if not passed:
        P("Tidak ada varian yang lebih baik di kedua paruh.")
    P("SELESAI")


if __name__ == "__main__":
    main()
