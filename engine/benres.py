"""Riset: apakah saringan Beneish M-score memperbaiki model? Hanya ANALISIS.

    python -m engine.benres --cache .cache/panels.pkl

Data laporan tahunan Yahoo hanya ~4–5 tahun, jadi skor titik-waktu baru ada sejak ±2023–2024.
Pengujian hanya dihitung pada jendela setelah skor tersedia (bukan 10 tahun):
  1) studi peristiwa: return ke depan saham "berisiko" vs "aman" (semua saham likuid non-keuangan),
  2) sinyal BELI model: return ke depan menurut kategori Beneish saat sinyal muncul,
  3) trade yang benar-benar diambil backtest di jendela itu, per kategori,
  4) backtest dengan syarat tambahan (blokir berisiko / blokir abu-abu+berisiko), KPI di jendela saja.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, beneish, data, features, fundamentals, regime
from . import universe as uni_mod
from .flowmom import BASE, build, extras, pc
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def P(*a):
    print("BEN|", *a, flush=True)


def kpi_win(df, d0, n_tr):
    eq = df["eq"][df.index >= d0]
    eq = eq / eq.iloc[0]
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    r = eq.pct_change().dropna()
    ann = len(eq) / yrs
    mid = eq.index[len(eq) // 2]
    hv = []
    for h in (eq[:mid], eq[mid:]):
        y = max((h.index[-1] - h.index[0]).days / 365.25, 1e-9)
        cg, md = (h.iloc[-1] / h.iloc[0]) ** (1 / y) - 1, float((h / h.cummax() - 1).min())
        hv.append((cg, md, cg / abs(md) if md < 0 else 0.0))
    cagr, mdd = eq.iloc[-1] ** (1 / yrs) - 1, float((eq / eq.cummax() - 1).min())
    return {"cagr": cagr, "mdd": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else 0.0, "h": hv, "tot": eq.iloc[-1] - 1,
            "sharpe": (r.mean() * ann - 0.05) / (r.std() * np.sqrt(ann)) if r.std() > 0 else 0.0, "n": n_tr}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    cfg["signal"].pop("beneish_max", None)          # model dasar = TANPA saringan Beneish
    now = datetime.now(WIB)
    cache = data.load_cache(a.cache)
    if not cache:
        raise SystemExit("cache histori tidak ditemukan — jalankan update dulu")
    universe, _, _ = uni_mod.load(cfg, refresh=False)
    cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
    frames = {t: f for t, f in cache["frames"].items() if t in universe and len(f) and f.index[-1] >= cutoff}
    panels = data.build_panels(frames, list(frames))
    got = data.fetch_yahoo([cfg["macro"]["IHSG"], cfg["macro"]["USDIDR"]], hist_start(cfg, now))
    F = extras(features.compute(panels, cfg))
    fund = fundamentals.load(Path(a.cache).parent / "fundamentals.json")
    sectors = {t: universe[t].get("sector") for t in F["c"].columns}
    B = beneish.panel(fund, sectors, F["c"].index, F["c"].columns)
    ih = got[cfg["macro"]["IHSG"]]["Close"] if got.get(cfg["macro"]["IHSG"]) is not None else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    reg = regime.compute(ih, F, got[cfg["macro"]["USDIDR"]]["Close"] if got.get(cfg["macro"]["USDIDR"]) is not None else None)
    liq = F["liquid"].astype(bool)
    nonfin = pd.Series({t: not beneish.is_financial(sectors.get(t), (fund.get(t) or {}).get("ysector")) for t in F["c"].columns})
    base_u = liq & nonfin.values[None, :]

    # cakupan per tahun
    has = B.notna() & base_u
    cov = (has.sum(axis=1) / base_u.sum(axis=1).replace(0, np.nan)).fillna(0)
    P(f"DATA {F['c'].shape[1]} saham | fundamental {len(fund)} | punya laporan tahunan {sum(1 for q in fund.values() if (q.get('fs') or {}).get('a'))}")
    for y in sorted(set(cov.index.year)):
        c = cov[cov.index.year == y]
        if c.max() > 0:
            P(f"cakupan skor titik-waktu {y}: rata-rata {c.mean()*100:.0f}% saham likuid non-keuangan (maks {c.max()*100:.0f}%)")
    d0 = cov[cov >= 0.40].index.min()
    if d0 is None or pd.isna(d0):
        P("cakupan skor belum cukup (< 40%) — riset dibatalkan, tunggu pengambilan data fundamental selesai")
        return
    P(f"JENDELA UJI: {d0.date()} s/d {F['c'].index[-1].date()} ({(F['c'].index[-1]-d0).days/365.25:.1f} thn)")
    t_last = F["c"].index[-1]
    lv_now = B.loc[t_last][base_u.loc[t_last]]
    P(f"hari ini (likuid non-keuangan, {lv_now.notna().sum()} punya skor): berisiko {(lv_now > beneish.RISK).sum()} | "
      f"abu-abu {((lv_now > beneish.GREY) & (lv_now <= beneish.RISK)).sum()} | aman {(lv_now <= beneish.GREY).sum()} | median M {lv_now.median():.2f}")

    def cat(x):
        return np.where(np.isnan(x), "tanpa data", np.where(x > beneish.RISK, "berisiko", np.where(x > beneish.GREY, "abu-abu", "aman")))

    # 1) studi peristiwa bulanan
    c = F["c"]
    P("== 1) STUDI PERISTIWA: return ke depan vs rata-rata saham (selisih), sampel tiap awal bulan ==")
    days = c.index[c.index >= d0]
    mon = days[np.r_[True, days.month[1:] != days.month[:-1]]]
    for h in (60, 120):
        fwd = c.shift(-h) / c - 1
        rows = []
        for d in mon:
            if c.index.get_loc(d) + h >= len(c):
                continue
            u = base_u.loc[d] & fwd.loc[d].notna()
            f = fwd.loc[d][u]
            ex = f - f.mean()
            rows.append(pd.DataFrame({"ex": ex, "up": ex > 0, "k": cat(B.loc[d][u].values)}))
        if not rows:
            continue
        R = pd.concat(rows)
        g = R.groupby("k").agg(n=("ex", "size"), rata=("ex", "mean"), median=("ex", "median"), menang=("up", "mean"))
        for k, r_ in g.iterrows():
            P(f"  {h}H {k:11s} n={int(r_.n):5d} | selisih rata-rata {pc(r_.rata)} | median {pc(r_['median'])} | kalahkan rata-rata {r_.menang*100:.0f}%")

    # 2) sinyal BELI model (hari pertama sinyal muncul)
    comp, cond = build(F, cfg, reg, BASE)
    e = cond["entry"] & nonfin.values[None, :]
    first = e & ~e.shift(1, fill_value=False)
    first = first[first.index >= d0]
    P("== 2) SINYAL BELI MODEL: return ke depan dari hari sinyal muncul ==")
    for h in (20, 60):
        fwd = (c.shift(-h) / c - 1).reindex_like(first)
        st = first.stack()
        st = st[st]
        if not len(st):
            continue
        vals = np.array([fwd.at[d, t] for d, t in st.index])
        ks = np.array([cat(np.array([B.at[d, t]]))[0] for d, t in st.index])
        ok = ~np.isnan(vals)
        for k in ("aman", "abu-abu", "berisiko", "tanpa data"):
            m = ok & (ks == k)
            if m.sum():
                P(f"  {h}H {k:11s} n={m.sum():4d} | rata-rata {pc(vals[m].mean())} | median {pc(np.median(vals[m]))} | positif {(vals[m] > 0).mean()*100:.0f}%")

    # 3) trade yang diambil backtest
    _, det0 = backtest.run(F, comp, cond, reg, cfg, detail=True)
    P("== 3) TRADE MODEL SEKARANG di jendela uji, menurut Beneish saat masuk ==")
    T0 = det0["trades"]
    tr = T0[pd.to_datetime(T0["d0"]) >= d0] if len(T0) else T0
    agg = {}
    for _, t in tr.iterrows():
        x = B[t["t"]].asof(pd.Timestamp(t["d0"])) if t["t"] in B else np.nan
        agg.setdefault(cat(np.array([x]))[0], []).append(t["ret"])
    for k, v in agg.items():
        v = np.array(v)
        P(f"  {k:11s} {len(v):3d} trade | rata-rata {pc(v.mean())} | menang {(v > 0).mean()*100:.0f}% | terburuk {pc(v.min())} | terbaik {pc(v.max())}")

    # 4) backtest dengan saringan
    P("== 4) BACKTEST (KPI dihitung di jendela uji saja) ==")
    q0 = kpi_win(det0["df"], d0, len(tr))

    def line(label, q):
        P(f"{label:38s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | total {pc(q['tot'])} | "
          f"paruh-1 {pc(q['h'][0][0],0)}/{pc(q['h'][0][1],0)} paruh-2 {pc(q['h'][1][0],0)}/{pc(q['h'][1][1],0)} | {q['n']} trade")
    line("MODEL SEKARANG", q0)
    for lab, thr in (("blokir berisiko (M > −1,78)", beneish.RISK), ("blokir abu-abu+berisiko (M > −2,22)", beneish.GREY),
                     ("blokir M > −1,50", -1.50), ("blokir M > −2,00", -2.00)):
        blk = (B > thr).reindex_like(cond["entry"]).fillna(False)
        c2 = dict(cond)
        c2["entry"] = cond["entry"] & ~blk
        c2["strong"] = cond["strong"] & c2["entry"]
        _, det = backtest.run(F, comp, c2, reg, cfg, detail=True)
        q = kpi_win(det["df"], d0, int((pd.to_datetime(det["trades"]["d0"]) >= d0).sum()) if len(det["trades"]) else 0)
        ok = q["h"][0][2] > q0["h"][0][2] and q["h"][1][2] > q0["h"][1][2]
        line(lab + (" ✓" if ok else ""), q)
    P("SELESAI")


if __name__ == "__main__":
    main()
