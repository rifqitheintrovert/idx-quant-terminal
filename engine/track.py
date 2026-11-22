"""Track record live: catatan sinyal harian yang tidak pernah ditulis ulang + portofolio kertas.

File repo: track/idx.json (di-commit oleh workflow). Isi:
  days   : satu baris per hari bursa yang SELESAI — sinyal BUY/STRONG BUY, saham DITAHAN filter pasar, saham di
           portofolio kertas yang kena EXIT, status gerbang, IHSG. Baris yang sudah ada tidak diubah.
  pf     : portofolio kertas (modal awal = backtest.initial_equity) yang mengeksekusi sinyal tercatat dengan
           aturan backtest: beli/jual di harga OPEN hari bursa berikutnya, ukuran posisi berbasis risiko, stop
           berbasis close, trailing chandelier, slot sesuai rezim + rem drawdown. Trade yang sudah tutup tidak diubah.
Statistik return maju sinyal (5 & 20 hari) dihitung ulang dari harga tiap run — bukan bagian catatan permanen.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .idx_rules import ara_pct, round_tick

log = logging.getLogger("track")
VERSION = 1


def _f(x, d=2):
    try:
        x = float(x)
        return round(x, d) if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def load(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _new(cfg, start):
    bt = cfg["backtest"]
    eq0 = float(bt.get("initial_equity", 10_000_000))
    return {"v": VERSION, "start": start, "equity0": eq0,
            "rules": {"max_positions": int(bt["max_positions"]), "risk_per_trade": float(bt.get("risk_per_trade", 0.01)),
                      "max_weight": float(bt.get("max_weight", 0.2)), "dd_brake": bt.get("dd_brake"),
                      "fee_buy": float(cfg["idx_rules"]["fee_buy"]), "fee_sell": float(cfg["idx_rules"]["fee_sell"]),
                      "lot": int(cfg["idx_rules"]["lot_size"]), "exposure": cfg["regime_exposure"]},
            "days": [], "pf": {"cash": eq0, "peak": eq0, "pos": {}, "pend_buy": [], "pend_sell": {}, "trades": [], "eq": []}}


def record_from_snapshot(stocks, d, gate_open, ihsg, reg_label, held_pf):
    """Baris hari ini dari sinyal yang benar-benar tampil di dashboard."""
    def row(s):
        return {"t": s["ticker"], "sig": s["signal"], "c": s["last"], "sl": s["levels"].get("sl"), "tp1": s["levels"].get("tp1"),
                "comp": s["scores"].get("composite"), "flow": s["scores"].get("flow"), "mom": s["scores"].get("momentum")}
    buy = [row(s) for s in stocks if s["signal"] in ("BUY", "STRONG BUY")]
    held = [row(s) for s in stocks if any("DITAHAN" in n for n in s.get("notes", []))]
    ex = [s["ticker"] for s in stocks if s["ticker"] in held_pf and s["signal"] == "EXIT"]
    buy.sort(key=lambda r: (r["sig"] != "STRONG BUY", -(r["comp"] or 0)))
    held.sort(key=lambda r: -(r["comp"] or 0))
    return {"d": d, "gate": bool(gate_open), "ihsg": _f(ihsg, 2), "reg": reg_label, "buy": buy, "held": held, "exit": ex}


def _step(T, row, F, i):
    """Proses satu hari bursa (indeks i di panel harga) untuk portofolio kertas."""
    R, pf = T["rules"], T["pf"]
    C, O, H, L, V, CH = F["c"], F["o"], F["h"], F["l"], F["v"], F["chandelier"]
    d = C.index[i]
    fb, fs, lot = R["fee_buy"], R["fee_sell"], R["lot"]

    def px(df, t):
        try:
            v = float(df.iloc[i][t])
            return v if np.isfinite(v) and v > 0 else None
        except (KeyError, ValueError, TypeError):
            return None

    # 1) eksekusi order dari hari sebelumnya di harga OPEN hari ini
    for t, why in list(pf["pend_sell"].items()):
        p = pf["pos"].get(t)
        o = px(O, t)
        if p is None:
            pf["pend_sell"].pop(t)
            continue
        if o is None or (px(V, t) or 0) <= 0:
            continue                                  # tidak ada transaksi / suspensi -> coba lagi besok
        pf["pend_sell"].pop(t)
        got, cost = p["sh"] * o * (1 - fs), p["sh"] * p["entry"] * (1 + fb)
        pf["cash"] += got
        pf["trades"].append({"t": t, "d0": p["d0"], "d1": d.strftime("%Y-%m-%d"), "entry": p["entry"], "exit": o, "sh": p["sh"],
                             "pl": round(got - cost), "ret": round(got / cost - 1, 4), "r": round((o - p["entry"]) / p["R0"], 2) if p["R0"] else None,
                             "why": why})
        pf["pos"].pop(t)
    eq_open = pf["cash"] + sum(p["sh"] * (px(O, t) or p["last"]) for t, p in pf["pos"].items())
    for b in pf["pend_buy"]:
        t = b["t"]
        if t in pf["pos"] or len(pf["pos"]) >= R["max_positions"]:
            continue
        o, prev = px(O, t), b["c"]
        stop = b.get("sl")
        if o is None or not stop or o <= stop or (px(V, t) or 0) <= 0:
            continue
        if prev and o >= prev * (1 + ara_pct(prev) - 0.01):
            continue                                  # dibuka di batas ARA: antrean beli tidak kebagian
        sh = min(eq_open * R["risk_per_trade"] / (o - stop), eq_open * R["max_weight"] / o, pf["cash"] / (o * (1 + fb)))
        sh = math.floor(sh / lot) * lot
        if sh <= 0:
            continue
        pf["cash"] -= sh * o * (1 + fb)
        pf["pos"][t] = {"sh": sh, "entry": o, "d0": d.strftime("%Y-%m-%d"), "stop": stop, "R0": o - stop, "last": o}
    pf["pend_buy"] = []

    # 2) nilai di harga close + trailing stop
    eq = pf["cash"]
    for t, p in pf["pos"].items():
        c = px(C, t) or p["last"]
        p["last"] = c
        eq += p["sh"] * c
        tr = px(CH, t)
        if tr:
            p["stop"] = max(p["stop"], round_tick(tr, "down"))
    pf["peak"] = max(pf["peak"], eq)
    pf["eq"].append([d.strftime("%Y-%m-%d"), round(eq), row.get("ihsg")])

    # 3) sinyal di close -> order besok
    for t, p in pf["pos"].items():
        if t in pf["pend_sell"]:
            continue
        if p["last"] <= p["stop"]:
            pf["pend_sell"][t] = "stop (close)"
        elif t in row.get("exit", []):
            pf["pend_sell"][t] = "sinyal exit"
    target = int(round(R["max_positions"] * float(R["exposure"].get(row.get("reg"), 0.7))))
    if R.get("dd_brake") and eq / pf["peak"] - 1 < -float(R["dd_brake"]):
        target = max(1, target // 2)
    slots = target - (len(pf["pos"]) - sum(1 for t in pf["pend_sell"] if t in pf["pos"]))
    if slots > 0:
        pf["pend_buy"] = [{"t": b["t"], "c": b["c"], "sl": b["sl"]} for b in row["buy"] if b["t"] not in pf["pos"]][:slots]


def update(path, stocks, F, gate_open, ihsg, reg_label, cfg, now, demo_rows=None) -> dict | None:
    """Catat hari bursa terakhir yang sudah selesai (sekali saja), proses portofolio kertas, kembalikan data untuk situs."""
    T = load(path) if demo_rows is None else {}
    C = F["c"]
    last = C.index[-1]
    today = pd.Timestamp(now.date())
    done = last < today or (last == today and now.hour * 60 + now.minute >= 16 * 60)
    if demo_rows is not None:
        T = _new(cfg, demo_rows[0]["d"])
        for row in demo_rows:
            T["days"].append(row)
            _step(T, row, F, C.index.get_loc(pd.Timestamp(row["d"])))
    elif done:
        d = last.strftime("%Y-%m-%d")
        if not T:
            T = _new(cfg, d)
            log.info("Track record dimulai %s", d)
        if not T["days"] or T["days"][-1]["d"] < d:
            row = record_from_snapshot(stocks, d, gate_open, ihsg, reg_label, set(T["pf"]["pos"]))
            T["days"].append(row)
            _step(T, row, F, len(C.index) - 1)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(T, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            log.info("Track record %s dicatat: %d BUY, %d ditahan, gerbang %s | portofolio kertas %d posisi, ekuitas Rp%s",
                     d, len(row["buy"]), len(row["held"]), "terbuka" if row["gate"] else "tertutup", len(T["pf"]["pos"]),
                     f"{T['pf']['eq'][-1][1]:,}")
    if not T:
        return None
    return public(T, F)


def _fwd(rows, F, key):
    """Return maju (5 & 20 hari bursa) dari close hari sinyal, dan selisihnya dengan IHSG."""
    C = F["c"]
    idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(C.index)}
    ih = {r["d"]: r["ihsg"] for r in rows}
    ihs = pd.Series(ih)
    out = {5: [], 20: []}
    prev = set()
    for r in rows:
        i = idx.get(r["d"])
        cur = {s["t"] for s in r[key]}
        new = [s for s in r[key] if s["t"] not in prev]      # hanya hari pertama sinyal muncul (hindari hitung ganda)
        prev = cur
        if i is None:
            continue
        for s in new:
            for h in (5, 20):
                if i + h < len(C.index) and s["t"] in C.columns:
                    c1 = C.iloc[i + h][s["t"]]
                    if np.isfinite(c1) and s["c"]:
                        d1 = C.index[i + h].strftime("%Y-%m-%d")
                        ib = ih.get(d1) if d1 in ih else None
                        ex = (c1 / s["c"] - 1) - (ib / r["ihsg"] - 1) if ib and r.get("ihsg") else None
                        out[h].append((c1 / s["c"] - 1, ex))
    res = {}
    for h, v in out.items():
        if v:
            r = np.array([x[0] for x in v])
            e = [x[1] for x in v if x[1] is not None]
            res[str(h)] = {"n": len(v), "avg": _f(r.mean(), 4), "med": _f(np.median(r), 4), "win": _f((r > 0).mean(), 3),
                           "ex": _f(np.mean(e), 4) if e else None}
    return res


def public(T, F) -> dict:
    pf = T["pf"]
    C = F["c"]
    pos = []
    for t, p in pf["pos"].items():
        pos.append({"t": t, "sh": p["sh"], "entry": p["entry"], "d0": p["d0"], "stop": p["stop"], "last": p["last"],
                    "ret": _f(p["last"] / p["entry"] - 1, 4), "pend": pf["pend_sell"].get(t)})
    days = T["days"]
    return {"start": T["start"], "equity0": T["equity0"], "rules": T["rules"], "n_days": len(days),
            "eq": pf["eq"], "cash": round(pf["cash"]), "pos": pos, "pend_buy": [b["t"] for b in pf["pend_buy"]],
            "trades": pf["trades"][-200:], "days": days[-120:],
            "fwd": {"buy": _fwd(days, F, "buy"), "held": _fwd(days, F, "held")}}


def demo_rows(F, comp, cond, reg, cfg, ndays=45):
    """Mode demo: catatan sinyal buatan dari aturan model di 45 hari terakhir data simulasi."""
    C, A = F["c"], F["atr14"]
    m = float(cfg["signal"]["atr_stop_mult"])
    rows = []
    gate = cond.get("gate")
    for i in range(len(C.index) - ndays, len(C.index)):
        d = C.index[i]
        g = bool(gate.iloc[i]) if gate is not None else True

        def mk(t, sig):
            c, a = float(C.iloc[i][t]), float(A.iloc[i][t])
            return {"t": t, "sig": sig, "c": c, "sl": round_tick(c - m * a, "down"), "tp1": round_tick(c + 1.5 * m * a, "up"),
                    "comp": _f(comp.iloc[i][t], 1), "flow": None, "mom": None}
        e = cond["entry"].iloc[i]
        buy = [mk(t, "STRONG BUY" if cond["strong"].iloc[i][t] else "BUY") for t in e[e].index]
        raw = cond.get("entry_raw")
        held = [mk(t, "HOLD") for t in (raw.iloc[i][raw.iloc[i] & ~e].index if raw is not None and not g else [])]
        ex = cond["exit"].iloc[i]
        buy.sort(key=lambda r: (r["sig"] != "STRONG BUY", -(r["comp"] or 0)))
        rows.append({"d": d.strftime("%Y-%m-%d"), "gate": g, "ihsg": _f(reg["ihsg"].iloc[i], 2), "reg": reg["label"].iloc[i],
                     "buy": buy, "held": held, "exit": list(ex[ex].index)})
    return rows
