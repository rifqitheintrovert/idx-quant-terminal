"""Cari portofolio dengan CAGR setinggi mungkin dan drawdown serendah mungkin. Hanya ANALISIS.

    python -m engine.optimize --cache .cache/panels.pkl

Caranya: bangun beberapa "sleeve" (strategi mandiri), lalu cari bobot gabungannya.
  CUR   strategi dashboard sekarang (tren + flow, harian)
  MIN   Minervini longgar (Trend Template + breakout volume, gerbang IHSG>MA200)
  MINI  MIN dengan stop intraday
  MR    mean reversion: saham uptrend yang jatuh sesaat (RSI-2 rendah), keluar saat memantul
  MOM   momentum bulanan 5 saham + saklar IHSG (rapuh, hanya pembanding)
  EMAS  emas dalam rupiah, beli & tahan
  (sisa bobot = kas, bunga 0%)
Anti-overfitting: bobot dipilih di PARUH PERTAMA (latih), dilaporkan hasilnya di PARUH KEDUA (uji).
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
from .idx_rules import WIB, ara_pct
from .minervini import mm_sim, setup
from .research import P, kpi, rebal_sim
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]
COST = 0.003          # biaya per rupiah yang dipindahkan saat rebalance tahunan


# ------------------------------------------------------------------ sleeve mean reversion
def mr_sim(F, cfg, start_i, sig, score, *, maxpos=8, hold_max=10, stop_pct=0.12, exit_ma="ma5"):
    fee_b, fee_s, lot = cfg["idx_rules"]["fee_buy"], cfg["idx_rules"]["fee_sell"], cfg["idx_rules"]["lot_size"]
    eq0 = float(cfg["backtest"].get("initial_equity", 1e7))
    dates = F["c"].index
    C, O, H, L, V = F["c"].values, F["o"].values, F["h"].values, F["l"].values, F["v"].values
    MA = F["c"].rolling(5).mean().values if exit_ma == "ma5" else F["ma20"].values
    cash, pos, exits, entries, eqs, n = eq0, {}, set(), [], [], 0
    wins = 0
    for i in range(start_i, len(dates)):
        for j in list(exits):
            if j in pos:
                if V[i, j] <= 0 or (H[i, j] == L[i, j] and C[i, j] <= C[i - 1, j] * 0.935):
                    continue
                p = pos.pop(j)
                got = p[0] * O[i, j] * (1 - fee_s)
                cash += got
                n += 1
                wins += got > p[2]
            exits.discard(j)
        if entries:
            eq_open = cash + sum(p[0] * O[i, j] for j, p in pos.items())
            for j in entries:
                px = O[i, j]
                if j in pos or len(pos) >= maxpos or not np.isfinite(px) or V[i, j] <= 0 \
                        or px >= C[i - 1, j] * (1 + ara_pct(C[i - 1, j]) - 0.01):
                    continue
                sh = math.floor(min(eq_open / maxpos, cash) / (px * (1 + fee_b)) / lot) * lot
                if sh > 0:
                    cost = sh * px * (1 + fee_b)
                    cash -= cost
                    pos[j] = (sh, px, cost, i)
            entries = []
        eqs.append(cash + sum(p[0] * C[i, j] for j, p in pos.items()))
        for j, p in pos.items():
            if C[i, j] > MA[i, j] or i - p[3] >= hold_max or C[i, j] <= p[1] * (1 - stop_pct):
                exits.add(j)
        slots = maxpos - (len(pos) - len(exits & set(pos)))
        if slots > 0:
            cand = [j for j in np.flatnonzero(sig[i]) if j not in pos]
            cand.sort(key=lambda j: score[i, j])
            entries = cand[:slots]
    return pd.Series(eqs, index=dates[start_i:]), n, wins


# ------------------------------------------------------------------ gabungan sleeve
def combine(R: np.ndarray, w: np.ndarray, seg: list[slice]) -> np.ndarray:
    """Kurva ekuitas portofolio (mulai 1.0) dari return harian sleeve R (hari x sleeve), bobot w, sisa kas.
    Rebalance tiap awal segmen (tahunan) dengan biaya COST atas nilai yang dipindah."""
    out = np.empty(R.shape[0])
    tot, val, cashw = 1.0, None, 1 - w.sum()
    for k, sl in enumerate(seg):
        if val is not None:
            tot -= np.abs(w * tot - val).sum() * COST
        g = np.cumprod(1 + R[sl], axis=0)
        port = (g * (w * tot)).sum(axis=1) + cashw * tot
        out[sl] = port
        val, tot = g[-1] * (w * tot), port[-1]
    return out


def stats(eq: np.ndarray, yrs: float):
    cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1
    peak = np.maximum.accumulate(eq)
    return cagr, float((eq / peak - 1).min())


def pc(x, d=1):
    return f"{x * 100:+.{d}f}%"


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
    F = features.compute(data.build_panels(frames, tickers), cfg)
    idx = F["c"].index
    macro = {}
    if not a.no_macro:
        try:
            got = data.fetch_yahoo([cfg["macro"][k] for k in ("IHSG", "USDIDR", "GOLD")], hist_start(cfg, now))
            macro = {k: got.get(cfg["macro"][k]) for k in ("IHSG", "USDIDR", "GOLD")}
        except Exception as e:  # noqa: BLE001
            P("makro gagal:", e)
    ihsg = (macro["IHSG"]["Close"].reindex(idx).ffill().bfill() if macro.get("IHSG") is not None
            else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000)
    if macro.get("GOLD") is not None and macro.get("USDIDR") is not None:
        gold = (macro["GOLD"]["Close"].reindex(idx).ffill() * macro["USDIDR"]["Close"].reindex(idx).ffill()).ffill().bfill()
    else:
        gold = pd.Series(np.exp(np.cumsum(0.0004 + 0.009 * np.random.default_rng(3).standard_normal(len(idx)))), index=idx)
    reg = regime.compute(ihsg, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)
    bt = cfg["backtest"]
    ready = (F["mom_6_1"].notna() & F["ma200"].notna()).sum(axis=1) >= max(5, min(40, int(0.5 * F["c"].shape[1])))
    start_i = max(int(np.argmax(ready.values)), int(idx.searchsorted(idx[-1] - pd.Timedelta(days=int(float(bt["years"]) * 365.25)))))
    dates = idx[start_i:]
    comp = features.composite(F, cfg["weights"], None)
    A, gate, template, signal = setup(F, ihsg)
    c = F["c"]
    rsi2 = ind.rsi(c, 2)

    def liq(bn):
        return (F["avg_val20"] >= bn * 1e9) & (c >= 50) & (c.notna().cumsum() >= 260)

    def build(eq0):
        """Semua sleeve dengan modal awal eq0 (kendala lot ikut berubah bila modal kecil)."""
        cf = copy.deepcopy(cfg)
        cf["backtest"]["initial_equity"] = eq0
        out = {}
        _, det = backtest.run(F, comp, features.conditions(F, comp, cf, reg), reg, cf, detail=True)
        out["CUR"] = det["df"]["eq"]
        tt10, rs10 = template(10)
        out["MIN"], _ = mm_sim(A, cf, start_i, signal(tt10, vcp=False), rs10.values, gate=gate)
        out["MINI"], _ = mm_sim(A, cf, start_i, signal(tt10, vcp=False), rs10.values, gate=gate, stop_mode="intraday")
        up = (c > F["ma200"])
        for nm, bn, g_, thr in (("MR10", 10, False, 10), ("MR25", 25, False, 10), ("MR25g", 25, True, 10), ("MR50", 50, False, 10),
                                ("MR25x", 25, False, 5)):
            sg = (liq(bn) & up & (rsi2 < thr)).values
            if g_:
                sg = sg & gate[:, None]
            out[nm], n, w = mr_sim(F, cf, start_i, sg, rsi2.values)
            if eq0 == base_eq:
                mrinfo[nm] = f"{n} trade, win {100*w/max(1,n):.0f}%"
        mom = F["mom_12_1"].values
        el = (liq(10) & up).values
        out["MOM"], _ = rebal_sim(F, mom, el, cf, start_i, n=5, switch=gate)
        out["EMAS"] = gold.iloc[start_i:] / gold.iloc[start_i] * eq0
        return out

    base_eq = float(bt.get("initial_equity", 1e7))
    mrinfo: dict = {}
    S = build(base_eq)
    yrs = (dates[-1] - dates[0]).days / 365.25
    P(f"DATA {len(tickers)} saham | {dates[0].date()}..{dates[-1].date()} | modal Rp{base_eq:,.0f}")
    P("== SLEEVE (berdiri sendiri) ==")
    for k, e in S.items():
        q = kpi(e)
        P(f"{k:6s} CAGR {pc(q['cagr'])} | MaxDD {pc(q['mdd'])} | Sharpe {q['sharpe']:+.2f} | Calmar {q['calmar']:.2f} | H1 {pc(q['h'][0][1],0)}/{pc(q['h'][0][2],0)} "
          f"H2 {pc(q['h'][1][1],0)}/{pc(q['h'][1][2],0)} | 2020 {pc(q['yr'].get(2020, np.nan),0)} 2021 {pc(q['yr'].get(2021, np.nan),0)} "
          f"2025 {pc(q['yr'].get(2025, np.nan),0)} 2026 {pc(q['yr'].get(2026, np.nan),0)} {mrinfo.get(k, '')}")
    rets = pd.DataFrame({k: e.pct_change().fillna(0) for k, e in S.items()})
    mc = rets.resample("ME").apply(lambda x: (1 + x).prod() - 1).corr()
    P("korelasi return bulanan: " + " | ".join(f"{a_}-{b_} {mc.loc[a_, b_]:+.2f}" for a_, b_ in itertools.combinations(["CUR", "MIN", "MR25", "EMAS"], 2)))

    # ---------- pencarian bobot ----------
    use = ["CUR", "MIN", "MR25", "EMAS"]            # sleeve inti (MR25 dipilih a priori: saham likuid, tanpa gerbang)
    R = rets[use].values
    years = dates.year.values
    seg = [slice(int(np.flatnonzero(years == y)[0]), int(np.flatnonzero(years == y)[-1]) + 1) for y in np.unique(years)]
    mid = len(dates) // 2
    seg1 = [s for s in seg if s.stop <= mid] or [slice(0, mid)]
    cut = seg1[-1].stop
    seg2 = [slice(s.start - cut, s.stop - cut) for s in seg if s.start >= cut]
    y1, y2 = (dates[cut - 1] - dates[0]).days / 365.25, (dates[-1] - dates[cut]).days / 365.25
    grid = [np.array(w) / 10 for w in itertools.product(range(0, 11), repeat=len(use)) if sum(w) <= 10 and sum(w) >= 5]
    rows = []
    for w in grid:
        e = combine(R, w, seg)
        cg, md = stats(e, yrs)
        c1, m1 = stats(combine(R[:cut], w, seg1), y1)
        c2, m2 = stats(combine(R[cut:], w, seg2), y2)
        rows.append((w, cg, md, c1, m1, c2, m2))
    P(f"== PENCARIAN BOBOT: {len(rows)} kombinasi dari {use} (langkah 10%, kas 0–50%) | latih {dates[0].date()}..{dates[cut-1].date()} | uji {dates[cut].date()}..{dates[-1].date()} ==")

    def fmt(r):
        w = r[0]
        ws = " ".join(f"{u}{int(round(x*100))}" for u, x in zip(use, w) if x > 0) + (f" KAS{int(round((1-w.sum())*100))}" if w.sum() < 0.999 else "")
        return (f"{ws:34s} | 10th: CAGR {pc(r[1])} DD {pc(r[2])} Calmar {r[1]/abs(r[2]):.2f} | latih: {pc(r[3])}/{pc(r[4])} | "
                f"uji: {pc(r[5])}/{pc(r[6])} | akhir Rp{base_eq*(1+r[1])**yrs/1e6:,.1f} jt")

    P("-- A. Dipilih di paruh LATIH: CAGR tertinggi dengan batas drawdown, lalu dilihat di paruh UJI --")
    picks = {}
    for lim in (0.10, 0.15, 0.20, 0.25):
        ok = [r for r in rows if r[4] >= -lim]
        if ok:
            b = max(ok, key=lambda r: r[3])
            picks[lim] = b
            P(f"DD latih ≤ {int(lim*100)}%: {fmt(b)}")
    P("-- B. Calmar terbaik di paruh LATIH (5 teratas) --")
    for r in sorted(rows, key=lambda r: -(r[3] / abs(r[4]) if r[4] < 0 else 0))[:5]:
        P(fmt(r))
    P("-- C. Paling KONSISTEN: Calmar terendah dari dua paruh, terbesar (5 teratas) --")
    cons = sorted(rows, key=lambda r: -min(r[3] / abs(r[4]) if r[4] < 0 else 0, r[5] / abs(r[6]) if r[6] < 0 else 0))
    for r in cons[:5]:
        P(fmt(r))
    P("-- D. Pembanding (dipilih dengan melihat SELURUH 10 tahun = paling rawan kebetulan): CAGR tertinggi per batas drawdown --")
    for lim in (0.15, 0.20, 0.25):
        ok = [r for r in rows if r[2] >= -lim]
        if ok:
            P(f"DD 10th ≤ {int(lim*100)}%: {fmt(max(ok, key=lambda r: r[1]))}")
    P("-- E. Acuan sederhana --")
    for nm, w in (("100% CUR", [1, 0, 0, 0]), ("50 CUR + 50 EMAS", [.5, 0, 0, .5]), ("50 MIN + 50 EMAS", [0, .5, 0, .5]),
                  ("rata 4 sleeve (25% masing2)", [.25, .25, .25, .25]), ("1/3 CUR, MIN, EMAS", [1 / 3, 1 / 3, 0, 1 / 3])):
        w = np.array(w, float)
        e = combine(R, w, seg)
        cg, md = stats(e, yrs)
        c1, m1 = stats(combine(R[:cut], w, seg1), y1)
        c2, m2 = stats(combine(R[cut:], w, seg2), y2)
        P(f"{nm:28s} " + fmt((w, cg, md, c1, m1, c2, m2)))

    # ---------- rincian pilihan + uji modal riil ----------
    best = cons[0]
    if os.environ.get("OPT_PICK"):                      # bobot pilihan manual, urutan = `use`
        w = np.array([float(x) for x in os.environ["OPT_PICK"].split(",")])
        e_ = combine(R, w, seg)
        best = (w, *stats(e_, yrs), *stats(combine(R[:cut], w, seg1), y1), *stats(combine(R[cut:], w, seg2), y2))
    w = best[0]
    e = pd.Series(combine(R, w, seg) * base_eq, index=dates)
    q = kpi(e)
    P(f"== PILIHAN: {fmt(best)} ==")
    P(f"Sharpe {q['sharpe']:.2f} | vol {pc(q['vol'])} | per tahun: " + " ".join(f"{int(y)} {pc(v,0)}" for y, v in q["yr"].items()))
    dd = e / e.cummax() - 1
    P(f"drawdown terdalam {pc(dd.min())} pada {dd.idxmin().date()} | hari di bawah -10%: {100*(dd < -0.10).mean():.0f}% | terlama di bawah puncak: "
      f"{int((dd < 0).astype(int).groupby((dd >= 0).cumsum()).sum().max())} hari bursa")
    # modal riil: tiap sleeve saham dijalankan dengan modal sebesar jatahnya (kendala lot makin terasa)
    parts = {}
    for u, x in zip(use, w):
        if x <= 0:
            continue
        parts[u] = (build(base_eq * x)[u] / (base_eq * x)).pct_change().fillna(0).values if u != "EMAS" else rets[u].values
    Rr = np.column_stack([parts[u] for u in parts])
    wr = np.array([x for x in w if x > 0])
    er = combine(Rr, wr, seg)
    cg, md = stats(er, yrs)
    P(f"UJI MODAL RIIL (tiap sleeve saham hanya memegang jatahnya dari Rp{base_eq/1e6:.0f} jt): CAGR {pc(cg)} | MaxDD {pc(md)} | akhir Rp{base_eq*er[-1]/1e6:,.1f} jt")
    for mult in (5, 10):
        parts = {u: ((build(base_eq * mult * x)[u] / (base_eq * mult * x)).pct_change().fillna(0).values if u != "EMAS" else rets[u].values)
                 for u, x in zip(use, w) if x > 0}
        er = combine(np.column_stack([parts[u] for u in parts]), wr, seg)
        cg, md = stats(er, yrs)
        P(f"  dengan modal Rp{base_eq*mult/1e6:.0f} jt: CAGR {pc(cg)} | MaxDD {pc(md)}")
    P("SELESAI")


if __name__ == "__main__":
    main()
