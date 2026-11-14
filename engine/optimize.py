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

    # rotasi sektor: 2 sektor dengan median return 3 bulan tertinggi (di antara saham likuid), ambil saham terkuatnya
    lq10 = liq(10)
    sec_of = pd.Series({t: universe[t]["sector"] for t in c.columns})
    r63 = F["ret63"].where(lq10)
    sec_med = pd.DataFrame({sname: r63.loc[:, sec_of[sec_of == sname].index].median(axis=1) for sname in sec_of.unique()})
    sec_n = pd.DataFrame({sname: lq10.loc[:, sec_of[sec_of == sname].index].sum(axis=1) for sname in sec_of.unique()})
    top = sec_med.where(sec_n >= 3).rank(axis=1, ascending=False) <= 2
    in_top = pd.DataFrame({t: top[sec_of[t]] for t in c.columns}, index=idx)
    sek_elig = (lq10 & (c > F["ma200"]) & in_top).values
    # beli saat panik: IHSG jatuh >= 20% dari puncak 1 tahun lalu mulai berbalik (di atas MA20) -> pegang 10 saham terlikuid
    # sampai IHSG kembali <= 5% dari puncak itu, atau gagal (turun 10% lagi di bawah harga saat masuk)
    hi = ihsg.rolling(252, min_periods=120).max().values
    ma20i = ihsg.rolling(20).mean().values
    iv = ihsg.values
    panic = np.zeros(len(idx), bool)
    on, ref_hi, ref_px = False, 0.0, 0.0
    for i in range(len(idx)):
        if not on and np.isfinite(hi[i]) and iv[i] <= hi[i] * 0.80 and iv[i] > ma20i[i]:
            on, ref_hi, ref_px = True, hi[i], iv[i]
        elif on and (iv[i] >= ref_hi * 0.95 or iv[i] <= ref_px * 0.90):
            on = False
        panic[i] = on

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
        out["SEK"], _ = rebal_sim(F, F["ret63"].values, sek_elig, cf, start_i, n=6, switch=gate)
        out["PANIK"], _ = rebal_sim(F, F["avg_val60"].values, liq(50).values, cf, start_i, n=10, switch=panic, daily_switch=True)
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
    P("korelasi return bulanan: " + " | ".join(f"{a_}-{b_} {mc.loc[a_, b_]:+.2f}" for a_, b_ in itertools.combinations(["CUR", "MIN", "SEK", "PANIK", "EMAS"], 2)))
    P(f"PANIK aktif {100*panic[start_i:].mean():.0f}% hari, {int((np.diff(panic[start_i:].astype(int)) == 1).sum())} kali masuk")

    # ---------- pencarian bobot ----------
    use = os.environ.get("OPT_USE", "CUR,MIN,SEK,PANIK").split(",")     # default: hanya saham Indonesia
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
    simple = [(f"100% {u}", [1.0 if k == j else 0.0 for k in range(len(use))]) for j, u in enumerate(use)]
    simple += [("rata semua sleeve", [1 / len(use)] * len(use)), (f"50/50 {use[0]}+{use[1]}", [.5, .5] + [0] * (len(use) - 2)),
               (f"40/40 {use[0]}+{use[1]} + 20 kas", [.4, .4] + [0] * (len(use) - 2)), (f"30/30 {use[0]}+{use[1]} + 40 kas", [.3, .3] + [0] * (len(use) - 2))]
    for nm, w in simple:
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
    # rem volatilitas: porsi dikecilkan saat campuran sedang bergejolak (tanpa leverage, biaya 0,4% dari porsi yang diubah)
    pr = e.pct_change().fillna(0)
    for look in (20, 60):
        rv = pr.rolling(look).std() * math.sqrt(242)
        for tgt in (0.08, 0.10, 0.12, 0.15):
            wt = (tgt / rv).clip(upper=1).shift(1).fillna(1)
            wt = wt.where((wt - wt.shift(1)).abs().fillna(1) > 0.1).ffill().fillna(1)          # ubah porsi hanya bila bergeser > 10 poin
            ev = (1 + pr * wt - (wt - wt.shift(1)).abs().fillna(0) * 0.004).cumprod().values
            cg, md = stats(ev, yrs)
            c1, m1 = stats(ev[:cut], y1)
            c2, m2 = stats(ev[cut:], y2)
            P(f"  + rem volatilitas {look}h target {int(tgt*100)}%: CAGR {pc(cg)} | MaxDD {pc(md)} | Calmar {cg/abs(md):.2f} | latih {pc(c1)}/{pc(m1)} | uji {pc(c2)}/{pc(m2)} | "
              f"porsi rata2 {100*wt.mean():.0f}% | perubahan porsi/th {int((wt != wt.shift(1)).sum()/yrs)}")
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
