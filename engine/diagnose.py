"""Diagnosa drawdown backtest: episode terdalam, penyebab (saham/sektor), anatomi rugi, peran rezim,
dan uji "bagaimana kalau" (varian aturan). Hanya ANALISIS — tidak mengubah model/dashboard.

    python -m engine.diagnose --cache .cache/panels.pkl
"""
from __future__ import annotations

import argparse
import copy
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, regime
from . import universe as uni_mod
from .idx_rules import WIB, ara_pct, round_tick
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("DIAG|", *a, flush=True)


# ------------------------------------------------------------------ simulasi fleksibel (baseline = backtest.run)
def sim(F, comp, cond, reg, cfg, sectors, *, sizing="equal", risk_pct=0.01, max_w=0.20, regime_cut=False,
        dd_brake=None, sector_cap=None, realistic=False, cols=None, maxpos=None):
    bt, s = cfg["backtest"], cfg["signal"]
    fee_b, fee_s, lot = cfg["idx_rules"]["fee_buy"], cfg["idx_rules"]["fee_sell"], cfg["idx_rules"]["lot_size"]
    maxpos = maxpos or bt["max_positions"]
    expo = cfg["regime_exposure"]
    equity0 = float(bt.get("initial_equity", 1e8))
    c = F["c"]
    dates = c.index
    ready = (F["mom_6_1"].notna() & F["ma200"].notna()).sum(axis=1) >= max(5, min(40, int(0.5 * c.shape[1])))
    start_i = int(np.argmax(ready.values)) if ready.any() else 200
    start_i = max(start_i, int(dates.searchsorted(dates[-1] - pd.Timedelta(days=int(float(bt["years"]) * 365.25)))))
    tick = list(c.columns)
    C, O, H, L, V = c.values, F["o"].values, F["h"].values, F["l"].values, F["v"].values
    ENT, STR, EXT = cond["entry"].values.copy(), cond["strong"].values, cond["exit"].values
    if cols is not None:
        ENT[:, ~np.isin(np.array(tick), list(cols))] = False
    COMP, ATR, CH, REG = comp.values, F["atr14"].values, F["chandelier"].values, reg["label"].values
    sec = [sectors.get(t, "?") for t in tick]

    cash, pos, peak, brake = equity0, {}, equity0, False
    pending_exit: dict[int, str] = {}
    pending_entry: list[int] = []
    rows, trades, attrib = [], [], []

    def locked_down(i, j):   # terkunci ARB seharian -> tidak bisa jual
        return H[i, j] == L[i, j] and C[i, j] <= C[i - 1, j] * 0.935

    for i in range(start_i, len(dates)):
        day = defaultdict(float)
        for j, why in list(pending_exit.items()):
            if j not in pos:
                pending_exit.pop(j)
                continue
            if realistic and (V[i, j] <= 0 or locked_down(i, j)):
                continue                                   # tidak ada pembeli -> coba lagi besok
            p = pos.pop(j)
            pending_exit.pop(j)
            px = O[i, j]
            got = p["sh"] * px * (1 - fee_s)
            cash += got
            day[j] += got - p["mark"]
            trades.append({"t": tick[j], "sec": sec[j], "d0": p["d0"], "d1": dates[i], "entry": p["entry"], "exit": px,
                           "ret": got / p["cost"] - 1, "pnl": got - p["cost"], "w": p["w"], "stopdist": p["stopdist"],
                           "atrp": p["atrp"], "why": why, "days": i - p["i0"], "eq0": p["eq0"]})
        eq_open = cash + sum(p["sh"] * O[i, j] for j, p in pos.items())
        for j in pending_entry:
            if j in pos or len(pos) >= maxpos:
                continue
            px = O[i, j]
            stop = round_tick(C[i - 1, j] - s["atr_stop_mult"] * ATR[i - 1, j], "down")
            if not np.isfinite(px) or px <= stop:
                continue
            if realistic and (V[i, j] <= 0 or px >= C[i - 1, j] * (1 + ara_pct(C[i - 1, j]) - 0.01)):
                continue                                   # tidak diperdagangkan / terkunci ARA -> tidak kebagian
            if sizing == "risk":
                sh = min(eq_open * risk_pct / (px - stop), eq_open * max_w / px, cash / (px * (1 + fee_b)))
            else:
                sh = min(eq_open / maxpos, cash) / (px * (1 + fee_b))
            sh = math.floor(sh / lot) * lot
            if sh <= 0:
                continue
            cost = sh * px * (1 + fee_b)
            cash -= cost
            pos[j] = {"sh": sh, "entry": px, "d0": dates[i], "stop": stop, "i0": i, "cost": cost, "mark": cost,
                      "w": cost / eq_open, "stopdist": (px - stop) / px, "atrp": ATR[i - 1, j] / C[i - 1, j], "eq0": eq_open}
        pending_entry = []

        eq, unreal, vmax = cash, 0.0, 0.0
        for j, p in pos.items():
            val = p["sh"] * C[i, j]
            day[j] += val - p["mark"]
            p["mark"] = val
            eq += val
            unreal += val - p["cost"]
            vmax = max(vmax, val)
            if np.isfinite(CH[i, j]):
                p["stop"] = max(p["stop"], round_tick(CH[i, j], "down"))
        rows.append((eq, cash, len(pos), unreal / eq, vmax / eq))
        attrib.append(dict(day))
        peak = max(peak, eq)
        brake = bool(dd_brake) and (eq / peak - 1) < -dd_brake      # sedang drawdown dalam -> eksposur baru dipangkas separuh

        for j, p in pos.items():
            if j in pending_exit:
                continue
            if C[i, j] <= p["stop"]:
                pending_exit[j] = "stop"
            elif EXT[i, j]:
                pending_exit[j] = "sinyal exit"
        target = int(round(maxpos * expo.get(REG[i], 0.7)))
        if brake:
            target = max(1, target // 2)
        hold = [j for j in pos if j not in pending_exit]
        if regime_cut and len(hold) > target:               # rezim memburuk -> lepas posisi terlemah
            for j in sorted(hold, key=lambda j: COMP[i, j] if np.isfinite(COMP[i, j]) else -1)[:len(hold) - target]:
                pending_exit[j] = "rezim"
            hold = [j for j in pos if j not in pending_exit]
        slots = target - len(hold)
        if slots > 0:
            cand = [j for j in range(len(tick)) if ENT[i, j] and j not in pos]
            cand.sort(key=lambda j: (not STR[i, j], -COMP[i, j]))
            if sector_cap:
                cnt = defaultdict(int)
                for j in hold:
                    cnt[sec[j]] += 1
                pick = []
                for j in cand:
                    if cnt[sec[j]] < sector_cap:
                        pick.append(j)
                        cnt[sec[j]] += 1
                    if len(pick) >= slots:
                        break
                pending_entry = pick
            else:
                pending_entry = cand[:slots]

    idx = dates[start_i:]
    df = pd.DataFrame(rows, index=idx, columns=["eq", "cash", "npos", "unreal", "wmax"])
    df["inv"] = 1 - df["cash"] / df["eq"]
    df["reg"] = REG[start_i:]
    df["ihsg"] = reg["ihsg"].iloc[start_i:].ffill().bfill().values
    return df, pd.DataFrame(trades), attrib, tick, sec


def kpi(df):
    eq = df["eq"]
    yrs = len(eq) / 242
    r = eq.pct_change().dropna()
    yr = eq.groupby(eq.index.year).last().pct_change()
    yr.iloc[0] = eq.groupby(eq.index.year).last().iloc[0] / eq.iloc[0] - 1
    return {"cagr": (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1, "mdd": float((eq / eq.cummax() - 1).min()),
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

    F, reg, comp, cond = build(cfg)
    ref = backtest.run(F, comp, cond, reg, cfg)
    df, tr, attrib, tick, sec = sim(F, comp, cond, reg, cfg, sectors)
    k = kpi(df)
    P(f"DATA {len(tickers)} saham | {df.index[0].date()}..{df.index[-1].date()} | cek kesesuaian dgn dashboard: "
      f"final {k['final']:,.0f} vs {ref['final_equity']:,.0f}")
    P(f"konsentrasi: posisi terbesar rata2 {pc(df['wmax'].mean()).replace('+','')} ekuitas, maks {pc(df['wmax'].max()).replace('+','')} "
      f"(target awal {100/cfg['backtest']['max_positions']:.1f}%) | hari dgn satu posisi >25% ekuitas: {100*(df['wmax']>0.25).mean():.0f}%")
    P(f"BASELINE CAGR {pc(k['cagr'])} MaxDD {pc(k['mdd'])} vol {pc(k['vol'])} Sharpe {k['sharpe']:.2f} | rata2 terinvestasi "
      f"{k['inv']*100:.0f}% | rata2 posisi {df['npos'].mean():.1f} | trade {len(tr)}")

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
    st = tr[tr.why == "stop"]
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

    # ---------- 4. bagaimana kalau ----------
    P("== 4. UJI 'BAGAIMANA KALAU' (hanya diagnosa, bukan rekomendasi final) ==")
    core = set(cfg["universe"])

    def line(name, d, t):
        q = kpi(d)
        y = q["yr"]
        g = lambda yy: pc(y.get(yy, float('nan')), 0) if yy in y.index else "n/a"   # noqa: E731
        P(f"{name:44s} CAGR {pc(q['cagr'])} | MaxDD {pc(q['mdd'])} | Sharpe {q['sharpe']:.2f} | invest {q['inv']*100:.0f}% | trade {len(t)} | "
          f"2021 {g(2021)} 2025 {g(2025)} 2026 {g(2026)} | akhir Rp{q['final']/1e6:,.1f} jt")

    line("0 baseline (aturan sekarang)", df, tr)
    V = [("1 eksekusi realistis (ARA/ARB terkunci)", dict(realistic=True)),
         ("2 sizing berbasis risiko 1%/posisi", dict(sizing="risk", risk_pct=0.01)),
         ("3 sizing berbasis risiko 2%/posisi", dict(sizing="risk", risk_pct=0.02)),
         ("4 paksa kurangi posisi saat rezim memburuk", dict(regime_cut=True)),
         ("5 rem portofolio: slot dipangkas 50% saat DD>15%", dict(dd_brake=0.15, regime_cut=True)),
         ("6 maks 2 posisi per sektor", dict(sector_cap=2)),
         ("7 hanya LQ45", dict(cols=core)),
         ("8 gabungan 1+2+4+6", dict(realistic=True, sizing="risk", risk_pct=0.01, regime_cut=True, sector_cap=2)),
         ("9 gabungan 1+3+4+6", dict(realistic=True, sizing="risk", risk_pct=0.02, regime_cut=True, sector_cap=2))]
    for name, kw in V:
        d, t, *_ = sim(F, comp, cond, reg, cfg, sectors, **kw)
        line(name, d, t)
    for bn in (25, 50):
        c2 = copy.deepcopy(cfg)
        c2["filters"]["min_avg_value_bn"] = bn
        F2, reg2, comp2, cond2 = build(c2)
        d, t, *_ = sim(F2, comp2, cond2, reg2, c2, sectors)
        line(f"10 likuiditas min Rp{bn} M/hari", d, t)
        d, t, *_ = sim(F2, comp2, cond2, reg2, c2, sectors, realistic=True, sizing="risk", risk_pct=0.02, regime_cut=True, sector_cap=2)
        line(f"11 likuiditas Rp{bn} M + gabungan 1+3+4+6", d, t)
    c3 = copy.deepcopy(cfg)
    c3["backtest"]["initial_equity"] = 100_000_000
    d, t, *_ = sim(F, comp, cond, reg, c3, sectors)
    line("12 baseline dgn modal Rp100 jt", d, t)
    P("SELESAI")


if __name__ == "__main__":
    main()
