"""Volatilitas & GARCH(1,1) per saham — bahan tab MC (Monte Carlo) di dashboard.

GJR-GARCH(1,1):  σ²ₜ = ω + (α + γ·1[εₜ₋₁<0])·ε²ₜ₋₁ + β·σ²ₜ₋₁ ,   ε = return log harian − rata-rata
  - γ > 0 -> efek leverage: hari turun menaikkan volatilitas lebih tinggi daripada hari naik sebesar sama
  - α besar  -> volatilitas cepat bereaksi terhadap guncangan kemarin
  - α+β (persistensi) dekat 1 -> volatilitas tinggi/rendah bertahan lama
  - ω/(1−α−γ/2−β) = varians jangka panjang (volatilitas "normal" saham itu)
Diestimasi dengan quasi-maximum likelihood + variance targeting (ω = varians sampel × (1−α−β)),
dicari serentak untuk semua saham (grid kasar lalu dipersempit) — tanpa scipy.

Residual terstandar z = ε/σ disimpan (±750 hari terakhir) supaya Monte Carlo di browser bisa memakai
"filtered historical simulation": guncangan diambil acak dari z historis saham itu sendiri (ekor gemuk ikut),
lalu diskalakan dengan σ GARCH yang berjalan.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = np.sqrt(250)
LOOKBACK = 1500        # ±6 tahun bursa untuk estimasi
NZ = 750               # residual terstandar yang dikirim ke dashboard


def _nll(r, ok, v0, a, b, g=None):
    """−log-likelihood Gauss (tanpa konstanta) untuk banyak saham sekaligus. r: T×N, a,b,g: N."""
    T, N = r.shape
    g = np.zeros(N) if g is None else g
    w = v0 * (1 - a - g / 2 - b)
    s2 = v0.copy()
    ll = np.zeros(N)
    for t in range(T):
        m = ok[t]
        e2 = r[t] ** 2
        ll += np.where(m, np.log(s2) + e2 / s2, 0.0)
        s2 = np.where(m, w + (a + g * (r[t] < 0)) * e2 + b * s2, s2)
    return ll


def fit(R: pd.DataFrame) -> dict:
    """R: return log harian (tanggal × saham). Return dict per saham {a, b, g, w, v0, mu}."""
    R = R.iloc[-LOOKBACK:]
    ok = R.notna().values & (R.abs().values < 0.35)
    mu = R.where(ok).mean().values
    r = np.nan_to_num(R.values - mu, nan=0.0)
    r[~ok] = 0.0
    n_ok = ok.sum(0)
    v0 = np.where(n_ok > 0, (r ** 2).sum(0) / np.maximum(n_ok, 1), np.nan)
    v0 = np.where(np.isfinite(v0) & (v0 > 0), v0, 1e-4)
    N = r.shape[1]
    best = np.full(N, np.inf)
    ba, bb, bg = np.full(N, 0.05), np.full(N, 0.90), np.zeros(N)
    for a in (0.02, 0.05, 0.08, 0.12, 0.18, 0.25):           # grid kasar (γ = 0)
        for b in (0.55, 0.70, 0.80, 0.86, 0.90, 0.93, 0.96):
            if a + b >= 0.995:
                continue
            ll = _nll(r, ok, v0, np.full(N, a), np.full(N, b))
            m = ll < best
            best[m], ba[m], bb[m] = ll[m], a, b
    for g in (0.03, 0.06, 0.10, 0.15, 0.22):                  # efek leverage: geser sebagian α ke γ
        a = np.clip(ba - g / 2, 0.003, None)
        b = np.minimum(bb, 0.995 - a - g / 2)
        ll = _nll(r, ok, v0, a, b, np.full(N, g))
        m = ll < best
        best[m], ba[m], bb[m], bg[m] = ll[m], a[m], b[m], g
    sa, sb, sg = 0.03, 0.04, 0.04
    for _ in range(4):                                         # persempit di sekitar titik terbaik tiap saham
        ca, cb, cg, cl = ba.copy(), bb.copy(), bg.copy(), best.copy()
        for da in (-1, 0, 1):
            for db in (-1, 0, 1):
                for dg in (-1, 0, 1):
                    if da == 0 and db == 0 and dg == 0:
                        continue
                    a = np.clip(ca + da * sa, 0.003, 0.5)
                    g = np.clip(cg + dg * sg, 0.0, 0.5)
                    b = np.clip(cb + db * sb, 0.0, 0.99)
                    b = np.minimum(b, 0.995 - a - g / 2)
                    ll = _nll(r, ok, v0, a, b, g)
                    m = ll < cl
                    cl[m], ba[m], bb[m], bg[m] = ll[m], a[m], b[m], g[m]
        best = cl
        sa, sb, sg = sa / 2, sb / 2, sg / 2
    out = {}
    for j, t in enumerate(R.columns):
        if n_ok[j] >= 250:
            out[t] = {"a": float(ba[j]), "b": float(bb[j]), "g": float(bg[j]), "v0": float(v0[j]),
                      "w": float(v0[j] * (1 - ba[j] - bg[j] / 2 - bb[j])), "mu": float(mu[j]), "n": int(n_ok[j])}
    return out


def _cond(r, ok, p):
    """Varians kondisional σ²ₜ (prediksi untuk hari t, diketahui di t−1) + σ² untuk besok."""
    s2 = np.empty(len(r) + 1)
    s2[0] = p["v0"]
    for t in range(len(r)):
        s2[t + 1] = p["w"] + (p["a"] + p["g"] * (r[t] < 0)) * r[t] ** 2 + p["b"] * s2[t] if ok[t] else s2[t]
    return s2


def _clean(x):
    """Ganti angka tak hingga / NaN dengan None (JSON ketat), rekursif."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    return x


def build(F: dict, tickers: list[str], nb: int, cfg: dict) -> dict:
    """Ringkasan volatilitas + GARCH untuk tiap ticker -> {ticker: dict} (masuk ke data/s/KODE.json)."""
    from .idx_rules import ara_pct, arb_pct

    c, h, l, o = F["c"][tickers], F["h"][tickers], F["l"][tickers], F["o"][tickers]
    R = np.log(c / c.shift(1))
    P = fit(R)
    ir = cfg.get("idx_rules", {})
    arb_cfg = ir.get("arb_pct")
    if ir.get("arb_valid_until") and str(c.index[-1].date()) > str(ir["arb_valid_until"]):
        arb_cfg = None                                             # ARB asimetris sudah lewat masa berlaku -> simetris
    out = {}
    for t in tickers:
        p = P.get(t)
        if not p:
            continue
        rr = R[t].iloc[-LOOKBACK:]
        okm = rr.notna().values & (rr.abs().values < 0.35)
        e = np.nan_to_num(rr.values - p["mu"], nan=0.0)
        e[~okm] = 0.0
        s2 = _cond(e, okm, p)
        sig = np.sqrt(s2)
        z = e[okm] / sig[:-1][okm]
        z = z[np.isfinite(z)][-NZ:]
        z = (z - z.mean()) / (z.std() or 1)                       # dinormalkan: rata-rata 0, sd 1
        r1 = R[t].dropna()
        r1 = r1[r1.abs() < 0.35]
        rv = lambda n: float(r1.iloc[-n:].std() * ANN) if len(r1) >= n else None  # noqa: E731
        hh, ll_, cc, oo = h[t], l[t], c[t], o[t]
        park = np.sqrt((np.log(hh / ll_) ** 2).iloc[-20:].mean() / (4 * np.log(2))) * ANN
        gk = np.sqrt((0.5 * np.log(hh / ll_) ** 2 - (2 * np.log(2) - 1) * np.log(cc / oo) ** 2).iloc[-20:].mean()) * ANN
        ew = r1.iloc[-500:].pow(2).ewm(alpha=0.06).mean()
        rv20 = r1.rolling(20).std() * ANN
        hist20 = rv20.iloc[-750:].dropna()
        last = float(cc.dropna().iloc[-1])
        y1 = r1.iloc[-250:]
        persist = p["a"] + p["g"] / 2 + p["b"]
        cv = pd.Series(sig[1:] * ANN, index=rr.index).reindex(c.index[-nb:])
        out[t] = {
            "g": {"a": round(p["a"], 4), "b": round(p["b"], 4), "g": round(p["g"], 4), "w": p["w"], "mu": round(p["mu"], 6),
                  "s1": round(float(sig[-1]), 5),                                   # σ harian untuk besok
                  "lr": round(float(np.sqrt(p["v0"]) * ANN), 4),                      # vol jangka panjang (tahunan)
                  "hl": round(float(np.log(0.5) / np.log(persist)), 1) if 0 < persist < 1 else None, "n": p["n"]},
            "z": [round(float(x), 3) for x in z],
            "rv": {"10": rv(10), "20": rv(20), "60": rv(60), "120": rv(120), "250": rv(250),
                   "park": float(park) if np.isfinite(park) else None, "gk": float(gk) if np.isfinite(gk) else None,
                   "ewma": float(np.sqrt(ew.iloc[-1]) * ANN) if len(ew) else None,
                   "pct": float((hist20 < hist20.iloc[-1]).mean()) if len(hist20) > 100 else None,
                   "skew": float(y1.skew()) if len(y1) > 60 else None, "kurt": float(y1.kurt()) if len(y1) > 60 else None,
                   "mu1": float(y1.mean() * 250) if len(y1) > 60 else None},
            "cv": [None if not np.isfinite(x) else round(float(x), 4) for x in cv.values],
            "rvs": [None if not np.isfinite(x) else round(float(x), 4) for x in rv20.reindex(c.index[-nb:]).values],
            "lim": {"ara": round(ara_pct(last), 4), "arb": round(arb_pct(last, arb_cfg), 4)},
        }
        for k, v in list(out[t]["rv"].items()):
            if v is not None and np.isfinite(v):
                out[t]["rv"][k] = round(v, 4)
        out[t] = _clean(out[t])
        g = out[t]["g"]
        if g["s1"] is None or g["w"] is None or not out[t]["z"] or any(v is None for v in out[t]["z"]):
            del out[t]                                             # data tidak cukup untuk simulasi
    return out
