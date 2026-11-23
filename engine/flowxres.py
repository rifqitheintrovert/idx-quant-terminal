"""Riset: apakah empat metode inflow lanjutan memperbaiki model? Hanya ANALISIS.

    python -m engine.flowxres --cache .cache/panels.pkl

Model dasar = model dashboard sekarang. Tiap varian menambah SATU syarat beli (atau mengganti skor flow) dari
engine/flowx.py. Yang dianggap lebih baik hanya yang Calmar-nya lebih tinggi di paruh latih DAN paruh uji.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, flowx, fundamentals, regime
from . import indicators as ind
from . import universe as uni_mod
from .flowmom import BASE, build, extras, kpi, pc
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("FX|", *a, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--no-macro", action="store_true")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    now = datetime.now(WIB)
    cache = data.load_cache(a.cache)
    if not cache:
        raise SystemExit("cache histori tidak ditemukan — jalankan update dulu")
    universe, _, _ = uni_mod.load(cfg, refresh=False)
    cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
    frames = {t: f for t, f in cache["frames"].items() if t in universe and len(f) and f.index[-1] >= cutoff}
    panels = data.build_panels(frames, list(frames))
    macro = {}
    if not a.no_macro:
        try:
            got = data.fetch_yahoo([cfg["macro"]["IHSG"], cfg["macro"]["USDIDR"]], hist_start(cfg, now))
            macro = {"IHSG": got.get(cfg["macro"]["IHSG"]), "USDIDR": got.get(cfg["macro"]["USDIDR"])}
        except Exception as e:  # noqa: BLE001
            P("makro gagal:", e)
    F = extras(features.compute(panels, cfg))
    fund = fundamentals.load(Path(a.cache).parent / "fundamentals.json")
    flowx.compute(F, fund)
    P(f"free float dari data fundamental: {int((~F['fl_est']).sum())} saham, perkiraan dari volume: {int(F['fl_est'].sum())}")
    ih = macro["IHSG"]["Close"] if macro.get("IHSG") is not None else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    reg = regime.compute(ih, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)
    liq = F["liquid"]

    def xs(p):
        return ind.pct_rank_xs(p.where(liq))

    R = {"tug": xs(F["tug60"]), "abs": xs(F["absb"]), "prem": xs(F["prem"]), "rot": xs(F["rot"])}
    flow0 = F["flow_B"]
    F["flow_X1"] = features._nanmean([flow0, flow0, R["tug"]])                 # 2/3 flow + 1/3 siang-semalam
    F["flow_X2"] = features._nanmean([flow0, flow0, R["abs"]])
    F["flow_X3"] = features._nanmean([flow0, flow0, flow0, R["tug"], R["abs"]])

    FILT = {
        "m1 harga > modal rata-rata pemegang": F["prem"] > 0,
        "m2 premi modal 0–30%": (F["prem"] > 0) & (F["prem"] < 0.30),
        "m3 premi modal < 50%": F["prem"] < 0.50,
        "m4 premi modal < 0 (di bawah modal)": F["prem"] < 0,
        "s1 siang−semalam 60H > 0": F["tug60"] > 0,
        "s2 siang 20H > 0": F["id20"] > 0,
        "s3 siang−semalam top 50%": R["tug"] >= 50,
        "s4 semalam 20H < 0 & siang 20H > 0": (F["on20"] < 0) & (F["id20"] > 0),
        "r1 rotasi float ≥ 0,5x": F["rot"] >= 0.5,
        "r2 rotasi float ≥ 1x": F["rot"] >= 1.0,
        "r3 rotasi float ≤ 3x": F["rot"] <= 3.0,
        "w1 serapan bersih ≥ 1": F["absb"] >= 1,
        "w2 serapan bersih ≥ 0": F["absb"] >= 0,
        "w3 tanpa serapan jual 20H": F["abs_s"] == 0,
    }
    SCORES = {"f1 skor flow + siang−semalam": "X1", "f2 skor flow + serapan": "X2", "f3 skor flow + keduanya": "X3"}

    memo = {}

    def ev(filt=None, flow="B", bt=None):
        key = (filt, flow, tuple(sorted((bt or {}).items())))
        if key not in memo:
            c2 = cfg if not bt else copy.deepcopy(cfg)
            if bt:
                c2["backtest"].update(bt)
            comp, cond = build(F, c2, reg, {**BASE, "flow": flow})
            if filt:
                m = None
                for f in filt.split("+"):
                    x = FILT[f].reindex_like(cond["entry"]).fillna(False).astype(bool)
                    m = x if m is None else (m & x)
                cond = dict(cond)
                cond["entry"] = cond["entry"] & m
                cond["strong"] = cond["strong"] & cond["entry"]
            _, det = backtest.run(F, comp, cond, reg, c2, detail=True)
            memo[key] = kpi(det["df"], len(det["trades"]))
        return memo[key]

    def line(label, q):
        P(f"{label:44s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | "
          f"LATIH {pc(q['h'][0][0],0)}/{pc(q['h'][0][1],0)} UJI {pc(q['h'][1][0],0)}/{pc(q['h'][1][1],0)} | "
          f"thn terburuk {pc(q['yr'].min(),0)} | {q['tpy']:.0f} trade/thn | akhir Rp{q['final']/1e6:,.1f} jt")

    q0 = ev()
    P(f"DATA {F['c'].shape[1]} saham | {F['c'].index[0].date()} s/d {F['c'].index[-1].date()} | modal Rp{cfg['backtest']['initial_equity']/1e6:g} jt")
    line("MODEL SEKARANG", q0)

    def better(q):
        return q["h"][0][2] > q0["h"][0][2] and q["h"][1][2] > q0["h"][1][2]

    P("== SATU SYARAT TAMBAHAN ==")
    res = []
    for f in FILT:
        q = ev(f)
        res.append((f, q))
        line(f + (" ✓" if better(q) else ""), q)
    P("== SKOR FLOW DIPERKAYA (syarat sama: flow ≥ 60, momentum ≥ 70) ==")
    for lab, fl in SCORES.items():
        q = ev(None, fl)
        res.append((lab, q))
        line(lab + (" ✓" if better(q) else ""), q)
    good = [f for f, q in res if better(q) and f in FILT]
    P("lolos di kedua paruh:", [f for f, q in res if better(q)] or "TIDAK ADA")
    if len(good) >= 2:
        P("== GABUNGAN DUA SYARAT YANG LOLOS ==")
        for i, f1 in enumerate(good):
            for f2 in good[i + 1:]:
                if f1[0] != f2[0]:
                    q = ev(f1 + "+" + f2)
                    line(f"{f1[:2]}+{f2[:2]}" + (" ✓" if better(q) else ""), q)
    best = max((r for r in res if better(r[1])), key=lambda r: min(r[1]["h"][0][2], r[1]["h"][1][2]), default=None)
    if best:
        f, q = best
        P(f"== KESTABILAN: {f} ==")
        line("pilihan", q)
        line("sekarang", q0)
        P("per tahun pilihan : " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q["yr"].items()))
        P("per tahun sekarang: " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q0["yr"].items()))
        fl = SCORES.get(f, "B")
        flt = f if f in FILT else None
        for lab, bt in [("modal Rp100 jt", {"initial_equity": 100_000_000}), ("risiko 0,75%", {"risk_per_trade": 0.0075}),
                        ("risiko 1,25%", {"risk_per_trade": 0.0125}), ("6 posisi", {"max_positions": 6}), ("10 posisi", {"max_positions": 10})]:
            line("  " + lab + " | pilihan", ev(flt, fl, bt))
            line("  " + lab + " | sekarang", ev(None, "B", bt))
    # potret hari ini
    t = F["c"].index[-1]
    L = {k: F[k].loc[t] for k in ("prem", "tug60", "rot", "absb")}
    lq = liq.loc[t]
    P(f"hari ini (saham likuid): median premi modal {L['prem'][lq].median()*100:+.1f}% | siang−semalam 60H > 0: "
      f"{(L['tug60'][lq] > 0).mean()*100:.0f}% saham | median rotasi float {L['rot'][lq].median():.2f}x | serapan bersih > 0: {(L['absb'][lq] > 0).mean()*100:.0f}% saham")
    P("SELESAI")


if __name__ == "__main__":
    main()
