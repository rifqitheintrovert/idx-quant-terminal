"""Probabilitas arah harga — dihitung dari kejadian historis saham BEI, bukan tebakan.

Untuk tiap saham likuid pada tiap hari, model logistik membaca kondisi yang SUDAH diketahui hari itu
(skor momentum, inflow, tren, RSI, volatilitas, jarak ke MA50, return 5/20 hari, kondisi pasar) lalu
memperkirakan:
  up5 / up20 / up60  = peluang harga penutupan h hari bursa ke depan LEBIH TINGGI dari hari ini
  tp1 / tp2          = peluang harga menyentuh target 1 / target 2 rencana trade SEBELUM menyentuh stop loss
                       (dalam 60 hari bursa; bila target & stop tersentuh di hari yang sama dihitung kena stop)
Dilatih pada semua saham likuid ±10 tahun (sampel tiap 3 hari). Hari-hari terakhir yang hasilnya belum
diketahui otomatis tidak ikut dilatih.

Uji kejujuran: `python -m engine.prob --cache .cache/panels.pkl` = walk-forward per tahun (model hanya
melihat data sebelum tahun itu), melaporkan AUC, Brier skill vs tebakan rata-rata, dan tabel kalibrasi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATS = ["mom", "flow", "trend", "rsi", "atr", "d50", "r5", "r20", "vr", "mkt", "brd"]
HORIZONS = (5, 20, 60)
TP_WINDOW = 60


def _ff(F: dict, reg: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """Fitur panel (tanggal × saham), sudah dipotong ekstremnya."""
    c = F["c"]
    atrp = (F["atr14"] / c).clip(0, 0.2)
    X = {"mom": F["s_mom"] / 100, "flow": F["s_flow"] / 100, "trend": F["s_trend"] / 100,
         "rsi": F["rsi14"] / 100, "atr": atrp * 10,
         "d50": (c / F["ma50"] - 1).clip(-0.5, 0.5) * 2,
         "r5": (c / c.shift(5) - 1).clip(-0.4, 0.4) * 2.5,
         "r20": (c / c.shift(20) - 1).clip(-0.6, 0.6) * 1.6,
         "vr": np.log(F["volratio"].clip(0.1, 10)) / 2}
    if reg is not None and "score" in reg:
        m = (reg["score"].reindex(c.index).astype(float) / 100).fillna(0.5)
        b = reg["breadth"].reindex(c.index).astype(float).fillna(0.5) if "breadth" in reg else m * 0 + 0.5
    else:
        m = pd.Series(0.5, index=c.index)
        b = m.copy()
    X["mkt"] = pd.DataFrame(np.repeat(m.values[:, None], c.shape[1], 1), index=c.index, columns=c.columns)
    X["brd"] = pd.DataFrame(np.repeat(b.values[:, None], c.shape[1], 1), index=c.index, columns=c.columns)
    return X


def _targets(F: dict, cfg: dict) -> dict[str, pd.DataFrame]:
    c, h, l = F["c"].values, F["h"].values, F["l"].values
    T, N = c.shape
    Y = {}
    for k in HORIZONS:
        y = np.full((T, N), np.nan)
        y[:-k] = (c[k:] > c[:-k]).astype(float)
        y[:-k][np.isnan(c[k:]) | np.isnan(c[:-k])] = np.nan
        Y[f"up{k}"] = y
    s = cfg["signal"]
    atr = F["atr14"].values
    R = np.maximum(s["atr_stop_mult"] * atr, 1e-9)
    sl = c - R
    for name, mult in (("tp1", float(s["tp1_r"])), ("tp2", float(s["tp2_r"]))):
        tp = c + mult * R
        res = np.full((T, N), np.nan)
        done = np.zeros((T, N), bool)
        hit = np.zeros((T, N))
        for d in range(1, TP_WINDOW + 1):          # jalan maju hari demi hari, vektor atas semua (t, saham)
            hh = np.full((T, N), np.nan)
            ll = np.full((T, N), np.nan)
            hh[:-d], ll[:-d] = h[d:], l[d:]
            stop = ~done & (ll <= sl)
            win = ~done & ~stop & (hh >= tp)
            hit[win] = 1
            done |= stop | win
        res[:] = hit
        res[~done] = 0                              # tidak kena target dalam 60 hari = tidak berhasil
        res[-TP_WINDOW:] = np.nan                   # belum diketahui
        res[np.isnan(c) | np.isnan(atr)] = np.nan
        Y[name] = res
    return Y


def _stack(X: dict, mask: np.ndarray, rows: np.ndarray) -> np.ndarray:
    return np.column_stack([X[f].values[rows][mask] for f in FEATS])


def _fit(Xm: np.ndarray, y: np.ndarray, lam: float = 1.0, it: int = 25) -> np.ndarray:
    """Regresi logistik (Newton / IRLS) dengan penalti L2 kecil; kolom pertama = intersep."""
    A = np.column_stack([np.ones(len(Xm)), Xm])
    w = np.zeros(A.shape[1])
    P = np.eye(A.shape[1]) * lam
    P[0, 0] = 0
    for _ in range(it):
        z = np.clip(A @ w, -30, 30)
        p = 1 / (1 + np.exp(-z))
        g = A.T @ (p - y) + P @ w
        Hm = (A * (p * (1 - p))[:, None]).T @ A + P
        step = np.linalg.solve(Hm, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def _pred(w: np.ndarray, Xm: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(w[0] + Xm @ w[1:], -30, 30)))


def _auc(p, y):
    o = np.argsort(p)
    r = np.empty(len(p))
    r[o] = np.arange(1, len(p) + 1)
    n1 = y.sum()
    n0 = len(y) - n1
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0) if n1 and n0 else np.nan


def _valid(X, liq):
    ok = liq.copy()
    for f in FEATS:
        ok &= np.isfinite(X[f].values)
    return ok


def fit_latest(F: dict, cfg: dict, reg: pd.DataFrame | None = None, step: int = 3) -> dict:
    """Latih semua model pada seluruh histori yang hasilnya sudah diketahui, lalu nilai hari terakhir.
    Return {ticker: {up5, up20, up60, tp1, tp2}} + meta (rata-rata dasar per target)."""
    X = _ff(F, reg)
    Y = _targets(F, cfg)
    liq = F["liquid"].fillna(False).values.astype(bool)
    ok = _valid(X, liq)
    T = len(F["c"])
    rows = np.arange(0, T, step)
    last = np.array([T - 1])
    Xl = np.column_stack([X[f].values[last][0] for f in FEATS])
    okl = np.isfinite(Xl).all(axis=1)
    out = {t: {} for t in F["c"].columns[okl]}
    meta = {}
    for name, y in Y.items():
        m = ok[rows] & np.isfinite(y[rows])
        if m.sum() < 5000:
            continue
        Xm = _stack(X, m, rows)
        yy = y[rows][m]
        w = _fit(Xm, yy)
        p = _pred(w, Xl[okl])
        for t, v in zip(F["c"].columns[okl], p):
            out[t][name] = round(float(v), 3)
        meta[name] = {"base": round(float(yy.mean()), 3), "n": int(m.sum())}
    return {"stocks": out, "meta": meta}


def research(F: dict, cfg: dict, reg: pd.DataFrame | None, log=print, step: int = 3, start_year: int | None = None):
    """Walk-forward per tahun: latih pada tahun-tahun sebelumnya (dengan jeda), uji di tahun itu."""
    X = _ff(F, reg)
    Y = _targets(F, cfg)
    liq = F["liquid"].fillna(False).values.astype(bool)
    ok = _valid(X, liq)
    idx = F["c"].index
    rows = np.arange(0, len(idx), step)
    years = sorted(set(idx[rows].year))
    y0 = start_year or years[min(3, len(years) - 1)]
    summary = {}
    for name, y in Y.items():
        gap = int(name[2:]) if name.startswith("up") else TP_WINDOW
        P, YY, YR = [], [], []
        for yr in [v for v in years if v >= y0]:
            te = rows[idx[rows].year == yr]
            cut = idx[te[0]] if len(te) else None
            if cut is None:
                continue
            tr = rows[rows < max(te[0] - gap, 0)]
            mtr = ok[tr] & np.isfinite(y[tr])
            mte = ok[te] & np.isfinite(y[te])
            if mtr.sum() < 5000 or mte.sum() < 200:
                continue
            w = _fit(_stack(X, mtr, tr), y[tr][mtr])
            P.append(_pred(w, _stack(X, mte, te)))
            YY.append(y[te][mte])
            YR.append(np.full(mte.sum(), yr))
        if not P:
            continue
        p, yv, yr = np.concatenate(P), np.concatenate(YY), np.concatenate(YR)
        base = yv.mean()
        bs, bs0 = np.mean((p - yv) ** 2), np.mean((base - yv) ** 2)
        auc = _auc(p, yv)
        per = {int(v): round(_auc(p[yr == v], yv[yr == v]), 3) for v in sorted(set(yr))}
        log(f"== {name}: n={len(yv)} | rata-rata dasar {base*100:.1f}% | AUC {auc:.3f} | Brier skill {(1-bs/bs0)*100:+.1f}% | AUC per tahun {per}")
        q = np.quantile(p, np.linspace(0, 1, 11))
        for i in range(10):
            mm = (p >= q[i]) & (p <= q[i + 1]) if i == 9 else (p >= q[i]) & (p < q[i + 1])
            if mm.sum():
                log(f"   desil {i+1:2d}: prediksi {p[mm].mean()*100:5.1f}% -> kenyataan {yv[mm].mean()*100:5.1f}%  (n={mm.sum()})")
        w = _fit(_stack(X, ok[rows] & np.isfinite(y[rows]), rows), y[rows][ok[rows] & np.isfinite(y[rows])])
        log("   bobot (data penuh): " + ", ".join(f"{f} {v:+.2f}" for f, v in zip(["const"] + FEATS, w)))
        summary[name] = {"auc": auc, "bss": 1 - bs / bs0, "base": base, "per": per,
                         "top": float(yv[p >= q[9]].mean()), "bot": float(yv[p <= q[1]].mean())}
    return summary


def main(argv=None):
    import argparse
    from datetime import datetime
    from pathlib import Path

    import yaml

    from . import data, features, regime
    from . import universe as uni_mod
    from .idx_rules import WIB
    from .run import hist_start

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.yaml"))
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    now = datetime.now(WIB)
    cache = data.load_cache(a.cache)
    universe, _, _ = uni_mod.load(cfg, refresh=False)
    cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
    frames = {t: f for t, f in cache["frames"].items() if t in universe and len(f) and f.index[-1] >= cutoff}
    F = features.compute(data.build_panels(frames, list(frames)), cfg)
    got = data.fetch_yahoo([cfg["macro"]["IHSG"], cfg["macro"]["USDIDR"]], hist_start(cfg, now))
    ih = got[cfg["macro"]["IHSG"]]["Close"] if got.get(cfg["macro"]["IHSG"]) is not None else (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    reg = regime.compute(ih, F, got[cfg["macro"]["USDIDR"]]["Close"] if got.get(cfg["macro"]["USDIDR"]) is not None else None)

    def P(*x):
        print("PRB|", *x, flush=True)
    P(f"DATA {F['c'].shape[1]} saham, {F['c'].index[0].date()} s/d {F['c'].index[-1].date()}")
    research(F, cfg, reg, log=P)
    r = fit_latest(F, cfg, reg)
    P("META", r["meta"])
    s = sorted(r["stocks"].items(), key=lambda kv: -kv[1].get("up20", 0))
    P("contoh tertinggi up20:", [(t, v) for t, v in s[:5]])
    P("contoh terendah up20:", [(t, v) for t, v in s[-5:]])
    P("SELESAI")


if __name__ == "__main__":
    main()
