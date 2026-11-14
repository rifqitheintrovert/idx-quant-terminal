"""Uji strategi Mark Minervini (SEPA, sisi teknikal) di data BEI 10 tahun. Hanya ANALISIS.

    python -m engine.minervini --cache .cache/panels.pkl

Yang diuji (tanpa data fundamental — syarat pertumbuhan laba Minervini TIDAK ikut):
  Trend Template (8 syarat): harga > MA150 & MA200; MA150 > MA200; MA200 naik >= 1 bulan; MA50 > MA150 > MA200;
    harga > MA50; harga >= 30% di atas low 52 minggu; harga <= 25% di bawah high 52 minggu; RS rating >= 70.
  Entry: breakout di atas pivot (high tertinggi basis 30 hari) dengan volume >= 1,5x rata-rata 50 hari,
    setelah konsolidasi yang mengetat (proxy VCP: rentang 10 hari sempit + volume mengering), tidak mengejar > 5% di atas pivot.
  Stop: 8% di bawah harga beli; naik ke impas setelah untung 2R; keluar bila close di bawah MA50.
  Ukuran: risiko 1,25% modal per trade (posisi = 1,25% / 8%), maks 25% per saham, maks 8 posisi.
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
from .idx_rules import WIB, ara_pct, round_tick
from .research import P, blend, kpi, line, rebal_sim
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]


def mm_sim(A, cfg, start_i, sig, rs, *, stop_pct=0.08, stop_mode="close", exit_ma="ma50", be_r=2.0, risk=0.0125,
           max_w=0.25, maxpos=8, gate=None, chase=0.05):
    fee_b, fee_s, lot = cfg["idx_rules"]["fee_buy"], cfg["idx_rules"]["fee_sell"], cfg["idx_rules"]["lot_size"]
    eq0 = float(cfg["backtest"].get("initial_equity", 1e7))
    dates, C, O, H, L, V, PIV = A["dates"], A["C"], A["O"], A["H"], A["L"], A["V"], A["PIV"]
    MA = A[exit_ma] if exit_ma else None
    cash, pos = eq0, {}
    exits, entries = {}, []
    eqs, trades = [], []

    def no_sell(i, j):
        return V[i, j] <= 0 or (H[i, j] == L[i, j] and C[i, j] <= C[i - 1, j] * 0.935)

    def sell(i, j, px, why):
        nonlocal cash
        p = pos.pop(j)
        got = p["sh"] * px * (1 - fee_s)
        cash += got
        trades.append((got / p["cost"] - 1, why, i - p["i0"]))

    for i in range(start_i, len(dates)):
        for j, why in list(exits.items()):
            if j not in pos:
                exits.pop(j)
            elif not no_sell(i, j):
                exits.pop(j)
                sell(i, j, O[i, j], why)
        if entries:
            eq_open = cash + sum(p["sh"] * O[i, j] for j, p in pos.items())
            for j in entries:
                if j in pos or len(pos) >= maxpos:
                    continue
                px = O[i, j]
                if not np.isfinite(px) or V[i, j] <= 0 or px >= C[i - 1, j] * (1 + ara_pct(C[i - 1, j]) - 0.01):
                    continue                                    # terkunci ARA / tanpa transaksi
                if px > PIV[i - 1, j] * (1 + chase + 0.02):
                    continue                                    # gap terlalu jauh dari pivot -> tidak dikejar
                sh = min(eq_open * risk / (px * stop_pct), eq_open * max_w / px, cash / (px * (1 + fee_b)))
                sh = math.floor(sh / lot) * lot
                if sh <= 0:
                    continue
                cost = sh * px * (1 + fee_b)
                cash -= cost
                pos[j] = {"sh": sh, "entry": px, "stop": round_tick(px * (1 - stop_pct), "down"), "cost": cost, "i0": i, "be": False}
            entries = []
        if stop_mode == "intraday":
            for j in list(pos):
                p = pos[j]
                if p["i0"] < i and L[i, j] <= p["stop"] and not no_sell(i, j):
                    exits.pop(j, None)
                    sell(i, j, min(O[i, j], p["stop"]), "stop")
        eq = cash + sum(p["sh"] * C[i, j] for j, p in pos.items())
        eqs.append(eq)
        for j, p in pos.items():
            if j in exits:
                continue
            if stop_mode == "close" and C[i, j] <= p["stop"]:
                exits[j] = "impas" if p["be"] else "stop"
            elif MA is not None and np.isfinite(MA[i, j]) and C[i, j] < MA[i, j]:
                exits[j] = "MA"
            elif be_r and not p["be"] and C[i, j] >= p["entry"] * (1 + be_r * stop_pct):
                p["be"] = True
                p["stop"] = max(p["stop"], round_tick(p["entry"] * (1 + fee_b + fee_s), "up"))
        slots = maxpos - (len(pos) - sum(1 for j in exits if j in pos))
        if slots > 0 and (gate is None or gate[i]):
            cand = [j for j in np.flatnonzero(sig[i]) if j not in pos]
            cand.sort(key=lambda j: -(rs[i, j] if np.isfinite(rs[i, j]) else -1))
            entries = cand[:slots]
    eq = pd.Series(eqs, index=dates[start_i:])
    q = kpi(eq, 2 * len(trades))
    r = np.array([t[0] for t in trades]) if trades else np.array([0.0])
    w, l_ = r[r > 0], r[r <= 0]
    why = pd.Series([t[1] for t in trades]).value_counts().to_dict() if trades else {}
    q["tstat"] = (f"trade {len(trades)} | win {100*len(w)/max(1,len(r)):.0f}% | rata2 untung {100*(w.mean() if len(w) else 0):+.1f}% | "
                  f"rata2 rugi {100*(l_.mean() if len(l_) else 0):+.1f}% | rugi terburuk {100*r.min():+.1f}% | untung terbaik {100*r.max():+.0f}% | "
                  f"rata2 hold {np.mean([t[2] for t in trades]) if trades else 0:.0f} hari | keluar: {why}")
    return eq, q


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
    eq0 = float(bt.get("initial_equity", 1e7))

    # ---------- Trend Template ----------
    c, h, l, v = F["c"], F["h"], F["l"], F["v"]
    ma50, ma150, ma200 = F["ma50"], c.rolling(150, min_periods=150).mean(), F["ma200"]
    hi52, lo52 = F["hi252"], F["lo252"]

    def liq(bn):
        return (F["avg_val20"] >= bn * 1e9) & (c >= 50) & (c.notna().cumsum() >= 260)

    rs_raw = 0.4 * (c / c.shift(63) - 1) + 0.2 * (c / c.shift(126) - 1) + 0.2 * (c / c.shift(189) - 1) + 0.2 * (c / c.shift(252) - 1)

    def template(bn, rs_min=0.70):
        lq = liq(bn)
        rs = rs_raw.where(lq).rank(axis=1, pct=True)
        tt = (lq & (c > ma150) & (c > ma200) & (ma150 > ma200) & (ma200 > ma200.shift(21)) & (ma50 > ma150) & (ma50 > ma200)
              & (c > ma50) & (c >= lo52 * 1.30) & (c >= hi52 * 0.75) & (rs >= rs_min))
        return tt, rs

    base = 30
    pivot = h.rolling(base, min_periods=base).max().shift(1)                  # high tertinggi basis (tanpa hari ini)
    base_low = l.rolling(base, min_periods=base).min().shift(1)
    depth = (pivot - base_low) / pivot                                       # kedalaman basis
    tight = ((h.rolling(10).max() - l.rolling(10).min()) / c).shift(1)        # rentang 10 hari sebelum breakout
    vol50 = v.rolling(50, min_periods=30).mean()
    dry = (v.rolling(10).mean() / vol50).shift(1)                            # volume mengering sebelum breakout
    brk = (c > pivot) & (c <= pivot * 1.05) & (v >= 1.5 * vol50.shift(1))

    def signal(tt, vcp=True, depth_max=0.30, tight_max=0.12):
        s = tt.shift(1, fill_value=False) & brk & (depth <= depth_max)
        if vcp:
            s = s & (tight <= tight_max) & (dry < 1.0)
        return s.values

    A = {"dates": idx, "C": c.values, "O": F["o"].values, "H": h.values, "L": l.values, "V": v.values, "PIV": pivot.values,
         "ma50": ma50.values, "ma20": F["ma20"].values}
    gate = (ihsg > ihsg.rolling(200, min_periods=120).mean()).values
    tt10, rs10 = template(10)
    tt25, rs25 = template(25)
    P(f"DATA {len(tickers)} saham | {idx[start_i].date()}..{idx[-1].date()} | modal Rp{eq0:,.0f} | rata2 saham lolos Trend Template per hari: "
      f"{tt10.iloc[start_i:].sum(axis=1).mean():.0f} (likuid≥10M), {tt25.iloc[start_i:].sum(axis=1).mean():.0f} (≥25M) | "
      f"sinyal breakout VCP per tahun: {signal(tt10)[start_i:].sum() / 10:.0f}, tanpa syarat VCP: {signal(tt10, vcp=False)[start_i:].sum() / 10:.0f}")

    res = {}
    comp = features.composite(F, cfg["weights"], None)
    _, det = backtest.run(F, comp, features.conditions(F, comp, cfg, reg), reg, cfg, detail=True)
    cur = det["df"]["eq"]
    res["00 STRATEGI SEKARANG"] = (cur, kpi(cur, 2 * len(det["trades"])))
    ih = ihsg.iloc[start_i:] / ihsg.iloc[start_i] * eq0
    res["01 IHSG beli & tahan"] = (ih, kpi(ih, 0))

    s10, s10p, s25 = signal(tt10), signal(tt10, vcp=False), signal(tt25)
    tests = [
        ("M1 Minervini dasar (VCP, stop 8%, MA50)", s10, rs10, {}),
        ("M2 M1 + hanya saat IHSG > MA200", s10, rs10, dict(gate=gate)),
        ("M3 M2 + stop intraday", s10, rs10, dict(gate=gate, stop_mode="intraday")),
        ("M4 M2 + stop 10%", s10, rs10, dict(gate=gate, stop_pct=0.10)),
        ("M5 M2 + stop 6%", s10, rs10, dict(gate=gate, stop_pct=0.06)),
        ("M6 M2 tanpa syarat VCP (breakout biasa)", s10p, rs10, dict(gate=gate)),
        ("M7 M2 + keluar di MA20 (lebih cepat)", s10, rs10, dict(gate=gate, exit_ma="ma20")),
        ("M8 M2 tanpa naik ke impas", s10, rs10, dict(gate=gate, be_r=None)),
        ("M9 M2 + likuid ≥ Rp25 M", s25, rs25, dict(gate=gate)),
        ("M10 M2 + risiko 1%, 10 posisi", s10, rs10, dict(gate=gate, risk=0.01, maxpos=10, max_w=0.20)),
        ("M11 M6 + likuid ≥ Rp25 M", signal(tt25, vcp=False), rs25, dict(gate=gate)),
        ("M12 M6 + stop intraday", s10p, rs10, dict(gate=gate, stop_mode="intraday")),
    ]
    stats = {}
    for name, sg, rs_, kw in tests:
        eq, q = mm_sim(A, cfg, start_i, sg, rs_.values, **kw)
        res[name] = (eq, q)
        stats[name] = q["tstat"]
    # Trend Template sebagai portofolio berkala (frekuensi rendah): 10 saham RS tertinggi yang lolos template
    for nm, kw in (("T1 Trend Template top-10 RS bulanan", {}), ("T2 T1 + saklar IHSG MA200", dict(switch=gate)),
                   ("T3 Trend Template top-10 RS kuartalan + saklar", dict(switch=gate, reb="Q"))):
        eq, ntr = rebal_sim(F, rs10.values, tt10.values, cfg, start_i, n=10, **kw)
        res[nm] = (eq, kpi(eq, ntr))

    P("== HASIL (urut Sharpe) ==")
    for name, (eq, q) in sorted(res.items(), key=lambda kv: -kv[1][1]["sharpe"]):
        line(name, q)
    P("== RINCIAN TRADE ==")
    for name, t in stats.items():
        P(f"{name:44s} {t}")
    P("== DENGAN 50% EMAS (rebalance tahunan) ==")
    g_ = gold.iloc[start_i:] / gold.iloc[start_i] * eq0
    best = sorted(((k, v) for k, v in res.items() if k[0] in "MT"), key=lambda kv: -kv[1][1]["sharpe"])[:3]
    for name, (eq, q0) in [("00 STRATEGI SEKARANG", res["00 STRATEGI SEKARANG"])] + best:
        e, _ = blend({"s": (eq, 0.5), "g": (g_, 0.5)})
        q = kpi(e * eq0)
        q["tr"] = (q0["tr"] or 0) + 2
        line(f"50% [{name.split(' ')[0]}] + 50% emas", q)
    P("SELESAI")


if __name__ == "__main__":
    main()
