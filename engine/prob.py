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

FEATS_ALL = ["mom", "flow", "trend", "rsi", "atr", "d50", "r5", "r20", "vr", "mkt", "brd"]
FEATS = ["mom", "flow", "trend", "rsi", "atr", "d50", "r5", "r20", "vr"]     # tanpa fitur pasar (koefisiennya berbalik tiap rezim)
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
        stp = np.zeros((T, N))
        for d in range(1, TP_WINDOW + 1):          # jalan maju hari demi hari, vektor atas semua (t, saham)
            hh = np.full((T, N), np.nan)
            ll = np.full((T, N), np.nan)
            hh[:-d], ll[:-d] = h[d:], l[d:]
            stop = ~done & (ll <= sl)
            win = ~done & ~stop & (hh >= tp)
            hit[win] = 1
            stp[stop] = 1
            done |= stop | win
        bad = np.isnan(c) | np.isnan(atr)
        res[:] = hit                                # tidak kena target dalam 60 hari = 0
        res[-TP_WINDOW:] = np.nan                   # belum diketahui
        res[bad] = np.nan
        Y[name] = res
        sv = stp.copy()                             # kena stop lebih dulu (sebelum target ini)
        sv[-TP_WINDOW:] = np.nan
        sv[bad] = np.nan
        Y["sl" + name[-1]] = sv
    return Y


def _stack(X: dict, mask: np.ndarray, rows: np.ndarray, feats=None) -> np.ndarray:
    return np.column_stack([X[f].values[rows][mask] for f in (feats or FEATS)])


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


def _valid(X, liq, feats=None):
    ok = liq.copy()
    for f in (feats or FEATS):
        ok &= np.isfinite(X[f].values)
    return ok


def fit_latest(F: dict, cfg: dict, reg: pd.DataFrame | None = None, step: int = 3, calib_years: int = 6) -> dict:
    """Latih pada seluruh histori yang hasilnya sudah diketahui, nilai hari terakhir, lalu KALIBRASI:
    skor model dipetakan ke frekuensi nyata per desil dari prediksi out-of-sample beberapa tahun terakhir.
    Return {"stocks": {ticker: {up5, up20, up60, tp1, tp2}}, "meta": {target: {base, n, lo, hi}}}."""
    X = _ff(F, reg)
    Y = _targets(F, cfg)
    liq = F["liquid"].fillna(False).values.astype(bool)
    ok = _valid(X, liq)
    idx = F["c"].index
    T = len(idx)
    rows = np.arange(0, T, step)
    y0 = max(idx[0].year + 3, idx[-1].year - calib_years)
    Xl = np.column_stack([X[f].values[-1] for f in FEATS])
    okl = np.isfinite(Xl).all(axis=1) & liq[-1]
    cols = F["c"].columns[okl]
    out = {t: {} for t in cols}
    meta = {}
    for name, y in Y.items():
        gap = int(name[2:]) if name.startswith("up") else TP_WINDOW
        m = ok[rows] & np.isfinite(y[rows])
        if m.sum() < 5000:
            continue
        w = _fit(_stack(X, m, rows), y[rows][m])
        raw = _pred(w, Xl[okl])
        r = _walk(X, y, ok, rows, idx, gap, FEATS, y0)
        if r is None:
            continue
        qr = _calib_map(r[0], r[1])
        p = _apply_map(qr, raw)
        for t, v in zip(cols, p):
            out[t][name] = round(float(v), 3)
        meta[name] = {"base": round(float(r[1].mean()), 3), "n": int(len(r[1])),
                      "lo": round(float(np.nanmin(qr[1])), 3), "hi": round(float(np.nanmax(qr[1])), 3)}
    return {"stocks": out, "meta": meta}


STATES = [("strong", "STRONG BUY"), ("buy", "BUY"), ("none", "Tanpa sinyal (HOLD/REDUCE)"), ("exit", "EXIT"), ("all", "Semua saham likuid")]
LIVE2STATE = {"STRONG BUY": "strong", "BUY": "buy", "HOLD": "none", "REDUCE": "none", "EXIT": "exit"}


def by_state(F: dict, cond: dict, cfg: dict) -> dict:
    """Frekuensi historis per kondisi sinyal (aturan yang sama dengan backtest), semua hari, semua saham likuid.
    Angka ini 'terkalibrasi' dengan sendirinya: persis berapa kali kejadian serupa berakhir naik / kena target."""
    Y = _targets(F, cfg)
    c = F["c"].values
    liq = F["liquid"].fillna(False).values.astype(bool)
    strong = cond["strong"].fillna(False).values.astype(bool) & liq
    entry = cond["entry"].fillna(False).values.astype(bool) & liq
    ext = cond["exit"].fillna(False).values.astype(bool) & liq & ~entry
    masks = {"strong": strong, "buy": entry & ~strong, "exit": ext, "none": liq & ~entry & ~ext, "all": liq}
    fr = {}
    for k in (20, 60):
        r = np.full(c.shape, np.nan)
        r[:-k] = c[k:] / c[:-k] - 1
        fr[k] = r
    years = F["c"].index.year.values
    out = {}
    for key, label in STATES:
        m = masks[key]
        row = {"label": label}
        for name, y in Y.items():
            mm = m & np.isfinite(y)
            n = int(mm.sum())
            if n < 30:
                continue
            row[name] = round(float(y[mm].mean()), 3)
            row["n"] = max(row.get("n", 0), n)
            if key != "all":        # stabil? berapa tahun tingkatnya di atas rata-rata semua saham
                base = masks["all"] & np.isfinite(y)
                yrs = [v for v in np.unique(years) if (mm[years == v]).sum() >= 20]
                row.setdefault("yrs", {})[name] = [sum(1 for v in yrs if y[years == v][mm[years == v]].mean() >
                                                       y[years == v][base[years == v]].mean()), len(yrs)]
        for k, r in fr.items():
            mm = m & np.isfinite(r)
            if mm.sum() >= 30:
                v = np.clip(r[mm], -0.95, 5)
                row[f"r{k}"] = round(float(np.mean(v)), 4)
                row[f"m{k}"] = round(float(np.median(v)), 4)
        out[key] = row
    s = cfg["signal"]
    return {"states": out, "since": str(F["c"].index[0].date()), "window": TP_WINDOW,
            "plan": {"sl_atr": s["atr_stop_mult"], "tp1_r": s["tp1_r"], "tp2_r": s["tp2_r"]}}


def _walk(X, y, ok, rows, idx, gap, feats, y0):
    """Prediksi out-of-sample per tahun (latih hanya pada data sebelum tahun itu, dengan jeda `gap` hari)."""
    years = sorted(set(idx[rows].year))
    P, YY, YR = [], [], []
    for yr in [v for v in years if v >= y0]:
        te = rows[idx[rows].year == yr]
        if not len(te):
            continue
        tr = rows[rows < max(te[0] - gap, 0)]
        mtr = ok[tr] & np.isfinite(y[tr])
        mte = ok[te] & np.isfinite(y[te])
        if mtr.sum() < 5000 or mte.sum() < 200:
            continue
        w = _fit(_stack(X, mtr, tr, feats), y[tr][mtr])
        P.append(_pred(w, _stack(X, mte, te, feats)))
        YY.append(y[te][mte])
        YR.append(np.full(mte.sum(), yr))
    if not P:
        return None
    return np.concatenate(P), np.concatenate(YY), np.concatenate(YR)


def _calib_map(p, y, nb=10):
    """Peta desil skor -> frekuensi nyata (dari prediksi out-of-sample)."""
    q = np.quantile(p, np.linspace(0, 1, nb + 1))
    b = np.clip(np.searchsorted(q[1:-1], p, side="right"), 0, nb - 1)
    rate = np.array([y[b == i].mean() if (b == i).any() else np.nan for i in range(nb)])
    return q, rate


def _apply_map(qr, p):
    q, rate = qr
    return rate[np.clip(np.searchsorted(q[1:-1], p, side="right"), 0, len(rate) - 1)]


def _report(name, p, yv, yr, log, tag):
    base = yv.mean()
    bs, bs0 = np.mean((p - yv) ** 2), np.mean((base - yv) ** 2)
    per = {int(v): round(float(_auc(p[yr == v], yv[yr == v])), 3) for v in sorted(set(yr))}
    q = np.quantile(p, [0.1, 0.9])
    log(f"== {name} [{tag}] n={len(yv)} | dasar {base*100:.1f}% | AUC {_auc(p, yv):.3f} | Brier skill {(1-bs/bs0)*100:+.2f}% | "
        f"10% terbawah -> {yv[p <= q[0]].mean()*100:.1f}% naik/berhasil | 10% teratas -> {yv[p >= q[1]].mean()*100:.1f}% | AUC/thn {per}")


def research(F: dict, cfg: dict, reg: pd.DataFrame | None, log=print, step: int = 3, start_year: int | None = None, entry=None):
    """Walk-forward per tahun + kalibrasi bertingkat (peta desil dari tahun-tahun sebelumnya saja)."""
    X = _ff(F, reg)
    Y = _targets(F, cfg)
    liq = F["liquid"].fillna(False).values.astype(bool)
    idx = F["c"].index
    rows = np.arange(0, len(idx), step)
    years = sorted(set(idx[rows].year))
    y0 = start_year or years[min(3, len(years) - 1)]
    for name, y in Y.items():
        gap = int(name[2:]) if name.startswith("up") else TP_WINDOW
        for tag, feats in (("tanpa fitur pasar", FEATS), ("dengan fitur pasar", FEATS_ALL)):
            ok = _valid(X, liq, feats)
            r = _walk(X, y, ok, rows, idx, gap, feats, y0)
            if r is None:
                continue
            p, yv, yr = r
            _report(name, p, yv, yr, log, tag + ", mentah")
            # kalibrasi bertingkat: tahun Y memakai peta desil dari prediksi OOS tahun < Y
            pc, yc, rc = [], [], []
            for v in sorted(set(yr))[2:]:
                m0, m1 = yr < v, yr == v
                pc.append(_apply_map(_calib_map(p[m0], yv[m0]), p[m1]))
                yc.append(yv[m1])
                rc.append(yr[m1])
            if pc:
                pcc, ycc, rcc = np.concatenate(pc), np.concatenate(yc), np.concatenate(rc)
                _report(name, pcc, ycc, rcc, log, tag + ", terkalibrasi")
                if tag == "tanpa fitur pasar":
                    q, rate = _calib_map(pcc, ycc)
                    log("   kalibrasi (prediksi terkalibrasi -> kenyataan per desil): " +
                        " | ".join(f"{a*100:.0f}->{b*100:.0f}" for a, b in zip(
                            [pcc[(pcc >= q[i]) & (pcc <= q[i + 1])].mean() for i in range(10)], rate)))
        if entry is not None:       # hari ketika sinyal BELI model muncul
            e = entry.values.astype(bool)
            m = e[rows] & np.isfinite(y[rows]) & liq[rows]
            m2 = np.isfinite(y[rows]) & liq[rows]
            log(f"   saat sinyal BELI: {y[rows][m].mean()*100:.1f}% (n={m.sum()}) vs semua saham likuid {y[rows][m2].mean()*100:.1f}%")


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
    from .flowmom import BASE, build, extras
    _, cond = build(extras(F), cfg, reg, BASE)
    research(F, cfg, reg, log=P, entry=cond["entry"])
    r = fit_latest(F, cfg, reg)
    P("META", r["meta"])
    s = sorted(r["stocks"].items(), key=lambda kv: -kv[1].get("up20", 0))
    P("contoh tertinggi up20:", [(t, v) for t, v in s[:5]])
    P("contoh terendah up20:", [(t, v) for t, v in s[-5:]])
    bs = by_state(F, cond, cfg)
    for k, r in bs["states"].items():
        P(f"STATE {r['label']:28s} n={r.get('n')} | naik 5H {r.get('up5',0)*100:.1f}% 20H {r.get('up20',0)*100:.1f}% 60H {r.get('up60',0)*100:.1f}% | "
          f"TP1 dulu {r.get('tp1',0)*100:.1f}% TP2 dulu {r.get('tp2',0)*100:.1f}% | rata2 20H {r.get('r20',0)*100:+.1f}% (median {r.get('m20',0)*100:+.1f}%) "
          f"60H {r.get('r60',0)*100:+.1f}% (median {r.get('m60',0)*100:+.1f}%) | tahun di atas rata-rata {r.get('yrs')}")
    P("SELESAI")


if __name__ == "__main__":
    main()
