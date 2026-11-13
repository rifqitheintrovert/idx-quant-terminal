"""Diagnosa drawdown backtest: episode terdalam, penyebab (saham/sektor), anatomi rugi, peran rezim,
dan uji "bagaimana kalau" (varian aturan). Hanya ANALISIS — tidak mengubah model/dashboard.

    python -m engine.diagnose --cache .cache/panels.pkl
"""
from __future__ import annotations

import argparse
import copy
import math
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, regime
from . import universe as uni_mod
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("DIAG|", *a, flush=True)


# ------------------------------------------------------------------ varian aturan (memakai mesin backtest yang sama dgn dashboard)
def variant(cfg, bt=None, sig=None):
    c = copy.deepcopy(cfg)
    c["backtest"].update(bt or {})
    c["signal"].update(sig or {})
    return c


def kpi(df):
    eq = df["eq"]
    yrs = len(eq) / 242
    r = eq.pct_change().dropna()
    yr = eq.groupby(eq.index.year).last().pct_change()
    yr.iloc[0] = eq.groupby(eq.index.year).last().iloc[0] / eq.iloc[0] - 1
    mid = eq.index[len(eq) // 2]
    halves = []
    for h in (eq[:mid], eq[mid:]):
        halves.append(((h.iloc[-1] / h.iloc[0]) ** (242 / len(h)) - 1, float((h / h.cummax() - 1).min())))
    return {"h": halves, "cagr": (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1, "mdd": float((eq / eq.cummax() - 1).min()),
            "vol": r.std() * math.sqrt(242), "sharpe": (r.mean() * 242 - 0.05) / (r.std() * math.sqrt(242)),
            "inv": df["inv"].mean(), "final": eq.iloc[-1], "yr": yr}


def episodes(eq, k=5):
    dd = eq / eq.cummax() - 1
    out, start, prev = [], None, eq.index[0]
    for d, x in dd.items():
        if x < 0 and start is None:
            start = prev
        if x == 0 and start is not None:
            seg = dd[start:d]
            out.append((start, seg.idxmin(), d, float(seg.min())))
            start = None
        prev = d
    if start is not None:
        seg = dd[start:]
        out.append((start, seg.idxmin(), None, float(seg.min())))
    return sorted(out, key=lambda e: e[3])[:k]


def pc(x, d=1):
    return f"{x * 100:+.{d}f}%"


# ------------------------------------------------------------------ main
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
    sectors = {t: universe[t]["sector"] for t in tickers}
    panels = data.build_panels(frames, tickers)
    macro = {}
    if not a.no_macro:
        try:
            got = data.fetch_yahoo([cfg["macro"]["IHSG"], cfg["macro"]["USDIDR"]], hist_start(cfg, now))
            macro = {"IHSG": got.get(cfg["macro"]["IHSG"]), "USDIDR": got.get(cfg["macro"]["USDIDR"])}
        except Exception as e:  # noqa: BLE001
            P("makro gagal:", e)

    def build(c):
        F = features.compute(panels, c)
        ih = macro["IHSG"]["Close"] if macro.get("IHSG") is not None else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
        rg = regime.compute(ih, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)
        cp = features.composite(F, c["weights"], None)
        return F, rg, cp, features.conditions(F, cp, c)

    F, reg, comp, _ = build(cfg)

    def evaluate(c):
        cond = features.conditions(F, comp, c, reg)
        out, det = backtest.run(F, comp, cond, reg, c, detail=True)
        return out, det["df"], det["trades"], det

    ref, df, tr, det = evaluate(cfg)
    attrib, tick = det["attrib"], det["tick"]
    k = kpi(df)
    P(f"DATA {len(tickers)} saham | {df.index[0].date()}..{df.index[-1].date()} | aturan aktif di config: "
      + ", ".join(f"{a}={cfg['backtest'].get(a)}" for a in ("sizing", "risk_per_trade", "max_weight", "realistic_fills", "weight_cap",
                                                            "tighten_after_r", "partial_tp_r", "cooldown_days", "dd_brake"))
      + f", market_filter={cfg['signal'].get('market_filter')}, max_atr_pct={cfg['signal'].get('max_atr_pct')}, stop_mode={cfg['signal'].get('stop_mode')}")
    P(f"konsentrasi: posisi terbesar rata2 {pc(df['wmax'].mean()).replace('+','')} ekuitas, maks {pc(df['wmax'].max()).replace('+','')} "
      f"| hari dgn satu posisi >25% ekuitas: {100*(df['wmax']>0.25).mean():.0f}%")
    P(f"AKTIF CAGR {pc(k['cagr'])} MaxDD {pc(k['mdd'])} vol {pc(k['vol'])} Sharpe {k['sharpe']:.2f} | rata2 terinvestasi "
      f"{k['inv']*100:.0f}% | rata2 posisi {df['npos'].mean():.1f} | trade {len(tr)} | akhir Rp{k['final']/1e6:,.1f} jt")
    tr = tr.assign(sec=tr.t.map(sectors))

    # ---------- 1. episode drawdown ----------
    att = pd.DataFrame(attrib, index=df.index).fillna(0.0)
    att.columns = [tick[j] for j in att.columns]
    P("== 1. EPISODE DRAWDOWN TERDALAM ==")
    for n, (p0, tr0, rec, depth) in enumerate(episodes(df["eq"]), 1):
        w = df.loc[p0:tr0]
        ih = w["ihsg"].iloc[-1] / w["ihsg"].iloc[0] - 1
        mix = w["reg"].value_counts(normalize=True)
        P(f"#{n} {p0.date()} -> {tr0.date()} ({len(w)} hari bursa) kedalaman {pc(depth)} | IHSG {pc(ih)} | pulih "
          f"{rec.date() if rec is not None else 'BELUM'} | terinvestasi rata2 {w['inv'].mean()*100:.0f}% (posisi {w['npos'].mean():.1f}) | "
          f"rezim ON {mix.get('RISK-ON',0)*100:.0f}% NEUTRAL {mix.get('NEUTRAL',0)*100:.0f}% OFF {mix.get('RISK-OFF',0)*100:.0f}%")
        P(f"   di puncak ({p0.date()}): laba belum direalisasi {pc(df['unreal'][p0])} ekuitas | posisi terbesar {pc(df['wmax'][p0]).replace('+','')} ekuitas | "
          f"{int(df['npos'][p0])} posisi")
        if n <= 3:
            a_ = att.loc[p0:tr0].iloc[1:].sum() / df["eq"][p0]
            a_ = a_[a_ != 0].sort_values()
            P(f"   penyumbang rugi terbesar (% ekuitas puncak): " + ", ".join(f"{t} {pc(v)}" for t, v in a_.head(8).items()))
            P(f"   penyumbang untung: " + (", ".join(f"{t} {pc(v)}" for t, v in a_.tail(3)[::-1].items() if v > 0) or "-")
              + f" | jumlah saham terlibat {len(a_)} | rugi dari {int((a_<0).sum())} saham, untung dari {int((a_>0).sum())}")
            bysec = a_.groupby(lambda t: sectors.get(t, '?')).sum().sort_values()
            P("   per sektor: " + ", ".join(f"{s_} {pc(v)}" for s_, v in bysec.head(5).items()))
            x = tr[(tr.d1 > p0) & (tr.d1 <= tr0)] if len(tr) else tr
            if len(x):
                P(f"   trade ditutup di periode ini: {len(x)} | win {100*(x.ret>0).mean():.0f}% | rata2 {pc(x.ret.mean())} | "
                  f"terburuk {pc(x.ret.min())} | keluar via: " + ", ".join(f"{r} {c_}" for r, c_ in x.why.value_counts().items()))
            # penurunan lewat gap (open vs close kemarin) vs intraday
            m = df["eq"].loc[p0:tr0]
            worst = m.pct_change().nsmallest(3)
            P("   3 hari terburuk: " + ", ".join(f"{d.date()} {pc(v)}" for d, v in worst.items()))

    # ---------- 2. anatomi rugi ----------
    P("== 2. ANATOMI TRADE ==")
    los, win = tr[tr.ret <= 0], tr[tr.ret > 0]
    P(f"semua trade {len(tr)} | win {100*len(win)/len(tr):.0f}% | rata2 untung {pc(win.ret.mean())} | rata2 rugi {pc(los.ret.mean())} | "
      f"median rugi {pc(los.ret.median())} | rugi terburuk {pc(los.ret.min())}")
    P(f"saat entry: rata2 ATR {pc(tr.atrp.mean()).replace('+','')}/hari | jarak stop awal rata2 {pc(tr.stopdist.mean()).replace('+','')} "
      f"(median {pc(tr.stopdist.median()).replace('+','')}, p90 {pc(tr.stopdist.quantile(.9)).replace('+','')}) | bobot rata2 {pc(tr.w.mean()).replace('+','')}")
    risk = tr.w * tr.stopdist
    real = (los.pnl / los.eq0)
    P(f"risiko per trade (bobot x jarak stop): rata2 {pc(risk.mean(),2).replace('+','')} ekuitas, p90 {pc(risk.quantile(.9),2).replace('+','')}, "
      f"maks {pc(risk.max(),2).replace('+','')} | rugi nyata per trade rugi: rata2 {pc(real.mean(),2)}, terburuk {pc(real.min(),2)}")
    over = los[los.ret < -(los.stopdist + 0.02)]
    P(f"rugi MELEBIHI rencana stop (>2 poin lebih dalam): {len(over)} dari {len(los)} trade rugi ({100*len(over)/max(1,len(los)):.0f}%) | "
      f"rugi < -10%: {int((tr.ret<-0.10).sum())}, < -15%: {int((tr.ret<-0.15).sum())}, < -20%: {int((tr.ret<-0.20).sum())}")
    st = tr[tr.why.str.startswith("stop")]
    clus = st.groupby("d1").size()
    P(f"keluar via stop {len(st)} ({100*len(st)/len(tr):.0f}%) rata2 {pc(st.ret.mean())} | via sinyal exit {int((tr.why=='sinyal exit').sum())} "
      f"rata2 {pc(tr[tr.why=='sinyal exit'].ret.mean())} | hari dgn >=3 posisi keluar bersamaan: {int((clus>=3).sum())}")
    top = tr.assign(c=tr.pnl / tr.eq0).sort_values("c")
    P("10 trade paling merugikan (% ekuitas saat itu): " + ", ".join(f"{r.t} {r.d0.date()} {pc(r.ret)} ({pc(r.c,2)})" for r in top.head(10).itertuples()))
    P("10 trade paling menguntungkan: " + ", ".join(f"{r.t} {r.d0.date()} {pc(r.ret)} ({pc(r.c,2)})" for r in top.tail(10)[::-1].itertuples()))
    P(f"untung terpusat: 10 trade terbaik = {100*win.pnl.nlargest(10).sum()/tr.pnl.sum():.0f}% dari total laba bersih; "
      f"jumlah saham berbeda yang pernah dibeli {tr.t.nunique()}")
    held = tr.groupby("sec").size().sort_values(ascending=False)
    P("trade per sektor: " + ", ".join(f"{s_} {n_}" for s_, n_ in held.head(6).items()))

    # ---------- 3. rezim ----------
    P("== 3. PERAN FILTER REZIM ==")
    r = np.log(df["eq"]).diff().fillna(0)
    dd = df["eq"] / df["eq"].cummax() - 1
    for lab in ["RISK-ON", "NEUTRAL", "RISK-OFF"]:
        m = df["reg"] == lab
        if m.any():
            P(f"{lab}: {100*m.mean():.0f}% hari | batas eksposur {cfg['regime_exposure'][lab]*100:.0f}% | terinvestasi nyata rata2 {df.loc[m,'inv'].mean()*100:.0f}% "
              f"(posisi {df.loc[m,'npos'].mean():.1f}) | kontribusi return strategi {pc(math.exp(r[m].sum())-1)} | IHSG {pc(math.exp(np.log(df['ihsg']).diff()[m].sum())-1)}")
    # berapa lama dari rezim berubah OFF sampai eksposur benar-benar turun
    off = (df["reg"] == "RISK-OFF")
    starts = df.index[off & ~off.shift(1, fill_value=False)]
    lag = []
    for d0 in starts:
        w = df.loc[d0:].iloc[:15]
        lag.append((w["inv"].iloc[0], w["inv"].iloc[min(5, len(w)-1)], w["inv"].iloc[min(10, len(w)-1)]))
    if lag:
        L_ = np.array(lag)
        P(f"saat rezim baru masuk RISK-OFF ({len(lag)} kali): terinvestasi rata2 {L_[:,0].mean()*100:.0f}% di hari-0 -> {L_[:,1].mean()*100:.0f}% (hari-5) -> "
          f"{L_[:,2].mean()*100:.0f}% (hari-10). Aturan sekarang hanya MELARANG beli baru, tidak memaksa jual.")

    # ---------- 4. uji varian ----------
    P("== 4. UJI VARIAN ATURAN (H1 = paruh pertama, H2 = paruh kedua periode; format CAGR/MaxDD) ==")

    def line(name, d, t):
        q = kpi(d)
        y = q["yr"]
        top = 100 * t.pnl.nlargest(10).sum() / t.pnl.sum() if len(t) and t.pnl.sum() > 0 else float("nan")
        P(f"{name:46s} CAGR {pc(q['cagr'])} | MaxDD {pc(q['mdd'])} | Sharpe {q['sharpe']:.2f} | H1 {pc(q['h'][0][0],0)}/{pc(q['h'][0][1],0)} "
          f"H2 {pc(q['h'][1][0],0)}/{pc(q['h'][1][1],0)} | thn terburuk {pc(y.min(),0)} | 2026 {pc(y.get(2026, float('nan')),0)} | "
          f"invest {q['inv']*100:.0f}% | trade {len(t)} | top10 {top:.0f}% laba | akhir Rp{q['final']/1e6:,.1f} jt")
        return q

    OLD = dict(sizing="equal", realistic_fills=False, weight_cap=None, tighten_after_r=None, partial_tp_r=None,
               cooldown_days=0, dd_brake=None)
    OLDS = dict(market_filter=None, max_atr_pct=None, stop_mode="close")
    R = {**OLD, "realistic_fills": True}
    B = {**R, "sizing": "risk", "risk_per_trade": 0.01, "max_weight": 0.20}
    tests = [
        ("00 aturan lama (bobot sama, order selalu terisi)", OLD, OLDS),
        ("R  + eksekusi realistis", R, OLDS),
        ("B  R + sizing risiko 1% (maks 20%/saham)", B, OLDS),
        ("B' R + sizing risiko 0,75%", {**B, "risk_per_trade": 0.0075}, OLDS),
        ("B\" R + sizing risiko 1,5%", {**B, "risk_per_trade": 0.015}, OLDS),
        ("C  B + pangkas posisi >25% ke 20%", {**B, "weight_cap": 0.20}, OLDS),
        ("C' B + pangkas posisi >19% ke 15%", {**B, "weight_cap": 0.15}, OLDS),
        ("D  B + rapatkan trailing 2xATR setelah +2R", {**B, "tighten_after_r": 2.0}, OLDS),
        ("D' B + rapatkan trailing 2xATR setelah +4R", {**B, "tighten_after_r": 4.0}, OLDS),
        ("E  B + jual 50% saat +3R", {**B, "partial_tp_r": 3.0}, OLDS),
        ("F  B + stop intraday", B, {**OLDS, "stop_mode": "intraday"}),
        ("G  B + beli hanya saat IHSG > MA50", B, {**OLDS, "market_filter": "ma50"}),
        ("G' B + beli hanya saat IHSG > MA200", B, {**OLDS, "market_filter": "ma200"}),
        ("H  B + tolak saham ATR > 7%/hari", B, {**OLDS, "max_atr_pct": 0.07}),
        ("H' B + tolak saham ATR > 5%/hari", B, {**OLDS, "max_atr_pct": 0.05}),
        ("I  B + 12 posisi", {**B, "max_positions": 12}, OLDS),
        ("J  B + jeda 20 hari setelah kena stop", {**B, "cooldown_days": 20}, OLDS),
        ("K  B + rem: slot separuh saat DD > 15%", {**B, "dd_brake": 0.15}, OLDS),
        ("X1 B + C + D'", {**B, "weight_cap": 0.20, "tighten_after_r": 4.0}, OLDS),
        ("X2 B + C + G", {**B, "weight_cap": 0.20}, {**OLDS, "market_filter": "ma50"}),
        ("X3 B + C + G + H", {**B, "weight_cap": 0.20}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("X4 B + C + G + H + J", {**B, "weight_cap": 0.20, "cooldown_days": 20}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("X5 B + C + G + H + K", {**B, "weight_cap": 0.20, "dd_brake": 0.15}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("X6 B + C + G + H + I(12 posisi)", {**B, "weight_cap": 0.20, "max_positions": 12}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("X7 B + C + G + H + D'", {**B, "weight_cap": 0.20, "tighten_after_r": 4.0}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("X8 B' + C + G + H + I", {**B, "risk_per_trade": 0.0075, "weight_cap": 0.20, "max_positions": 12}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("X9 B + C' + G' + H", {**B, "weight_cap": 0.15}, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
        # putaran 2: gabungan dari yang terbukti menolong di KEDUA paruh (G' filter MA200, H batas ATR, K rem drawdown)
        ("Y1 B + G' + K", {**B, "dd_brake": 0.15}, {**OLDS, "market_filter": "ma200"}),
        ("Y2 B + G' + H + K", {**B, "dd_brake": 0.15}, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
        ("Y3 B + G' + H + K + C'", {**B, "dd_brake": 0.15, "weight_cap": 0.15}, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
        ("Y4 B + G' + H + K(10%)", {**B, "dd_brake": 0.10}, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
        ("Y5 B + G' + H + K(20%)", {**B, "dd_brake": 0.20}, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
        ("Y6 B + G + H + K", {**B, "dd_brake": 0.15}, {**OLDS, "market_filter": "ma50", "max_atr_pct": 0.07}),
        ("Y7 B + G' + H", B, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
        ("Y8 B + H + K", {**B, "dd_brake": 0.15}, {**OLDS, "max_atr_pct": 0.07}),
        ("Y9 B + G' + H + K + J", {**B, "dd_brake": 0.15, "cooldown_days": 20}, {**OLDS, "market_filter": "ma200", "max_atr_pct": 0.07}),
    ]
    extra = os.environ.get("DIAG_ONLY")
    for name, b_, s_ in tests:
        if extra and not any(name.startswith(x) for x in extra.split(",")):
            continue
        _, d, t, _ = evaluate(variant(cfg, b_, s_))
        line(name, d, t)
    P("SELESAI")


if __name__ == "__main__":
    main()
