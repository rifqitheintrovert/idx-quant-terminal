"""Fitur panel: money flow, momentum, trend, timing + skor 0..100.
Dipakai bersama oleh sinyal live dan backtest (agar backtest = logika yang sama)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


def compute(panels: dict[str, pd.DataFrame], cfg: dict, foreign: pd.DataFrame | None = None) -> dict:
    o, h, l, c, v = (panels[k] for k in ["Open", "High", "Low", "Close", "Volume"])
    F: dict[str, pd.DataFrame] = {"o": o, "h": h, "l": l, "c": c, "v": v}

    # ---------- likuiditas & money flow ----------
    value = c * v
    F["value"] = value
    F["avg_val20"] = value.rolling(20, min_periods=10).mean()
    F["avg_val60"] = value.rolling(60, min_periods=20).mean()
    nf = ind.net_flow_value(h, l, c, v)
    F["nf1"] = nf
    F["nf5"] = nf.rolling(5, min_periods=5).sum()
    F["nf20"] = nf.rolling(20, min_periods=20).sum()
    base = F["avg_val60"].replace(0, np.nan)
    F["nf5_int"] = F["nf5"] / (base * 5)
    F["nf20_int"] = F["nf20"] / (base * 20)
    F["cmf20"] = ind.cmf(h, l, c, v, 20)
    F["mfi14"] = ind.mfi(h, l, c, v, 14)
    F["obvm20"] = ind.obv_momentum(c, v, 20)
    F["volratio"] = value.rolling(5, min_periods=5).mean() / base
    # akumulasi jangka menengah (±3 bulan): inflow yang BERTAHAN, bukan lonjakan sesaat
    F["nf60"] = nf.rolling(60, min_periods=40).sum()
    F["nf60_int"] = F["nf60"] / (base * 60)
    F["accdays60"] = (nf > 0).rolling(60, min_periods=40).mean().where(c.notna())      # porsi hari dengan net inflow
    up, dn = value.where(c > c.shift(1), 0.0), value.where(c < c.shift(1), 0.0)
    F["updn50"] = (up.rolling(50, min_periods=30).sum() / dn.rolling(50, min_periods=30).sum().replace(0, np.nan)).where(c.notna())
    F["cmf60"] = ind.cmf(h, l, c, v, 60)
    F["obvm60"] = ind.obv_momentum(c, v, 60)
    if foreign is not None and not foreign.empty:
        fr = foreign.reindex(c.index).reindex(columns=c.columns)
        F["fnet1"] = fr
        F["fnet5"] = fr.rolling(5, min_periods=1).sum()
        F["fnet20"] = fr.rolling(20, min_periods=1).sum()
        F["fnet5_int"] = F["fnet5"] / (base * 5)

    # ---------- trend & momentum ----------
    F["ma20"] = ind.sma(c, 20)
    F["ma50"] = ind.sma(c, 50)
    F["ma200"] = ind.sma(c, 200)
    F["ma50_slope"] = F["ma50"] / F["ma50"].shift(10) - 1
    F["rsi14"] = ind.rsi(c, 14)
    F["atr14"] = ind.atr(h, l, c, 14)
    F["atr_pct"] = F["atr14"] / c
    for n, k in [(1, "ret1"), (5, "ret5"), (21, "ret21"), (63, "ret63"), (126, "ret126"), (252, "ret252")]:
        F[k] = c / c.shift(n) - 1
    F["mom_12_1"] = c.shift(21) / c.shift(252) - 1      # Jegadeesh-Titman / AMP 12-1
    F["mom_6_1"] = c.shift(21) / c.shift(126) - 1
    F["hi252"] = h.rolling(252, min_periods=120).max()
    F["lo252"] = l.rolling(252, min_periods=120).min()
    F["prox52"] = c / F["hi252"]                         # George-Hwang 52-week-high
    F["hh22"] = h.rolling(22, min_periods=22).max()
    F["chandelier"] = F["hh22"] - cfg["signal"]["trail_atr_mult"] * F["atr14"]
    F["z20"] = (c - F["ma20"]) / F["atr14"].replace(0, np.nan)

    # ---------- skor ----------
    liq = (F["avg_val20"] >= cfg["filters"]["min_avg_value_bn"] * 1e9) & (c >= cfg["filters"]["min_price"]) \
        & (c.notna().cumsum() >= int(cfg["filters"].get("min_history_days", 60)))
    F["liquid"] = liq

    def xs(p):  # peringkat cross-sectional hanya di antara saham likuid
        return ind.pct_rank_xs(p.where(liq))

    fast = [xs(F["nf20_int"]), xs(F["nf5_int"]), xs(F["cmf20"]), xs(F["obvm20"]), xs(F["mfi14"])]
    acc_parts = [xs(F["nf20_int"]), xs(F["nf60_int"]), xs(F["cmf20"]), xs(F["cmf60"]), xs(F["obvm60"]),
                 xs(F["updn50"]), xs(F["accdays60"])]
    if "fnet5_int" in F:
        fast.append(xs(F["fnet5_int"]))
        acc_parts.append(xs(F["fnet5_int"]))
    F["s_flow_fast"] = _nanmean(fast)           # skor lama: flow 5-20 hari
    F["s_flow_acc"] = _nanmean(acc_parts)       # skor akumulasi: flow 20-60 hari
    F["s_flow"] = F["s_flow_acc"] if str(cfg["signal"].get("flow_score", "akumulasi")) == "akumulasi" else F["s_flow_fast"]

    mom_long = F["mom_12_1"].where(F["mom_12_1"].notna(), F["mom_6_1"])
    F["s_mom"] = _nanmean([xs(mom_long), xs(F["mom_6_1"]), xs(F["ret63"]), xs(F["prox52"])])

    t = (c > F["ma20"]) * 20 + (c > F["ma50"]) * 25 + (c > F["ma200"]) * 25 \
        + (F["ma50"] > F["ma200"]) * 15 + (F["ma50_slope"] > 0) * 15
    F["s_trend"] = t.where(F["ma200"].notna(), t * 100 / 60).astype(float)

    z = F["z20"]
    tz = 100 - np.clip(z - 1.0, 0, None) * 28 - np.clip(-0.5 - z, 0, None) * 22
    tr = np.clip(F["rsi14"] - 68, 0, None) * 3 + np.clip(35 - F["rsi14"], 0, None) * 1.5
    F["s_timing"] = np.clip(tz - tr, 0, 100)

    # status akumulasi / distribusi (ala bandarmologi, dari OHLCV)
    acc = (F["cmf20"] > 0.05) & (F["nf20"] > 0) & (F["obvm20"] > 0)
    dist = (F["cmf20"] < -0.05) & (F["nf20"] < 0) & (F["obvm20"] < 0)
    F["acc"] = acc.astype(int) - dist.astype(int)
    return F


def composite(F: dict, w: dict, sentiment: pd.DataFrame | float | None = None) -> pd.DataFrame:
    """Skor komposit. Tanpa sentimen (backtest) bobot dinormalisasi ulang."""
    parts = {"flow": F["s_flow"], "momentum": F["s_mom"], "trend": F["s_trend"], "timing": F["s_timing"]}
    if sentiment is not None:
        parts["sentiment"] = sentiment
    parts = {k: p for k, p in parts.items() if w.get(k, 0) > 0}       # bobot 0 = komponen tidak dipakai
    tot = sum(w[k] for k in parts)
    out = None
    for k, p in parts.items():
        term = p * (w[k] / tot)
        out = term if out is None else out + term
    return out


def conditions(F: dict, comp: pd.DataFrame, cfg: dict, reg: pd.DataFrame | None = None) -> dict:
    s = cfg["signal"]
    c = F["c"]
    trend_ok = (c > F["ma50"]) & (F["ma20"] > F["ma50"])
    flow_any = (F["cmf20"] > 0) | (F["nf5"] > 0)
    flow_both = (F["cmf20"] > 0) & (F["nf5"] > 0)
    not_ob = F["rsi14"] < s["rsi_overbought"]
    liq = F["liquid"]
    exit_ = (c < F["chandelier"]) | ((c < F["ma50"]) & (F["cmf20"] < 0)) | (comp < s["exit"])
    entry = liq & (comp >= s["buy"]) & trend_ok & flow_any & not_ob & ~exit_
    if s.get("min_flow_score"):                 # inflow akumulasi harus kuat relatif terhadap saham lain
        entry = entry & (F["s_flow"] >= float(s["min_flow_score"]))
    if s.get("min_mom_score"):                  # momentum harus di papan atas (mis. >= 70 = top 30%)
        entry = entry & (F["s_mom"] >= float(s["min_mom_score"]))
    if s.get("max_atr_pct"):                    # saham terlalu liar -> jarak stop terlalu lebar, tidak dibeli
        entry = entry & (F["atr_pct"] <= float(s["max_atr_pct"]))
    gate, entry_raw = None, entry               # entry_raw = lolos semua kriteria saham, sebelum filter pasar
    if s.get("market_filter") and reg is not None:   # beli baru hanya saat pasar (IHSG) di atas MA-nya
        gate = (reg["ihsg"] > reg[str(s["market_filter"]).lower()]).reindex(c.index).fillna(False).astype(bool)
        entry = entry & gate.values[:, None]
    strong = entry & (comp >= s["strong_buy"]) & flow_both & (F["rsi14"] < s["rsi_overbought"] - 3)
    return {"entry": entry, "strong": strong, "exit": exit_, "trend_ok": trend_ok, "gate": gate, "entry_raw": entry_raw}


def _nanmean(frames: list[pd.DataFrame]) -> pd.DataFrame:
    stack = np.stack([f.values for f in frames])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            m = np.nanmean(stack, axis=0)
    return pd.DataFrame(m, index=frames[0].index, columns=frames[0].columns)
