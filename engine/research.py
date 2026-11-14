"""Riset strategi frekuensi rendah ("tahan badai") di data 10 tahun yang sama dengan backtest dashboard.
Hanya ANALISIS — tidak mengubah model/dashboard.

    python -m engine.research --cache .cache/panels.pkl

Keluarga yang diuji (semua: modal dari config, lot 100, fee BEI, sinyal di close -> eksekusi open besok,
tidak beli saat terkunci ARA / tanpa transaksi, kas berbunga 0%):
  MOM   momentum 12-1 bulan, N saham teratas, ganti bulanan/kuartalan
  LOWV  saham paling tenang (volatilitas 120 hari terendah)
  MIX   gabungan peringkat momentum + ketenangan
  SKOR  skor komposit dashboard, tapi hanya diganti bulanan
  +saklar: seluruh portofolio jadi kas saat IHSG < MA200 (dicek bulanan / harian)
  ALOKASI: sleeve saham + emas (Rp) + kas, diseimbangkan ulang tahunan
"""
from __future__ import annotations

import argparse
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, regime
from . import universe as uni_mod
from .idx_rules import WIB, ara_pct
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]
RF = 0.05


def P(*a):
    print("RISET|", *a, flush=True)


# ------------------------------------------------------------------ simulator rebalance berkala
def rebal_sim(F, rank, elig, cfg, start_i, *, n=10, reb="M", buffer=2.0, switch=None, daily_switch=False):
    """rank: array (hari x saham), makin BESAR makin disukai. elig: bool array saham yang boleh dipilih.
    switch: bool array per hari (True = boleh pegang saham)."""
    fee_b, fee_s, lot = cfg["idx_rules"]["fee_buy"], cfg["idx_rules"]["fee_sell"], cfg["idx_rules"]["lot_size"]
    eq0 = float(cfg["backtest"].get("initial_equity", 1e7))
    dates = F["c"].index
    C, O, H, L, V = F["c"].values, F["o"].values, F["h"].values, F["l"].values, F["v"].values
    per = dates.to_period("Q" if reb == "Q" else "M")
    last_of = np.append(per[1:] != per[:-1], False)          # hari bursa terakhir tiap bulan/kuartal
    cash, pos = eq0, {}
    sells, buys = [], []
    eqs, ntr = [], 0
    off = False
    for i in range(start_i, len(dates)):
        for j in list(sells):                                  # jual dulu
            if j in pos:
                if V[i, j] <= 0 or (H[i, j] == L[i, j] and C[i, j] <= C[i - 1, j] * 0.935):
                    continue                                   # terkunci ARB / tidak ada transaksi -> coba besok
                cash += pos.pop(j) * O[i, j] * (1 - fee_s)
                ntr += 1
            sells.remove(j)
        if buys:
            eq_open = cash + sum(sh * O[i, j] for j, sh in pos.items())
            for j in buys:
                px = O[i, j]
                if j in pos or not np.isfinite(px) or V[i, j] <= 0 or px >= C[i - 1, j] * (1 + ara_pct(C[i - 1, j]) - 0.01):
                    continue
                sh = math.floor(min(eq_open / n, cash) / (px * (1 + fee_b)) / lot) * lot
                if sh > 0:
                    cash -= sh * px * (1 + fee_b)
                    pos[j] = sh
                    ntr += 1
            buys = []
        eq = cash + sum(sh * C[i, j] for j, sh in pos.items())
        eqs.append(eq)
        on = True if switch is None else bool(switch[i])
        if daily_switch and not on and pos and not off:        # saklar harian: pasar jatuh di tengah bulan -> keluar
            sells = list(pos)
            off = True
        if last_of[i]:
            off = not on
            if not on:
                sells = list(pos)
            else:
                r = rank[i]
                ok = elig[i] & np.isfinite(r) & (C[i] * lot * (1 + fee_b) <= eq / n)   # harus sanggup beli 1 lot
                order = [j for j in np.argsort(-np.where(ok, r, -np.inf)) if ok[j]]
                keepset = set(order[:int(n * buffer)])
                keep = [j for j in pos if j in keepset]                               # zona penyangga: kurangi gonta-ganti
                sells = [j for j in pos if j not in keepset]
                buys = [j for j in order if j not in pos][:max(0, n - len(keep))]
    return pd.Series(eqs, index=dates[start_i:]), ntr


def kpi(eq, ntr=None):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    ann = len(eq) / yrs
    r = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    mdd = float((eq / eq.cummax() - 1).min())
    vol = r.std() * math.sqrt(ann)
    last = eq.groupby(eq.index.year).last()
    yr = last.pct_change()
    yr.iloc[0] = last.iloc[0] / eq.iloc[0] - 1
    mid = eq.index[len(eq) // 2]
    hs = []
    for h in (eq[:mid], eq[mid:]):
        hy = (h.index[-1] - h.index[0]).days / 365.25
        hr = h.pct_change().dropna()
        hc = (h.iloc[-1] / h.iloc[0]) ** (1 / hy) - 1
        hv = hr.std() * math.sqrt(ann)
        hs.append(((hr.mean() * ann - RF) / hv if hv > 0 else 0, hc, float((h / h.cummax() - 1).min())))
    return {"cagr": cagr, "mdd": mdd, "vol": vol, "sharpe": (r.mean() * ann - RF) / vol if vol > 0 else 0,
            "calmar": cagr / abs(mdd) if mdd < 0 else 0, "yr": yr, "h": hs, "tr": None if ntr is None else ntr / yrs,
            "final": eq.iloc[-1], "ulcer": float(np.sqrt(((eq / eq.cummax() - 1) ** 2).mean()))}


def pc(x, d=0):
    return "n/a" if x is None or not np.isfinite(x) else f"{x * 100:+.{d}f}%"


def line(name, q):
    y = q["yr"]
    g = lambda yy: pc(y.get(yy, float("nan")))  # noqa: E731
    trs = "-" if q["tr"] is None else f"{q['tr']:.0f}"
    P(f"{name:44s} Sharpe {q['sharpe']:+.2f} | Calmar {q['calmar']:.2f} | CAGR {pc(q['cagr'],1)} | MaxDD {pc(q['mdd'],1)} | vol {pc(q['vol']).replace('+','')} | "
      f"H1 S{q['h'][0][0]:+.2f} {pc(q['h'][0][1])}/{pc(q['h'][0][2])} H2 S{q['h'][1][0]:+.2f} {pc(q['h'][1][1])}/{pc(q['h'][1][2])} | "
      f"terburuk {pc(y.min())} | 2020 {g(2020)} 2021 {g(2021)} 2025 {g(2025)} 2026 {g(2026)} | "
      f"transaksi/th {trs} | akhir Rp{q['final']/1e6:,.1f} jt")


def blend(parts: dict[str, tuple[pd.Series, float]], reb_months=12, cost=0.003):
    """Portofolio beberapa aset (kurva ekuitas harian + bobot target), diseimbangkan ulang tiap N bulan.
    cost = biaya per rupiah yang dipindahkan saat rebalance."""
    names = list(parts)
    rets = pd.DataFrame({k: parts[k][0].pct_change().fillna(0) for k in names})
    w0 = np.array([parts[k][1] for k in names])
    cashw = 1 - w0.sum()
    val = w0.copy()
    cash = cashw
    out, last_m, n = [], None, 0
    for d, row in rets.iterrows():
        val = val * (1 + row.values)
        tot = val.sum() + cash
        m = d.year * 12 + d.month
        if last_m is None:
            last_m = m
        if m - last_m >= reb_months:
            tgt = w0 * tot
            moved = np.abs(tgt - val).sum()
            tot -= moved * cost
            val, cash, last_m, n = w0 * tot, cashw * tot, m, n + 1
        out.append(tot)
    return pd.Series(out, index=rets.index), n


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
    panels = data.build_panels(frames, tickers)
    F = features.compute(panels, cfg)
    idx = F["c"].index
    macro = {}
    if not a.no_macro:
        try:
            got = data.fetch_yahoo([cfg["macro"][k] for k in ("IHSG", "USDIDR", "GOLD")], hist_start(cfg, now))
            macro = {k: got.get(cfg["macro"][k]) for k in ("IHSG", "USDIDR", "GOLD")}
        except Exception as e:  # noqa: BLE001
            P("makro gagal:", e)
    if macro.get("IHSG") is not None:
        ihsg = macro["IHSG"]["Close"].reindex(idx).ffill().bfill()
    else:
        ihsg = (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    if macro.get("GOLD") is not None and macro.get("USDIDR") is not None:
        gold = (macro["GOLD"]["Close"].reindex(idx).ffill() * macro["USDIDR"]["Close"].reindex(idx).ffill()).ffill().bfill()
    else:
        rng = np.random.default_rng(3)
        gold = pd.Series(np.exp(np.cumsum(0.0004 + 0.009 * rng.standard_normal(len(idx)))), index=idx)
    reg = regime.compute(ihsg, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)
    comp = features.composite(F, cfg["weights"], None)

    bt = cfg["backtest"]
    ready = (F["mom_6_1"].notna() & F["ma200"].notna()).sum(axis=1) >= max(5, min(40, int(0.5 * F["c"].shape[1])))
    start_i = max(int(np.argmax(ready.values)), int(idx.searchsorted(idx[-1] - pd.Timedelta(days=int(float(bt["years"]) * 365.25)))))
    dates = idx[start_i:]
    P(f"DATA {len(tickers)} saham | {dates[0].date()}..{dates[-1].date()} | modal Rp{bt.get('initial_equity', 1e7):,.0f} | Sharpe memakai bunga bebas risiko {RF*100:.0f}%, kas dianggap berbunga 0%")

    c = F["c"]
    hist_ok = (c.notna().cumsum() >= 250).values
    stock_up = (c > F["ma200"]).values
    mom = F["mom_12_1"].values
    vol120 = c.pct_change().rolling(120, min_periods=100).std().values
    val60 = F["avg_val60"].values
    px_ok = (c >= 50).values

    def liq(bn):
        return (val60 >= bn * 1e9) & px_ok & hist_ok

    def xrank(x, ok):       # peringkat persentil antar saham yang memenuhi syarat (0..1)
        df = pd.DataFrame(np.where(ok, x, np.nan))
        return df.rank(axis=1, pct=True).values

    sw_ma200 = (ihsg > ihsg.rolling(200, min_periods=120).mean()).values
    res = {}

    def run_(name, rank, elig, **kw):
        eq, ntr = rebal_sim(F, rank, elig, cfg, start_i, **kw)
        res[name] = (eq, kpi(eq, ntr))

    # ---------- pembanding ----------
    cond = features.conditions(F, comp, cfg, reg)
    _, det = backtest.run(F, comp, cond, reg, cfg, detail=True)
    cur = det["df"]["eq"]
    res["00 STRATEGI SEKARANG (harian)"] = (cur, kpi(cur, len(det["trades"]) * 2))
    eq0 = float(bt.get("initial_equity", 1e7))
    ih = ihsg.iloc[start_i:] / ihsg.iloc[start_i] * eq0
    res["01 IHSG beli & tahan"] = (ih, kpi(ih, 0))
    g_ = gold.iloc[start_i:] / gold.iloc[start_i] * eq0
    res["02 Emas (Rp) beli & tahan"] = (g_, kpi(g_, 0))

    def timed(asset, ma=200):   # aset dipegang hanya saat di atas MA-nya (dicek akhir bulan), selain itu kas
        s = asset.iloc[start_i:]
        on = (asset > asset.rolling(ma, min_periods=120).mean())
        per = idx.to_period("M")
        month_end = pd.Series(np.append(per[1:] != per[:-1], False), index=idx)
        state = on.where(month_end).ffill().shift(1).fillna(False).astype(bool).iloc[start_i:]
        r = s.pct_change().fillna(0).where(state, 0.0)
        flips = int((state != state.shift(1)).sum())
        r = r - (state != state.shift(1)).astype(float) * 0.002
        return (1 + r).cumprod() * eq0, flips

    e, n_ = timed(ihsg)
    res["03 IHSG + saklar MA200 bulanan"] = (e, kpi(e, n_))
    e, n_ = timed(gold)
    res["04 Emas + saklar MA200 bulanan"] = (e, kpi(e, n_))

    # ---------- saham: momentum / low-vol / gabungan / skor ----------
    for bn in (10, 25, 50):
        el = liq(bn) & stock_up
        for n in (5, 10):
            run_(f"MOM  likuid≥{bn}M N{n} bulanan", mom, el, n=n)
            run_(f"MOM  likuid≥{bn}M N{n} bulanan +saklar", mom, el, n=n, switch=sw_ma200)
        run_(f"MOM  likuid≥{bn}M N10 bulanan +saklar harian", mom, el, n=10, switch=sw_ma200, daily_switch=True)
        run_(f"MOM  likuid≥{bn}M N10 kuartalan +saklar", mom, el, n=10, reb="Q", switch=sw_ma200)
    for bn in (10, 25, 50):
        el = liq(bn)
        run_(f"LOWV likuid≥{bn}M N10 kuartalan", -vol120, el, n=10, reb="Q")
        run_(f"LOWV likuid≥{bn}M N10 kuartalan +saklar", -vol120, el, n=10, reb="Q", switch=sw_ma200)
        elu = el & stock_up
        run_(f"LOWV+tren likuid≥{bn}M N10 kuartalan", -vol120, elu, n=10, reb="Q")
        mix = xrank(mom, elu) + xrank(-vol120, elu)
        run_(f"MIX  likuid≥{bn}M N10 bulanan", mix, elu, n=10)
        run_(f"MIX  likuid≥{bn}M N10 bulanan +saklar", mix, elu, n=10, switch=sw_ma200)
        run_(f"MIX  likuid≥{bn}M N10 kuartalan +saklar", mix, elu, n=10, reb="Q", switch=sw_ma200)
    ent = cond["entry_raw"].values if cond.get("entry_raw") is not None else cond["entry"].values
    run_("SKOR komposit N10 bulanan", comp.values, ent, n=10)
    run_("SKOR komposit N10 bulanan +saklar", comp.values, ent, n=10, switch=sw_ma200)

    P("== SAHAM SAJA (urut Sharpe) ==")
    for name, (eq, q) in sorted(res.items(), key=lambda kv: -kv[1][1]["sharpe"]):
        line(name, q)

    # ---------- alokasi aset: sleeve saham + emas + kas ----------
    P("== ALOKASI ASET (sleeve saham + emas Rp + kas; rebalance tahunan, biaya 0,3% dari nilai yang dipindah) ==")
    stock_only = {k: v for k, v in res.items() if k[:2] not in ("01", "02", "03", "04")}
    best = sorted(stock_only.items(), key=lambda kv: -min(kv[1][1]["h"][0][0], kv[1][1]["h"][1][0]))[:4]   # paling konsisten di 2 paruh
    sleeves = {k: v[0] for k, v in best}
    sleeves["00 STRATEGI SEKARANG (harian)"] = cur
    sleeves["03 IHSG + saklar MA200 bulanan"] = res["03 IHSG + saklar MA200 bulanan"][0]
    gold_t = res["04 Emas + saklar MA200 bulanan"][0]
    alloc = {}
    for sname, s_eq in sleeves.items():
        short = sname.split("  ")[0] if sname[:2].isdigit() else sname
        for ws, wg, gname, g_eq in ((0.5, 0.5, "emas", g_), (0.4, 0.4, "emas", g_), (0.6, 0.3, "emas", g_), (0.5, 0.5, "emas+saklar", gold_t)):
            e, n_ = blend({"s": (s_eq, ws), "g": (g_eq, wg)})
            nm = f"{int(ws*100)}% [{short}] + {int(wg*100)}% {gname}" + (f" + {int(round((1-ws-wg)*100))}% kas" if ws + wg < 0.999 else "")
            tr = (res[sname][1]["tr"] or 0) + 2 if sname in res else None
            q = kpi(e)
            q["tr"] = tr
            alloc[nm] = q
    for name, q in sorted(alloc.items(), key=lambda kv: -kv[1]["sharpe"]):
        line(name[:60], q)
    P("SELESAI")


if __name__ == "__main__":
    main()
