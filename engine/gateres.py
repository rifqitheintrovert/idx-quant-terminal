"""Riset: solusi kelemahan MA (gerbang pasar) dan Parabolic SAR sebagai trailing stop. Hanya ANALISIS.

    python -m engine.gateres --cache .cache/panels.pkl

Model dasar = model dashboard sekarang (momentum + akumulasi inflow, aturan risiko yang sama).
Yang diganti hanya:
  GERBANG  kapan beli baru boleh dibuka (sekarang: IHSG > MA200)
  EXIT     trailing stop (sekarang: chandelier = high 22 hari − 3×ATR)
Pilihan dinilai di paruh pertama (latih) dan paruh kedua (uji) secara terpisah; yang dipakai hanya yang
lebih baik dari model sekarang di KEDUA paruh.
"""
from __future__ import annotations

import argparse
import copy
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, regime
from . import universe as uni_mod
from .flowmom import BASE, build, extras, kpi, pc
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("GR|", *a, flush=True)


# ------------------------------------------------------------------ Parabolic SAR (long)
def psar(H, L, C, af0=0.02, step=0.02, afmax=0.2):
    """Trailing level per saham. Saat tren naik = SAR di bawah harga; hari tren berbalik (close < SAR) = SAR itu
    (sehingga close <= stop -> keluar); selama tren turun = NaN (stop tidak dinaikkan)."""
    h, l, c = H.values, L.values, C.values
    n, m = c.shape
    out = np.full((n, m), np.nan)
    up = np.zeros(m, bool)
    sar = np.full(m, np.nan)
    ep = np.full(m, np.nan)
    af = np.full(m, af0)
    started = np.zeros(m, bool)
    for i in range(1, n):
        ok = np.isfinite(c[i]) & np.isfinite(h[i]) & np.isfinite(l[i]) & np.isfinite(l[i - 1]) & np.isfinite(h[i - 1])
        new = ok & ~started
        # mulai sebagai tren naik dari low kemarin
        sar[new], ep[new], af[new], up[new], started[new] = l[i - 1][new], h[i][new], af0, True, True
        act = ok & started & ~new
        if not act.any():
            continue
        lo2 = np.fmin(l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
        hi2 = np.fmax(h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
        nxt = sar + af * (ep - sar)
        nxt = np.where(up, np.fmin(nxt, lo2), np.fmax(nxt, hi2))
        flip_dn = act & up & (c[i] < nxt)
        flip_up = act & ~up & (c[i] > nxt)
        stay_up = act & up & ~flip_dn
        stay_dn = act & ~up & ~flip_up
        out[i][stay_up] = nxt[stay_up]
        out[i][flip_dn] = nxt[flip_dn]                    # hari berbalik: close di bawah level ini -> keluar
        upd = stay_up & (h[i] > ep)
        ep[upd] = h[i][upd]
        af[upd] = np.minimum(af[upd] + step, afmax)
        updn = stay_dn & (l[i] < ep)
        ep[updn] = l[i][updn]
        af[updn] = np.minimum(af[updn] + step, afmax)
        sar[stay_up | stay_dn] = nxt[stay_up | stay_dn]
        # balik arah
        sar[flip_dn], ep[flip_dn], af[flip_dn], up[flip_dn] = ep[flip_dn], l[i][flip_dn], af0, False
        sar[flip_up], ep[flip_up], af[flip_up], up[flip_up] = ep[flip_up], h[i][flip_up], af0, True
    return pd.DataFrame(out, index=C.index, columns=C.columns)


# ------------------------------------------------------------------ gerbang pasar
def gates(reg, F, ih):
    ih = ih.reindex(F["c"].index).ffill()
    ma = {k: ih.rolling(k, min_periods=int(k * 0.8)).mean() for k in (50, 100, 150, 200)}
    ema200 = ih.ewm(span=200, min_periods=160, adjust=False).mean()
    liq = F["liquid"]
    breadth = ((F["c"] > F["ma50"]) & liq).sum(axis=1) / liq.sum(axis=1).replace(0, np.nan)
    G = {}
    G["g0 IHSG > MA200 (sekarang)"] = (ih > ma[200]).astype(float)
    G["g1 IHSG > MA150"] = (ih > ma[150]).astype(float)
    G["g2 IHSG > MA100"] = (ih > ma[100]).astype(float)
    G["g3 IHSG > EMA200"] = (ih > ema200).astype(float)
    # penyangga: buka di atas MA200 +2%, tutup di bawah MA200 −2%
    st, out = 0.0, []
    for x, m in zip(ih.values, ma[200].values):
        if np.isfinite(x) and np.isfinite(m):
            st = 1.0 if x > m * 1.02 else 0.0 if x < m * 0.98 else st
        out.append(st)
    G["g4 MA200 ± penyangga 2%"] = pd.Series(out, index=ih.index)
    # konfirmasi: status berubah hanya setelah 3 hari berturut-turut di sisi baru
    above = (ih > ma[200]).astype(int)
    st, cnt, out = 0, 0, []
    for a in above.values:
        cnt = cnt + 1 if a != st else 0
        if cnt >= 3:
            st, cnt = a, 0
        out.append(float(st))
    G["g5 MA200 + konfirmasi 3 hari"] = pd.Series(out, index=ih.index)
    # bertahap: penuh di atas MA200; separuh saat di atas MA50 yang sedang naik
    half = (ih > ma[50]) & (ma[50] > ma[50].shift(20))
    G["g6 bertahap: MA200 penuh, MA50 naik separuh"] = np.where(ih > ma[200], 1.0, np.where(half, 0.5, 0.0))
    G["g6 bertahap: MA200 penuh, MA50 naik separuh"] = pd.Series(G["g6 bertahap: MA200 penuh, MA50 naik separuh"], index=ih.index)
    # breadth: buka juga kalau mayoritas saham likuid sudah di atas MA50-nya sendiri
    G["g7 MA200 atau breadth ≥ 50%"] = ((ih > ma[200]) | (breadth >= 0.5)).astype(float)
    G["g8 MA200 atau breadth ≥ 60%"] = ((ih > ma[200]) | (breadth >= 0.6)).astype(float)
    G["g9 bertahap + breadth ≥ 50% separuh"] = pd.Series(np.where(ih > ma[200], 1.0, np.where(half | (breadth >= 0.5), 0.5, 0.0)), index=ih.index)
    G["gX tanpa gerbang (pembanding)"] = pd.Series(1.0, index=ih.index)
    return G, breadth, ma


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
    ih = macro["IHSG"]["Close"] if macro.get("IHSG") is not None else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    reg = regime.compute(ih, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)
    G, breadth, ma = gates(reg, F, ih)

    # entry TANPA gerbang pasar; gerbang dipasang di sini lewat pengali slot
    cfg_ng = copy.deepcopy(cfg)
    cfg_ng["signal"]["market_filter"] = None
    comp, cond0 = build(F, cfg_ng, reg, BASE)
    P("membuat Parabolic SAR …")
    EX = {"x0 chandelier 3×ATR (sekarang)": None,
          "x1 Parabolic SAR 0,02/0,20": psar(F["h"], F["l"], F["c"], 0.02, 0.02, 0.20),
          "x2 Parabolic SAR lambat 0,01/0,10": psar(F["h"], F["l"], F["c"], 0.01, 0.01, 0.10)}
    ch = F["chandelier"]
    EX["x3 chandelier ATAU SAR (yang lebih ketat)"] = pd.DataFrame(np.fmax(ch.values, EX["x1 Parabolic SAR 0,02/0,20"].values), index=ch.index, columns=ch.columns)
    EX["x4 chandelier ATAU SAR lambat"] = pd.DataFrame(np.fmax(ch.values, EX["x2 Parabolic SAR lambat 0,01/0,10"].values), index=ch.index, columns=ch.columns)

    memo = {}

    def ev(g, x, bt=None):
        key = (g, x, tuple(sorted((bt or {}).items())))
        if key not in memo:
            c2 = cfg if not bt else copy.deepcopy(cfg)
            if bt:
                c2["backtest"].update(bt)
            gm = G[g]
            cond = dict(cond0)
            cond["entry"] = cond0["entry"] & (gm.reindex(cond0["entry"].index).fillna(0) > 0).values[:, None]
            cond["strong"] = cond0["strong"] & cond["entry"]
            cond["slot_mult"] = gm
            cond["trail"] = EX[x]
            _, det = backtest.run(F, comp, cond, reg, c2, detail=True)
            memo[key] = kpi(det["df"], len(det["trades"]))
        return memo[key]

    def line(label, q):
        P(f"{label:46s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | "
          f"LATIH {pc(q['h'][0][0],0)}/{pc(q['h'][0][1],0)} UJI {pc(q['h'][1][0],0)}/{pc(q['h'][1][1],0)} | "
          f"thn terburuk {pc(q['yr'].min(),0)} | invest {q['inv']*100:.0f}% | {q['tpy']:.0f} trade/thn | akhir Rp{q['final']/1e6:,.1f} jt")

    g0, x0 = list(G)[0], list(EX)[0]
    q0 = ev(g0, x0)
    P(f"DATA {F['c'].shape[1]} saham | modal Rp{cfg['backtest']['initial_equity']/1e6:g} jt | {F['c'].index[0].date()} s/d {F['c'].index[-1].date()}")
    line("MODEL SEKARANG", q0)

    def better(q):
        return q["h"][0][2] > q0["h"][0][2] and q["h"][1][2] > q0["h"][1][2]

    P("== GERBANG PASAR (exit tetap chandelier) ==")
    t = F["c"].index[-1]
    for g in G:
        q = ev(g, x0)
        op = float(G[g].reindex([t]).iloc[0]) if t in G[g].index else float("nan")
        line(g + (" ✓" if better(q) else ""), q)
        P(f"   terbuka {float((G[g].iloc[-2520:] > 0).mean())*100:.0f}% waktu (10 thn) | status hari ini: "
          f"{'TERBUKA' if op >= 1 else 'SEPARUH' if op > 0 else 'TERTUTUP'}")
    P(f"kondisi hari ini: IHSG {float(ih.iloc[-1]):,.0f} | MA50 {float(ma[50].iloc[-1]):,.0f} (20 hari lalu {float(ma[50].iloc[-21]):,.0f}) | "
      f"MA100 {float(ma[100].iloc[-1]):,.0f} | MA200 {float(ma[200].iloc[-1]):,.0f} | breadth (saham likuid > MA50) {float(breadth.iloc[-1])*100:.0f}%")

    P("== EXIT / TRAILING STOP (gerbang tetap MA200) ==")
    for x in EX:
        q = ev(g0, x)
        line(x + (" ✓" if better(q) else ""), q)

    P("== GABUNGAN (gerbang × exit) — urut Calmar paruh terlemah ==")
    res = [((g, x), ev(g, x)) for g in G for x in EX if not g.startswith("gX")]
    res.sort(key=lambda r: -min(r[1]["h"][0][2], r[1]["h"][1][2]))
    for (g, x), q in res[:12]:
        line(f"{g[:2]} + {x[:2]}" + (" ✓" if better(q) else ""), q)
    nb = sum(1 for _, q in res if better(q))
    P(f"gabungan yang lebih baik dari model sekarang di KEDUA paruh: {nb}/{len(res)}")
    best = [r for r in res if better(r[1])]
    if best:
        (g, x), q = best[0]
        P(f"== KESTABILAN pilihan terbaik: {g} + {x} ==")
        line("pilihan", q)
        line("model sekarang", q0)
        P("per tahun pilihan : " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q["yr"].items()))
        P("per tahun sekarang: " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q0["yr"].items()))
        for lab, bt in [("modal Rp100 jt", {"initial_equity": 100_000_000}), ("risiko 0,75%", {"risk_per_trade": 0.0075}),
                        ("risiko 1,25%", {"risk_per_trade": 0.0125}), ("6 posisi", {"max_positions": 6}), ("10 posisi", {"max_positions": 10})]:
            line("  " + lab + " | pilihan", ev(g, x, bt))
            line("  " + lab + " | sekarang", ev(g0, x0, bt))
    P("SELESAI")


if __name__ == "__main__":
    main()
