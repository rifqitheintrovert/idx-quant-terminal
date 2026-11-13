"""Snapshot sinyal per saham (status, level entry/SL/TP, alasan) + ringkasan pasar."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .idx_rules import round_tick


def _f(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(x) else round(x, nd)


def _arr(s: pd.Series, nd=0, scale=1.0):
    out = []
    for x in s.values:
        x = float(x) * scale if x is not None else float("nan")
        out.append(None if not math.isfinite(x) else (int(round(x)) if nd == 0 else round(x, nd)))
    return out


def rp_bn(x):
    return _f(x / 1e9, 2)


def _col(a, nd=0, scale=1.0):
    out = np.round(np.asarray(a, dtype=float) * scale, nd).tolist()
    return [None if x != x else (int(x) if nd == 0 else x) for x in out]


def snapshot(F, comp_live, comp_hist, cond, sent, universe, cfg, regime_label, nbars):
    """-> (stocks, dates, series). `series[t]` = data chart per saham (ditulis ke file terpisah)."""
    s = cfg["signal"]
    arb = cfg["idx_rules"]["arb_pct"]
    idx = F["c"].index[-nbars:]
    stocks, series = [], {}
    frames = {k: v for k, v in F.items() if isinstance(v, pd.DataFrame)}
    last = {k: v.iloc[-1].to_dict() for k, v in frames.items()}        # baris terakhir tiap fitur
    prevc = F["c"].iloc[-2].to_dict() if len(F["c"]) > 1 else {}
    comp_last = comp_live.iloc[-1].to_dict()
    cl = {k: cond[k].iloc[-1].to_dict() for k in ("entry", "strong", "exit", "entry_raw") if cond.get(k) is not None}
    mf = str(s.get("market_filter") or "").upper()
    max_atr = s.get("max_atr_pct")
    tails = {k: frames[k].iloc[-nbars:] for k in ("o", "h", "l", "c", "v", "ma20", "ma50", "ma200", "nf1")}
    score_tail = comp_hist.iloc[-nbars:]
    for t in F["c"].columns:
        L = {k: v.get(t) for k, v in last.items()}
        if L["c"] is None or not np.isfinite(L["c"]):
            continue
        c = float(L["c"])
        atr = float(L["atr14"]) if np.isfinite(L["atr14"]) else c * 0.03
        sc = {
            "flow": _f(L["s_flow"], 1), "momentum": _f(L["s_mom"], 1), "trend": _f(L["s_trend"], 1),
            "timing": _f(L["s_timing"], 1), "sentiment": _f(sent["per_ticker"].get(t, {}).get("score", 50), 1),
            "composite": _f(comp_last.get(t), 1),
        }
        comp = sc["composite"] or 0
        liquid = bool(L["liquid"])
        ent, strong, ext = bool(cl["entry"][t]), bool(cl["strong"][t]), bool(cl["exit"][t])
        rsi = float(L["rsi14"]) if np.isfinite(L["rsi14"]) else 50
        acc = int(L["acc"]) if np.isfinite(L["acc"]) else 0

        notes = []
        if not liquid:
            sig = "AVOID"
        elif ext:
            sig = "EXIT"
        elif strong and regime_label != "RISK-OFF":
            sig = "STRONG BUY"
        elif ent or strong:
            sig = "BUY"
            if regime_label == "RISK-OFF":
                notes.append("Rezim RISK-OFF: ukuran posisi diperkecil")
        elif liquid and cl.get("entry_raw", {}).get(t):       # lolos kriteria saham, tapi pasar sedang tidak mendukung
            sig = "HOLD"
            notes.append(f"Lolos kriteria beli, tapi DITAHAN filter pasar (IHSG di bawah {mf}) — masuk daftar pantau")
        elif comp < s["reduce"] or rsi > 80 or acc < 0:
            sig = "REDUCE"
        else:
            sig = "HOLD"

        # ---- level harga (fraksi BEI) ----
        ma20 = float(L["ma20"]) if np.isfinite(L["ma20"]) else c
        lo = c - 0.75 * atr
        if lo < ma20 < c:
            lo = ma20
        entry_low, entry_high = round_tick(lo, "down"), round_tick(c, "nearest")
        sl = round_tick(c - s["atr_stop_mult"] * atr, "down")
        sl = min(sl, entry_low - 1) if entry_low > 1 else sl
        R = max(c - sl, 1)
        tp1, tp2 = round_tick(c + s["tp1_r"] * R, "up"), round_tick(c + s["tp2_r"] * R, "up")
        trail = round_tick(float(L["chandelier"]), "down") if np.isfinite(L["chandelier"]) else None
        sl_pct = sl / c - 1
        if abs(sl_pct) > arb and sig in ("BUY", "STRONG BUY"):
            notes.append(f"Jarak SL {sl_pct*100:.1f}% > batas ARB {arb*100:.0f}%/hari: eksekusi SL bisa butuh >1 hari")

        reasons = _reasons(L, sc, sent["per_ticker"].get(t, {}), liquid, cfg)
        if sig == "HOLD" and notes and "DITAHAN" in notes[-1]:
            reasons.insert(0, {"t": f"Ditahan filter pasar (IHSG < {mf})", "s": 0})
        if max_atr and liquid and np.isfinite(L["atr_pct"]) and L["atr_pct"] > max_atr:
            reasons.append({"t": f"Terlalu liar: ATR {L['atr_pct']*100:.1f}%/hari > {max_atr*100:g}%", "s": -1})
        pc = prevc.get(t)
        series[t] = {
            "o": _col(tails["o"][t]), "h": _col(tails["h"][t]), "l": _col(tails["l"][t]),
            "c": _col(tails["c"][t]), "v": _col(tails["v"][t]),
            "ma20": _col(tails["ma20"][t]), "ma50": _col(tails["ma50"][t]), "ma200": _col(tails["ma200"][t]),
            "nf": _col(tails["nf1"][t], 2, 1e-9), "score": _col(score_tail[t]),
        }
        stocks.append({
            "ticker": t, "name": universe[t]["name"], "sector": universe[t]["sector"],
            "last": _f(c, 0), "chg": _f(c - pc, 0) if pc is not None and np.isfinite(pc) else 0,
            "chg_pct": _f(L["ret1"], 4), "signal": sig, "scores": sc, "notes": notes,
            "levels": {"entry_low": entry_low, "entry_high": entry_high, "sl": sl, "sl_pct": _f(sl_pct, 4),
                       "tp1": tp1, "tp2": tp2, "trail": trail, "rr1": _f((tp1 - c) / R, 2), "rr2": _f((tp2 - c) / R, 2),
                       "atr": _f(atr, 1), "atr_pct": _f(L["atr_pct"], 4)},
            "flow": {"nf1": rp_bn(L["nf1"]), "nf5": rp_bn(L["nf5"]), "nf20": rp_bn(L["nf20"]),
                     "cmf": _f(L["cmf20"], 3), "mfi": _f(L["mfi14"], 1), "obvm": _f(L["obvm20"], 3),
                     "volratio": _f(L["volratio"], 2), "value": rp_bn(L["value"]), "avg_val20": rp_bn(L["avg_val20"]),
                     "status": "AKUMULASI" if acc > 0 else "DISTRIBUSI" if acc < 0 else "NETRAL",
                     "fnet1": rp_bn(L["fnet1"]) if "fnet1" in L and L["fnet1"] is not None else None,
                     "fnet5": rp_bn(L["fnet5"]) if "fnet5" in L and L["fnet5"] is not None else None,
                     "fnet20": rp_bn(L["fnet20"]) if "fnet20" in L and L["fnet20"] is not None else None},
            "ind": {"rsi": _f(rsi, 1), "ma20": _f(L["ma20"], 0), "ma50": _f(L["ma50"], 0), "ma200": _f(L["ma200"], 0),
                    "z20": _f(L["z20"], 2), "ret5": _f(L["ret5"], 4), "ret21": _f(L["ret21"], 4),
                    "ret63": _f(L["ret63"], 4), "ret252": _f(L["ret252"], 4), "mom_12_1": _f(L["mom_12_1"], 4),
                    "hi52": _f(L["hi252"], 0), "lo52": _f(L["lo252"], 0), "prox52": _f(L["prox52"], 3)},
            "sent": sent["per_ticker"].get(t, {}),
            "reasons": reasons,
        })
    order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "REDUCE": 3, "EXIT": 4, "AVOID": 5}
    stocks.sort(key=lambda x: (order[x["signal"]], -(x["scores"]["composite"] or 0)))
    return stocks, [d.strftime("%Y-%m-%d") for d in idx], series


def _reasons(L, sc, se, liquid, cfg):
    r = []

    def add(txt, sign):
        r.append({"t": txt, "s": sign})

    c = float(L["c"])
    if not liquid:
        add(f"Likuiditas < Rp{cfg['filters']['min_avg_value_bn']} M/hari", -1)
    cmf = L["cmf20"]
    if L["acc"] > 0:
        add(f"Akumulasi (CMF {cmf:+.2f})", 1)
    elif L["acc"] < 0:
        add(f"Distribusi (CMF {cmf:+.2f})", -1)
    nf5 = L["nf5"] / 1e9 if np.isfinite(L["nf5"]) else 0
    if abs(nf5) >= 1:
        add(f"{'Inflow' if nf5 > 0 else 'Outflow'} 5H ≈ Rp{abs(nf5):,.0f} M".replace(",", "."), 1 if nf5 > 0 else -1)
    if "fnet5" in L and L["fnet5"] is not None and np.isfinite(L["fnet5"]) and abs(L["fnet5"]) > 1e9:
        add(f"Asing net {'beli' if L['fnet5'] > 0 else 'jual'} 5H Rp{abs(L['fnet5'])/1e9:,.0f} M", 1 if L["fnet5"] > 0 else -1)
    if np.isfinite(L["volratio"]) and L["volratio"] >= 1.6:
        add(f"Nilai transaksi 5H {L['volratio']:.1f}x rata-rata", 1 if nf5 > 0 else -1)
    if sc["momentum"] is not None:
        if sc["momentum"] >= 80:
            add("Momentum top 20% universe", 1)
        elif sc["momentum"] <= 20:
            add("Momentum bottom 20% universe", -1)
    if np.isfinite(L["prox52"]) and L["prox52"] >= 0.95:
        add("Dekat 52-week high", 1)
    if np.isfinite(L["ma200"]):
        if c > L["ma50"] > L["ma200"]:
            add("Uptrend: di atas MA50 & MA200", 1)
        elif c < L["ma200"]:
            add("Di bawah MA200", -1)
    rsi = L["rsi14"]
    if np.isfinite(rsi):
        if rsi >= cfg["signal"]["rsi_overbought"]:
            add(f"RSI {rsi:.0f} overbought", -1)
        elif rsi <= 30:
            add(f"RSI {rsi:.0f} oversold", 0)
    z = L["z20"]
    if np.isfinite(z):
        if z > 2.2:
            add(f"Sudah {z:.1f} ATR di atas MA20 — rawan pullback", -1)
        elif -0.6 < z < 0.8 and c > L["ma50"]:
            add("Dekat area support MA20", 1)
    if np.isfinite(L["chandelier"]) and c < L["chandelier"]:
        add("Tutup di bawah trailing stop", -1)
    if se.get("n", 0) > 0:
        if se["score"] >= 58:
            add(f"Sentimen positif ({se['n']} berita)", 1)
        elif se["score"] <= 42:
            add(f"Sentimen negatif ({se['n']} berita)", -1)
    r.sort(key=lambda x: -x["s"])
    return r


def _gate(reg, stocks, cfg):
    """Gerbang beli: filter pasar yang menentukan boleh/tidaknya membuka posisi baru."""
    mf = cfg["signal"].get("market_filter")
    if not mf:
        return None
    r = reg.iloc[-1]
    ma = r[str(mf).lower()]
    return {"rule": f"IHSG > {str(mf).upper()}", "open": bool(np.isfinite(ma) and r["ihsg"] > ma), "ihsg": _f(r["ihsg"], 2),
            "ma": _f(ma, 2), "gap": _f(r["ihsg"] / ma - 1, 4) if np.isfinite(ma) and ma else None,
            "held": sum(1 for s in stocks if any("DITAHAN" in n for n in s["notes"]))}


def market_block(F, reg, macro, stocks, sent, cfg, nbars):
    idx = F["c"].index
    rlast = reg.iloc[-1]
    ih = reg["ihsg"]
    lab = rlast["label"]
    comps = [
        {"k": "IHSG vs MA200", "v": f"{(ih.iloc[-1]/rlast['ma200']-1)*100:+.1f}%" if np.isfinite(rlast["ma200"]) else "n/a",
         "s": 1 if rlast["ihsg_gt_ma200"] else -1},
        {"k": "MA50 vs MA200", "v": "golden" if rlast["ma50_gt_ma200"] else "death/flat",
         "s": 1 if rlast["ma50_gt_ma200"] else -1},
        {"k": "Breadth (>MA50)", "v": f"{rlast['breadth']*100:.0f}%" if np.isfinite(rlast["breadth"]) else "n/a",
         "s": int(rlast["breadth_strong"] + rlast["breadth_weak"])},
        {"k": "Volatilitas IHSG", "v": f"{rlast['vol20']*100:.0f}% (pct {rlast['vol_pct']*100:.0f})" if np.isfinite(rlast["vol_pct"]) else "n/a",
         "s": int(rlast["vol_high"])},
        {"k": "USD/IDR 20H", "v": f"{rlast['fx20']*100:+.1f}%" if np.isfinite(rlast["fx20"]) else "n/a", "s": int(rlast["rupiah_weak"])},
        {"k": "Drawdown 52W", "v": f"{rlast['dd']*100:.1f}%" if np.isfinite(rlast["dd"]) else "n/a", "s": 0},
    ]
    mac = []
    for name, df in macro.items():
        if df is None or df.empty or name == "IHSG":
            continue
        cl = df["Close"].dropna()
        if len(cl) < 2:
            continue
        mac.append({"name": name, "last": _f(cl.iloc[-1], 2), "chg_pct": _f(cl.iloc[-1] / cl.iloc[-2] - 1, 4),
                    "chg20": _f(cl.iloc[-1] / cl.iloc[-21] - 1, 4) if len(cl) > 21 else None,
                    "spark": [_f(x, 3) for x in cl.iloc[-60:].values]})
    # sektor
    df = pd.DataFrame([{"sector": s["sector"], "nf1": s["flow"]["nf1"] or 0, "nf5": s["flow"]["nf5"] or 0,
                        "nf20": s["flow"]["nf20"] or 0, "flow": s["scores"]["flow"] or 50,
                        "ret1": s["chg_pct"] or 0, "ret5": s["ind"]["ret5"] or 0, "ret21": s["ind"]["ret21"] or 0,
                        "acc": 1 if s["flow"]["status"] == "AKUMULASI" else 0,
                        "dist": 1 if s["flow"]["status"] == "DISTRIBUSI" else 0} for s in stocks])
    sectors = []
    for sec, g in df.groupby("sector"):
        sectors.append({"sector": sec, "n": int(len(g)), "nf1": _f(g.nf1.sum(), 1), "nf5": _f(g.nf5.sum(), 1),
                        "nf20": _f(g.nf20.sum(), 1), "flow": _f(g.flow.mean(), 1), "ret1": _f(g.ret1.mean(), 4),
                        "ret5": _f(g.ret5.mean(), 4), "ret21": _f(g.ret21.mean(), 4),
                        "acc": int(g.acc.sum()), "dist": int(g.dist.sum())})
    sectors.sort(key=lambda x: -(x["nf5"] or 0))
    liq = [s for s in stocks if s["signal"] != "AVOID"]
    by = lambda key, rev: [s["ticker"] for s in sorted(liq, key=key, reverse=rev)[:8]]  # noqa: E731
    n = min(nbars, len(ih))
    adv = sum(1 for s in stocks if (s["chg_pct"] or 0) > 0)
    dec = sum(1 for s in stocks if (s["chg_pct"] or 0) < 0)
    lq = F["liquid"].iloc[-1].astype(bool)
    above200 = (F["c"].iloc[-1] > F["ma200"].iloc[-1])[lq] if lq.any() else pd.Series([np.nan])
    return {
        "ihsg": {"last": _f(ih.iloc[-1], 2), "chg": _f(ih.iloc[-1] - ih.iloc[-2], 2),
                 "chg_pct": _f(ih.iloc[-1] / ih.iloc[-2] - 1, 4), "ret21": _f(ih.iloc[-1] / ih.iloc[-22] - 1, 4),
                 "series": _arr(ih.iloc[-n:], 2), "ma50": _arr(reg["ma50"].iloc[-n:], 2),
                 "ma200": _arr(reg["ma200"].iloc[-n:], 2), "regime": [int(x) for x in reg["score"].iloc[-n:].values]},
        "regime": {"label": lab, "score": int(rlast["score"]), "exposure": cfg["regime_exposure"][lab], "components": comps},
        "breadth": {"above_ma50": _f(rlast["breadth"], 3), "above_ma200": _f(above200.mean(), 3),
                    "adv": adv, "dec": dec, "unch": len(stocks) - adv - dec},
        "macro": mac,
        "sectors": sectors,
        "top_inflow": by(lambda s: s["flow"]["nf5"] or 0, True),
        "top_outflow": by(lambda s: s["flow"]["nf5"] or 0, False),
        "gainers": by(lambda s: s["chg_pct"] or 0, True),
        "losers": by(lambda s: s["chg_pct"] or 0, False),
        "signal_count": {k: sum(1 for s in stocks if s["signal"] == k)
                         for k in ["STRONG BUY", "BUY", "HOLD", "REDUCE", "EXIT", "AVOID"]},
        "sentiment": sent["market"],
        "gate": _gate(reg, stocks, cfg),
    }
