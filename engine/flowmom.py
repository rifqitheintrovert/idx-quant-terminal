"""Riset: model yang HANYA bertumpu pada momentum + akumulasi inflow. Hanya ANALISIS.

    python -m engine.flowmom --cache .cache/panels.pkl

Semua varian memakai mesin backtest & aturan risiko yang sama dengan dashboard. Yang diubah hanya:
  flow   definisi skor inflow (A = sekarang, B = akumulasi panjang 60 hari, C = gabungan pendek+panjang)
  mom    definisi skor momentum (A = sekarang, B = menengah 3-6 bln, C = termasuk bulan terakhir, D = disesuaikan risiko)
  w      bobot skor (flow, momentum, tren, timing)
  gate   syarat tambahan saat beli (status akumulasi, inflow berkelanjutan, flow & momentum sama-sama kuat, dekat high 52 mgg)
  exit   aturan keluar (sekarang / + keluar saat distribusi / hanya trailing)
  buy    ambang skor beli
Anti-overfitting: pilihan dibuat dari PARUH PERTAMA (latih), hasil PARUH KEDUA (uji) dilaporkan apa adanya.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import math
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, regime
from . import indicators as ind
from . import universe as uni_mod
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("FM|", *a, flush=True)


def pc(x, d=1):
    return f"{x * 100:+.{d}f}%"


# ------------------------------------------------------------------ fitur tambahan akumulasi
def extras(F):
    c, h, l, v = F["c"], F["h"], F["l"], F["v"]
    value, nf, base = F["value"], F["nf1"], F["avg_val60"].replace(0, np.nan)
    F["nf60"] = nf.rolling(60, min_periods=40).sum()
    F["nf60_int"] = F["nf60"] / (base * 60)
    F["accdays20"] = (nf > 0).rolling(20, min_periods=20).mean().where(c.notna())
    F["accdays60"] = (nf > 0).rolling(60, min_periods=40).mean().where(c.notna())
    up = value.where(c > c.shift(1), 0.0)
    dn = value.where(c < c.shift(1), 0.0)
    F["updn50"] = (up.rolling(50, min_periods=30).sum() / dn.rolling(50, min_periods=30).sum().replace(0, np.nan)).where(c.notna())
    F["cmf60"] = ind.cmf(h, l, c, v, 60)
    F["obvm60"] = ind.obv_momentum(c, v, 60)
    vol63 = c.pct_change().rolling(63, min_periods=40).std().replace(0, np.nan)
    F["ramom"] = F["ret126"] / (vol63 * math.sqrt(126))
    liq = F["liquid"]

    def xs(p):
        return ind.pct_rank_xs(p.where(liq))

    nm = features._nanmean
    F["flow_A"] = F["s_flow"]
    F["flow_B"] = nm([xs(F["nf20_int"]), xs(F["nf60_int"]), xs(F["cmf20"]), xs(F["cmf60"]), xs(F["obvm60"]),
                      xs(F["updn50"]), xs(F["accdays60"])])
    F["flow_C"] = nm([xs(F["nf5_int"]), xs(F["nf20_int"]), xs(F["nf60_int"]), xs(F["cmf20"]), xs(F["obvm20"]),
                      xs(F["updn50"]), xs(F["accdays20"])])
    F["mom_A"] = F["s_mom"]
    F["mom_B"] = nm([xs(F["mom_6_1"]), xs(F["ret63"]), xs(F["prox52"])])
    F["mom_C"] = nm([xs(F["ret126"]), xs(F["ret63"]), xs(F["ret21"]), xs(F["prox52"])])
    F["mom_D"] = nm([xs(F["ramom"]), xs(F["prox52"]), xs(F["mom_6_1"])])
    return F


W = {  # (flow, momentum, tren, timing)
    "w0 30/25/20/10 (sekarang)": (30, 25, 20, 10),
    "w1 50/50/0/0": (50, 50, 0, 0),
    "w2 40/40/20/0": (40, 40, 20, 0),
    "w3 40/40/10/10": (40, 40, 10, 10),
    "w4 60/40/0/0": (60, 40, 0, 0),
    "w5 40/60/0/0": (40, 60, 0, 0),
    "w6 45/45/0/10": (45, 45, 0, 10),
    "w7 100/0 (flow saja)": (100, 0, 0, 0),
    "w8 0/100 (momentum saja)": (0, 100, 0, 0),
    "w9 35/50/15/0": (35, 50, 15, 0),
}
GATES = ["g0 sekarang", "g1 +status akumulasi", "g2 +inflow 20h & 60h positif", "g3 +flow>=60 & mom>=60",
         "g4 +flow>=70 & mom>=70", "g5 +harga >=80% high 52mgg", "g6 +flow>=50 & mom>=50", "g7 g2 + g5"]
EXITS = ["x0 sekarang", "x1 +keluar saat distribusi", "x2 hanya trailing & MA50"]
BASE = {"flow": "A", "mom": "A", "w": "w0 30/25/20/10 (sekarang)", "gate": GATES[0], "exit": EXITS[0], "buy": 60}


def build(F, cfg, reg, v):
    s = cfg["signal"]
    c = F["c"]
    sf, sm = F["flow_" + v["flow"]], F["mom_" + v["mom"]]
    wf, wm, wt, wz = W[v["w"]]
    comp = (sf * wf + sm * wm + F["s_trend"] * wt + F["s_timing"] * wz) / (wf + wm + wt + wz)
    trend_ok = (c > F["ma50"]) & (F["ma20"] > F["ma50"])
    flow_any = (F["cmf20"] > 0) | (F["nf5"] > 0)
    flow_both = (F["cmf20"] > 0) & (F["nf5"] > 0)
    not_ob = F["rsi14"] < s["rsi_overbought"]
    ex = v["exit"][:2]
    exit_ = (c < F["chandelier"]) | ((c < F["ma50"]) & (F["cmf20"] < 0))
    if ex != "x2":
        exit_ = exit_ | (comp < s["exit"])
    if ex == "x1":
        exit_ = exit_ | (F["acc"] == -1)
    entry = F["liquid"] & (comp >= v["buy"]) & trend_ok & flow_any & not_ob & ~exit_
    g = v["gate"][:2]
    if g == "g1":
        entry &= F["acc"] == 1
    if g in ("g2", "g7"):
        entry &= (F["nf20"] > 0) & (F["nf60"] > 0)
    if g == "g3":
        entry &= (sf >= 60) & (sm >= 60)
    if g == "g4":
        entry &= (sf >= 70) & (sm >= 70)
    if g == "g6":
        entry &= (sf >= 50) & (sm >= 50)
    if g in ("g5", "g7"):
        entry &= F["prox52"] >= 0.80
    if v["gate"].startswith("t"):                # "t70/65" = skor flow >= 70 dan skor momentum >= 65
        tf, tm = [float(x) for x in v["gate"][1:].split("/")]
        entry &= (sf >= tf) & (sm >= tm)
    if s.get("max_atr_pct"):
        entry &= F["atr_pct"] <= float(s["max_atr_pct"])
    if s.get("market_filter"):
        gate = (reg["ihsg"] > reg[str(s["market_filter"]).lower()]).reindex(c.index).fillna(False).astype(bool)
        entry &= gate.values[:, None]
    strong = entry & (comp >= v["buy"] + 10) & flow_both & (F["rsi14"] < s["rsi_overbought"] - 3)
    return comp, {"entry": entry, "strong": strong, "exit": exit_}


def kpi(df, n_tr):
    eq = df["eq"]
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    ann = len(eq) / yrs
    r = eq.pct_change().dropna()
    last = eq.groupby(eq.index.year).last()
    yr = last.pct_change()
    yr.iloc[0] = last.iloc[0] / eq.iloc[0] - 1
    mid = eq.index[len(eq) // 2]
    hv = []
    for h in (eq[:mid], eq[mid:]):
        y = (h.index[-1] - h.index[0]).days / 365.25
        cg, md = (h.iloc[-1] / h.iloc[0]) ** (1 / y) - 1, float((h / h.cummax() - 1).min())
        hv.append((cg, md, cg / abs(md) if md < 0 else 0.0))
    cagr, mdd = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1, float((eq / eq.cummax() - 1).min())
    return {"h": hv, "cagr": cagr, "mdd": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else 0.0,
            "sharpe": (r.mean() * ann - 0.05) / (r.std() * math.sqrt(ann)) if r.std() > 0 else 0.0,
            "inv": df["inv"].mean(), "final": eq.iloc[-1], "yr": yr, "tpy": n_tr / yrs}


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
    tickers = list(frames)
    panels = data.build_panels(frames, tickers)
    macro = {}
    if not a.no_macro:
        try:
            got = data.fetch_yahoo([cfg["macro"]["IHSG"], cfg["macro"]["USDIDR"]], hist_start(cfg, now))
            macro = {"IHSG": got.get(cfg["macro"]["IHSG"]), "USDIDR": got.get(cfg["macro"]["USDIDR"])}
        except Exception as e:  # noqa: BLE001
            P("makro gagal:", e)
    F = extras(features.compute(panels, cfg))
    ih = macro["IHSG"]["Close"] if macro.get("IHSG") is not None else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    reg = regime.compute(ih, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)

    memo = {}

    def ev(v, bt=None):
        key = (tuple(sorted(v.items())), tuple(sorted((bt or {}).items())))
        if key not in memo:
            c2 = cfg
            if bt:
                c2 = copy.deepcopy(cfg)
                c2["backtest"].update(bt)
            comp, cond = build(F, c2, reg, v)
            out, det = backtest.run(F, comp, cond, reg, c2, detail=True)
            memo[key] = kpi(det["df"], len(det["trades"]))
        return memo[key]

    def name(v):
        return f"flow{v['flow']} mom{v['mom']} {v['w'][:2]} {v['gate'][:2]} {v['exit'][:2]} buy{v['buy']}"

    def line(label, q):
        y = q["yr"]
        P(f"{label:44s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | "
          f"LATIH {pc(q['h'][0][0],0)}/{pc(q['h'][0][1],0)} UJI {pc(q['h'][1][0],0)}/{pc(q['h'][1][1],0)} | "
          f"thn terburuk {pc(y.min(),0)} | invest {q['inv']*100:.0f}% | {q['tpy']:.0f} trade/thn | akhir Rp{q['final']/1e6:,.1f} jt")

    q0 = ev(BASE)
    if os.environ.get("FM_STAGE", "") == "grid":
        return grid(ev, line, q0)
    P(f"DATA {len(tickers)} saham | modal awal Rp{cfg['backtest']['initial_equity']/1e6:g} jt | aturan risiko = dashboard")
    line("DASAR (model sekarang)", q0)

    # ---------- tahap 1: ubah satu hal dari model sekarang ----------
    dims = {"flow": ["A", "B", "C"], "mom": ["A", "B", "C", "D"], "w": list(W), "gate": GATES, "exit": EXITS, "buy": [55, 60, 65, 70]}
    labels = {"flow": "skor inflow", "mom": "skor momentum", "w": "bobot", "gate": "syarat beli", "exit": "aturan keluar", "buy": "ambang beli"}
    best = {}
    P("== TAHAP 1: ubah SATU hal dari model sekarang ==")
    for d, opts in dims.items():
        P(f"-- {labels[d]} --")
        res = []
        for o in opts:
            q = ev({**BASE, d: o})
            res.append((q["h"][0][2], o))
            line(f"{d}={o}", q)
        res.sort(key=lambda x: -x[0])
        keep = int(os.environ.get("FM_KEEP_" + d.upper(), 3 if d in ("w", "gate") else 2))
        best[d] = [o for _, o in res[:keep]]
        P(f"   terbaik di paruh latih: {best[d]}")

    # ---------- tahap 2: gabungan pilihan terbaik (dipilih dari paruh latih) ----------
    combos = [dict(zip(best, x)) for x in itertools.product(*best.values())]
    P(f"== TAHAP 2: {len(combos)} gabungan dari pilihan terbaik per dimensi ==")
    res = [(ev(v), v) for v in combos]
    res.sort(key=lambda x: -x[0]["h"][0][2])
    P("-- 15 teratas menurut PARUH LATIH (Calmar latih); kolom UJI = di luar sampel --")
    for q, v in res[:15]:
        line(name(v), q)
    P("-- 15 teratas menurut 10 tahun penuh (Calmar) --")
    for q, v in sorted(res, key=lambda x: -x[0]["calmar"])[:15]:
        line(name(v), q)
    P("-- 10 teratas menurut paruh TERLEMAH (min Calmar latih, uji) = paling konsisten --")
    rob = sorted(res, key=lambda x: -min(x[0]["h"][0][2], x[0]["h"][1][2]))
    for q, v in rob[:10]:
        line(name(v), q)
    P("-- 10 teratas menurut CAGR 10 tahun dengan DD tidak lebih dalam dari model sekarang --")
    ok = [x for x in res if x[0]["mdd"] >= q0["mdd"] - 0.005]
    for q, v in sorted(ok, key=lambda x: -x[0]["cagr"])[:10]:
        line(name(v), q)
    med = np.median([x[0]["h"][1][0] for x in res]), np.median([x[0]["h"][1][1] for x in res])
    P(f"median semua gabungan di paruh UJI: CAGR {pc(med[0])} DD {pc(med[1])} | model sekarang UJI {pc(q0['h'][1][0])}/{pc(q0['h'][1][1])} "
      f"| gabungan yg mengalahkan model sekarang di KEDUA paruh (Calmar): "
      f"{sum(1 for x in res if x[0]['h'][0][2] > q0['h'][0][2] and x[0]['h'][1][2] > q0['h'][1][2])}/{len(res)}")

    # ---------- tahap 3: pilihan (otomatis = juara paruh latih; manual lewat FM_PICK) ----------
    pick = res[0][1]
    env = os.environ.get("FM_PICK", "").strip()
    if env:                                   # mis. "C,B,w1,g2,x0,60"
        f_, m_, w_, g_, x_, b_ = [x.strip() for x in env.split(",")]
        pick = {"flow": f_, "mom": m_, "w": next(k for k in W if k.startswith(w_)), "gate": next(k for k in GATES if k.startswith(g_)),
                "exit": next(k for k in EXITS if k.startswith(x_)), "buy": int(b_)}
    P(f"== TAHAP 3: PILIHAN {name(pick)} ==")
    q = ev(pick)
    line("pilihan", q)
    line("model sekarang", q0)
    P("per tahun pilihan : " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q["yr"].items()))
    P("per tahun sekarang: " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q0["yr"].items()))
    P("-- tetangga pilihan (ubah satu hal) = uji kestabilan --")
    for d, opts in dims.items():
        for o in opts:
            if o != pick[d]:
                line(f"  {d}={str(o)[:28]}", ev({**pick, d: o}))
    P("-- pilihan dengan pengaturan risiko lain --")
    for lab, bt in [("risiko 0,75%/trade", {"risk_per_trade": 0.0075}), ("risiko 1,25%/trade", {"risk_per_trade": 0.0125}),
                    ("risiko 1,5%/trade", {"risk_per_trade": 0.015}), ("6 posisi", {"max_positions": 6}),
                    ("10 posisi", {"max_positions": 10}), ("12 posisi, maks 15%/saham", {"max_positions": 12, "max_weight": 0.15}),
                    ("maks 25%/saham", {"max_weight": 0.25}), ("rem DD 10%", {"dd_brake": 0.10}), ("tanpa rem DD", {"dd_brake": None}),
                    ("jeda 20 hari setelah stop", {"cooldown_days": 20}),
                    ("modal Rp100 jt", {"initial_equity": 100_000_000})]:
        line("  " + lab, ev(pick, bt))
    P("SELESAI")


def grid(ev, line, q0):
    """Peta ambang 'flow & momentum sama-sama kuat': apakah 70/70 itu dataran (kokoh) atau puncak kebetulan?"""
    ths = [0, 50, 60, 65, 70, 75, 80, 85]
    line("model sekarang", q0)
    for fl, w in [("B", "w9 35/50/15/0"), ("A", "w0 30/25/20/10 (sekarang)"), ("B", "w2 40/40/20/0")]:
        P(f"== PETA AMBANG  skor inflow {fl}, bobot {w[:2]}  (baris = ambang flow, kolom = ambang momentum; isi = CAGR/DD 10 thn | UJI) ==")
        P("flow\\mom  " + "  ".join(f"{m:>17d}" for m in ths))
        cell = {}
        for tf in ths:
            row = []
            for tm in ths:
                q = ev({**BASE, "flow": fl, "w": w, "gate": f"t{tf}/{tm}"})
                cell[(tf, tm)] = q
                row.append(f"{q['cagr']*100:4.0f}/{q['mdd']*100:4.0f}|{q['h'][1][0]*100:3.0f}/{q['h'][1][1]*100:4.0f}")
            P(f"{tf:>8d}  " + "  ".join(row))
        top = sorted(cell.items(), key=lambda x: -min(x[1]["h"][0][2], x[1]["h"][1][2]))[:6]
        for (tf, tm), q in top:
            line(f"  paling konsisten t{tf}/{tm}", q)
    P("== jumlah posisi & risiko untuk beberapa ambang (skor inflow B, bobot w9) ==")
    for g in ("t65/65", "t70/70", "t75/75", "t70/60", "t60/70"):
        for lab, bt in [("5 posisi", {"max_positions": 5}), ("6 posisi", {"max_positions": 6}), ("7 posisi", {"max_positions": 7}),
                        ("8 posisi", {}), ("6 posisi + risiko 1,25%", {"max_positions": 6, "risk_per_trade": 0.0125}),
                        ("6 posisi, modal Rp100 jt", {"max_positions": 6, "initial_equity": 100_000_000})]:
            line(f"  {g} {lab}", ev({**BASE, "flow": "B", "w": "w9 35/50/15/0", "gate": g}, bt))
    P("SELESAI")


if __name__ == "__main__":
    main()
