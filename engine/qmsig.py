"""Riset: SIGNAL dari quantitative model (skor QM) vs model sinyal sekarang — portofolio Rp10 jt, ±10 tahun.

    python -m engine.qmsig --cache .cache/panels.pkl        (workflow "Uji Sinyal QM")

Skor QM harian = jumlah vonis 14 model ringkasan QM (titik-waktu, engine/stkbt.qm_panel) untuk SEMUA saham yang
pernah likuid (tanpa bias saham yang bertahan). Varian sinyal QM: masuk saat skor > 0 / ≥ 2 / ≥ 3, dengan/tanpa
gerbang IHSG > MA200, dengan/tanpa batas minimum "tidak ada model Negatif"; keluar saat skor < 0 (ditambah stop
trailing bawaan mesin backtest). Urutan kandidat = skor QM (seri dipecah dengan likuiditas).
Diganti hanya bila lebih baik dari model sekarang di KEDUA paruh data. Hasil: site/data/qmsig.json (panel F6 BTEST).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest
from .flowmom import kpi, pc
from .stkbt import KEYS, ROOT, qm_panel, setup


def P(*a):
    print("QSG|", *a, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args(argv)
    ctx = setup(a.demo, a.cache)
    F, cfg, reg, comp, cond, ih, liq, idx = (ctx[k] for k in ("F", "cfg", "reg", "comp", "cond", "ih", "liq", "idx"))
    T = [t for t in F["c"].columns if int(liq[t].sum()) >= 120]
    P(f"saham yang pernah likuid ≥ 120 hari: {len(T)}")
    Q = qm_panel(ctx, T)
    S = pd.DataFrame(Q["S"], index=idx, columns=T).reindex(columns=F["c"].columns)
    neg = pd.DataFrame(sum((Q["V"][k] == -1).astype(int) for k in KEYS), index=idx, columns=T).reindex(columns=F["c"].columns).fillna(0)
    L = liq.reindex_like(S).fillna(False)
    gate = (ih > ih.rolling(200).mean()).reindex(idx).fillna(False)
    G = pd.DataFrame(np.repeat(gate.values[:, None], S.shape[1], 1), index=idx, columns=S.columns)
    tie = F["avg_val60"].reindex_like(S).rank(axis=1, pct=True).fillna(0) if "avg_val60" in F else 0
    cq = S.fillna(-99) * 10 + tie

    def run(c2, cp):
        _, det = backtest.run(F, cp, c2, reg, cfg, detail=True)
        return kpi(det["df"], len(det["trades"]))

    q0 = run(cond, comp)
    out = {"base": None, "variants": [], "meta": {}}

    def pack(q):
        return {"cagr": round(q["cagr"], 4), "mdd": round(q["mdd"], 4), "calmar": round(q["calmar"], 3), "sharpe": round(q["sharpe"], 3),
                "h": [round(x[2], 3) for x in q["h"]], "hc": [round(x[0], 4) for x in q["h"]], "tpy": round(q["tpy"], 1), "final": round(q["final"])}

    def line(lab, q):
        P(f"{lab:48s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | "
          f"paruh Calmar {q['h'][0][2]:.2f}/{q['h'][1][2]:.2f} | trade/thn {q['tpy']:.0f} | akhir Rp{q['final']:,.0f}")
    line("MODEL SINYAL SEKARANG (momentum + flow)", q0)
    out["base"] = pack(q0)
    VAR = [("QM > 0", 1, False, False), ("QM > 0 + gerbang MA200", 1, True, False), ("QM ≥ 2 + gerbang", 2, True, False),
           ("QM ≥ 3 + gerbang", 3, True, False), ("QM ≥ 4 + gerbang", 4, True, False),
           ("QM > 0 + gerbang + tanpa model Negatif", 1, True, True), ("QM ≥ 2 + gerbang + tanpa model Negatif", 2, True, True)]
    for lab, thr, use_gate, no_neg in VAR:
        ent = L & (S >= thr)
        if use_gate:
            ent &= G
        if no_neg:
            ent &= neg == 0
        ext = (S < 0) | (neg > 0 if no_neg else False)
        c2 = {"entry": ent.fillna(False), "strong": ent.fillna(False) & (S >= thr + 2), "exit": ext.fillna(False) & ~ent.fillna(False)}
        q = run(c2, cq)
        both = q["h"][0][2] > q0["h"][0][2] and q["h"][1][2] > q0["h"][1][2]
        line(f"[{lab}]{' LEBIH BAIK di kedua paruh' if both else ''}", q)
        out["variants"].append({"label": lab, "thr": thr, "gate": use_gate, "noneg": no_neg, **pack(q), "both": bool(both),
                                "sig_day": round(float(ent.sum(axis=1).mean()), 1)})
    best = max(out["variants"], key=lambda v: v["calmar"])
    win = [v for v in out["variants"] if v["both"]]
    out["meta"] = {"n_stocks": len(T), "start": str(idx[0].date()), "end": str(idx[-1].date()), "equity": float(cfg["backtest"].get("initial_equity", 1e7)),
                   "decision": "GANTI" if win else "TETAP", "best": best["label"], "demo": bool(a.demo)}
    P(f"KEPUTUSAN: {'ada varian QM lebih baik di kedua paruh: ' + ', '.join(v['label'] for v in win) if win else 'TIDAK ADA varian QM yang lebih baik dari model sekarang di kedua paruh -> SIGNAL tetap'}")
    Path(ROOT / "site" / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "site" / "data" / "qmsig.json").write_text(json.dumps(out))
    P("JSON " + json.dumps(out))
    P(f"SELESAI {(time.time() - ctx['T0']) / 60:.1f} menit")


if __name__ == "__main__":
    main()
