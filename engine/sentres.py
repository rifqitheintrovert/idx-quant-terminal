"""Riset sentimen BEI — level pasar (IHSG) dan per saham. Hanya ANALISIS; tidak mengubah model.

    python -m engine.sentres --cache .cache/panels.pkl

LEVEL PASAR — proxy harian (arah apa adanya; model yang menentukan bobot):
  ext    (saham naik ≥10% − turun ≥6,9%) / saham likuid, rata-rata 10 hari   [khas BEI: ARA/ARB]
  turn   nilai transaksi 5 hari / rata-rata 250 hari (log)
  bigsm  return 20 hari 10 saham terbesar (nilai transaksi 1 thn) − separuh terkecil   [asing vs ritel]
  gor    porsi nilai transaksi saham < Rp200 vs rata-rata 250 hari (log)               [saham gorengan]
  ad     (naik − turun) / saham likuid, rata-rata 10 hari
  hilo, brd, mom, vol(−), flow, fx(−)   = komponen indeks v1
  onid   rata-rata (return semalam − siang) 20 hari saham likuid
  eido   return 20 hari EIDO (ETF Indonesia di New York, proxy minat asing)
  vix(−), dxy(−), eem                    selera risiko global ke negara berkembang
Model (walk-forward, dihitung ulang tiap awal bulan, hanya data masa lalu):
  v1     indeks sekarang (rata-rata persentil 6 komponen)
  pca    komponen utama pertama dari z-score proxy (gaya Baker–Wurgler), 3 thn terakhir
  pls    PLS 1 komponen: bobot = kovarians proxy dengan return IHSG 20 hari (yang sudah diketahui)
  kalman PCA yang disaring local-level Kalman (rasio noise diestimasi maksimum likelihood)
Metrik: IC Spearman (20/60 hari, per paruh), selisih kuintil, t Newey-West, R² out-of-sample (Campbell–Thompson),
uji Granger dua arah.

PER SAHAM — proxy (dinormalkan lintas saham tiap hari):
  aturn  nilai transaksi 5 hari / 120 hari (log)        ext20  hari naik ≥10% − turun ≥6,9% (20 hari)
  rssec  return 20 hari − median sektornya               rsmkt  return 20 hari − IHSG
  onid   return semalam − siang 20 hari                  vspk   volatilitas 5 hari / 60 hari (log)
Skor: ew (rata-rata), pca (komponen utama gabungan), pls (bobot = IC masa lalu).
Metrik: IC lintas saham harian (5/20/60 hari), t Fama-MacBeth dgn Newey-West, % hari IC>0, selisih kuintil Q5−Q1,
per paruh.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

MKT_PROX = ["ext", "turn", "bigsm", "gor", "ad", "hilo", "brd", "mom", "vol", "flow", "fx", "onid", "eido", "vix", "dxy", "eem"]
STK_PROX = ["aturn", "ext20", "rssec", "rsmkt", "onid", "vspk"]


# ------------------------------------------------------------------ utilitas statistik
def _rz(x: pd.DataFrame | pd.Series, n=250, mp=200):
    return (x - x.rolling(n, min_periods=mp).mean()) / x.rolling(n, min_periods=mp).std()


def _nw_t(y: np.ndarray, x: np.ndarray, lag: int):
    """t-stat koefisien regresi y = a + b·x dengan galat Newey-West."""
    m = np.isfinite(y) & np.isfinite(x)
    y, x = y[m], x[m]
    if len(y) < 100:
        return None, None
    X = np.column_stack([np.ones(len(x)), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:-L]
        S += w * (G + G.T)
    XtXi = np.linalg.inv(X.T @ X)
    V = XtXi @ S @ XtXi
    return float(b[1]), float(b[1] / np.sqrt(V[1, 1])) if V[1, 1] > 0 else None


def _nw_mean_t(x: np.ndarray, lag: int):
    x = x[np.isfinite(x)]
    if len(x) < 50:
        return None
    e = x - x.mean()
    s = (e @ e) / len(x)
    for L in range(1, lag + 1):
        s += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / len(x)
    return float(x.mean() / np.sqrt(s / len(x))) if s > 0 else None


def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30:
        return None
    ra, rb = pd.Series(a[m]).rank().values, pd.Series(b[m]).rank().values
    return float(np.corrcoef(ra, rb)[0, 1])


def _chi2_sf(x, k):
    """Peluang ekor chi² (pendekatan Wilson–Hilferty) — cukup untuk uji Granger."""
    if x <= 0:
        return 1.0
    z = ((x / k) ** (1 / 3) - (1 - 2 / (9 * k))) / math.sqrt(2 / (9 * k))
    return 0.5 * math.erfc(z / math.sqrt(2))


def _granger(y: np.ndarray, x: np.ndarray, p: int = 5):
    """Apakah lag x membantu memprediksi y (di atas lag y sendiri)? Return (F, p-value)."""
    m = np.isfinite(y) & np.isfinite(x)
    y, x = y[m], x[m]
    T = len(y)
    if T < 200:
        return None, None
    Y = y[p:]
    Ly = np.column_stack([y[p - i:T - i] for i in range(1, p + 1)])
    Lx = np.column_stack([x[p - i:T - i] for i in range(1, p + 1)])
    one = np.ones((len(Y), 1))
    R = np.hstack([one, Ly])
    U = np.hstack([one, Ly, Lx])
    rss_r = np.sum((Y - R @ np.linalg.lstsq(R, Y, rcond=None)[0]) ** 2)
    rss_u = np.sum((Y - U @ np.linalg.lstsq(U, Y, rcond=None)[0]) ** 2)
    df2 = len(Y) - U.shape[1]
    F = ((rss_r - rss_u) / p) / (rss_u / df2)
    return float(F), _chi2_sf(F * p, p)


# ------------------------------------------------------------------ proxy pasar
def market_proxies(F: dict, ihsg: pd.Series, macro: dict) -> pd.DataFrame:
    c = F["c"]
    idx = c.index
    r = c.pct_change().clip(-0.35, 0.35)
    liq = F["liquid"].fillna(False).astype(bool)
    nl = liq.sum(1).replace(0, np.nan)
    val = F["value"].where(liq)
    ih = ihsg.reindex(idx).ffill()
    P = {}
    P["ext"] = (((r >= 0.10) & liq).sum(1) - ((r <= -0.069) & liq).sum(1)) / nl
    P["ext"] = P["ext"].rolling(10, min_periods=5).mean()
    tv = val.sum(1)
    P["turn"] = np.log(tv.rolling(5).mean() / tv.rolling(250, min_periods=200).mean())
    av = F["value"].rolling(250, min_periods=120).mean().where(liq)
    rk = av.rank(axis=1, ascending=False)
    big = rk <= 10
    small = av.le(av.median(axis=1), axis=0) & liq
    r20 = c / c.shift(20) - 1
    P["bigsm"] = r20.where(big).mean(1) - r20.where(small).mean(1)
    pen = (c < 200) & liq
    share = val.where(pen).sum(1) / tv.replace(0, np.nan)
    P["gor"] = np.log((share.rolling(5).mean() + 1e-4) / (share.rolling(250, min_periods=200).mean() + 1e-4))
    P["ad"] = ((((r > 0) & liq).sum(1) - ((r < 0) & liq).sum(1)) / nl).rolling(10, min_periods=5).mean()
    hi = (c >= c.rolling(250, min_periods=200).max()) & liq
    lo = (c <= c.rolling(250, min_periods=200).min()) & liq
    nh, nlw = hi.sum(1), lo.sum(1)
    P["hilo"] = ((nh - nlw) / (nh + nlw).replace(0, np.nan)).fillna(0).rolling(10, min_periods=5).mean()
    P["brd"] = ((c > F["ma50"]) & liq).sum(1) / nl
    P["mom"] = ih / ih.rolling(125, min_periods=100).mean() - 1
    P["vol"] = -(np.log(ih / ih.shift(1)).rolling(20).std())
    P["flow"] = ((F["cmf20"] > 0) & liq).sum(1) / nl
    if "on20" in F and "id20" in F:
        P["onid"] = (F["on20"] - F["id20"]).where(liq).mean(1)

    def ser(name):
        m = macro.get(name)
        if m is None:
            return None
        s = m["Close"] if isinstance(m, pd.DataFrame) else m
        s = s.copy()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize() if getattr(s.index, "tz", None) else pd.to_datetime(s.index).normalize()
        s = s[~s.index.duplicated(keep="last")]
        return s.reindex(idx, method="ffill")

    u = ser("USDIDR")
    if u is not None:
        P["fx"] = -(u / u.rolling(50, min_periods=40).mean() - 1)
    e = ser("EIDO")
    if e is not None:
        P["eido"] = e / e.shift(20) - 1
    v = ser("VIX")
    if v is not None:
        P["vix"] = -np.log(v / v.rolling(250, min_periods=200).mean())
    d = ser("DXY")
    if d is not None:
        P["dxy"] = -(d / d.rolling(50, min_periods=40).mean() - 1)
    m = ser("EEM")
    if m is not None:
        P["eem"] = m / m.shift(20) - 1
    return pd.DataFrame(P).reindex(columns=[k for k in MKT_PROX if k in P])


def v1_index(R: pd.DataFrame) -> pd.Series:
    cols = [k for k in ("hilo", "brd", "mom", "vol", "flow", "fx") if k in R]
    Pc = R[cols].rolling(250, min_periods=200).rank(pct=True) * 100
    return Pc.mean(axis=1, skipna=True).where(Pc.notna().sum(1) >= 4)


def _kalman_ll(y, q):
    """Local level: s_t = s_{t−1} + u (var q), y_t = s_t + e (var 1). Return (filtered, loglik)."""
    s, P, ll, out = 0.0, 1.0, 0.0, np.full(len(y), np.nan)
    for t, yt in enumerate(y):
        P = P + q
        if np.isfinite(yt):
            S = P + 1.0
            K = P / S
            v = yt - s
            ll += -0.5 * (np.log(S) + v * v / S)
            s = s + K * v
            P = (1 - K) * P
        out[t] = s
    return out, ll


def market_models(R: pd.DataFrame, ih: pd.Series, h_pls: int = 20, win: int = 750) -> dict:
    Z = _rz(R).clip(-4, 4)
    idx = Z.index
    fwd = np.log(ih.shift(-h_pls) / ih)
    out = {k: pd.Series(np.nan, index=idx) for k in ("pca", "pls")}
    first = np.r_[True, idx.month[1:] != idx.month[:-1]]
    w_pca = w_pls = None
    load = {}
    for i, d in enumerate(idx):
        if first[i] and i >= 400:
            X = Z.iloc[max(0, i - win):i].dropna(axis=1, how="all")
            X = X.loc[:, X.notna().mean() > 0.8].dropna()
            if len(X) >= 300 and X.shape[1] >= 4:
                C = np.corrcoef(X.values.T)
                ev, V = np.linalg.eigh(C)
                w = V[:, -1]
                ref = list(X.columns).index("brd") if "brd" in X.columns else 0
                if w[ref] < 0:
                    w = -w
                w_pca = pd.Series(w, index=X.columns)
                y = fwd.reindex(X.index).values
                keep = np.arange(len(X)) < len(X) - h_pls          # target harus sudah diketahui
                yy = y[keep]
                ok = np.isfinite(yy)
                if ok.sum() > 200:
                    Xk = X.values[keep][ok]
                    yk = (yy[ok] - yy[ok].mean()) / (yy[ok].std() or 1)
                    wp = Xk.T @ yk / len(yk)
                    w_pls = pd.Series(wp / (np.abs(wp).sum() or 1), index=X.columns)
                load[str(d.date())] = {"pca": w_pca.round(3).to_dict(), "pls": w_pls.round(3).to_dict() if w_pls is not None else None}
        zt = Z.iloc[i]
        if w_pca is not None:
            out["pca"].iloc[i] = float((zt.reindex(w_pca.index).fillna(0) * w_pca).sum())
        if w_pls is not None:
            out["pls"].iloc[i] = float((zt.reindex(w_pls.index).fillna(0) * w_pls).sum())
    # Kalman local-level pada skor PCA (q dipilih maksimum likelihood, dari data s/d 1 thn sebelum akhir)
    y = (out["pca"] / out["pca"].std()).values
    best = (None, -np.inf)
    cut = max(len(y) - 250, 300)
    for q in (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5):
        _, ll = _kalman_ll(y[:cut], q)
        if ll > best[1]:
            best = (q, ll)
    kf, _ = _kalman_ll(y, best[0])
    out["kalman"] = pd.Series(kf, index=idx).where(out["pca"].notna())
    out["v1"] = v1_index(R)
    return {"series": out, "loadings": load, "kalman_q": best[0]}


def market_metrics(S: pd.Series, ih: pd.Series, h: int) -> dict:
    fwd = np.log(ih.shift(-h) / ih)
    df = pd.DataFrame({"s": S, "f": fwd}).dropna()
    if len(df) < 300:
        return {}
    mid = df.index[len(df) // 2]
    o = {"n": len(df), "ic": _spear(df["s"].values, df["f"].values),
         "ic_h": [_spear(df.loc[df.index < mid, "s"].values, df.loc[df.index < mid, "f"].values),
                  _spear(df.loc[df.index >= mid, "s"].values, df.loc[df.index >= mid, "f"].values)]}
    q = pd.qcut(df["s"].rank(method="first"), 5, labels=False)
    qm = df.groupby(q)["f"].mean()
    o["q"] = [float(x) for x in qm.values]
    o["spread"] = float(qm.iloc[-1] - qm.iloc[0])
    b, t = _nw_t(df["f"].values, ((df["s"] - df["s"].mean()) / df["s"].std()).values, lag=h)
    o["beta"], o["t_nw"] = b, t
    # R² out-of-sample: regresi diperbarui tiap 5 hari dengan data yang targetnya sudah diketahui
    s_, f_ = df["s"].values, df["f"].values
    pe, pm, act = [], [], []
    for i in range(500, len(df), 5):
        j = i - h
        if j < 250:
            continue
        X = np.column_stack([np.ones(j), s_[:j]])
        bb = np.linalg.lstsq(X, f_[:j], rcond=None)[0]
        pe.append(bb[0] + bb[1] * s_[i])
        pm.append(f_[:j].mean())
        act.append(f_[i])
    if act:
        act, pe, pm = np.array(act), np.array(pe), np.array(pm)
        o["r2oos"] = float(1 - np.sum((act - pe) ** 2) / np.sum((act - pm) ** 2))
    return o


# ------------------------------------------------------------------ proxy per saham
def stock_proxies(F: dict, ihsg: pd.Series, sectors: dict) -> dict:
    c = F["c"]
    r = c.pct_change().clip(-0.35, 0.35)
    val = F["value"]
    ih = ihsg.reindex(c.index).ffill()
    r20 = c / c.shift(20) - 1
    P = {"aturn": np.log((val.rolling(5, min_periods=3).mean() + 1) / (val.rolling(120, min_periods=60).mean() + 1)),
         "ext20": (r >= 0.10).astype(float).rolling(20, min_periods=10).sum() - (r <= -0.069).astype(float).rolling(20, min_periods=10).sum(),
         "rsmkt": r20.sub(ih / ih.shift(20) - 1, axis=0),
         "vspk": np.log((r.rolling(5, min_periods=4).std() + 1e-4) / (r.rolling(60, min_periods=40).std() + 1e-4))}
    sec = pd.Series(sectors).reindex(c.columns).fillna("Lainnya")
    med = pd.DataFrame(index=c.index, columns=c.columns, dtype=float)
    for s_, cols in sec.groupby(sec).groups.items():
        cols = list(cols)
        med[cols] = np.repeat(r20[cols].median(axis=1).values[:, None], len(cols), 1)
    P["rssec"] = r20 - med
    if "on20" in F and "id20" in F:
        P["onid"] = F["on20"] - F["id20"]
    return {k: P[k] for k in STK_PROX if k in P}


def _xs_z(X: pd.DataFrame, liq: pd.DataFrame) -> pd.DataFrame:
    """Normalisasi lintas saham: peringkat → skala unit (hanya saham likuid)."""
    Xm = X.where(liq)
    rk = Xm.rank(axis=1, pct=True)
    return (rk - 0.5) * np.sqrt(12)


def _xs_ic(S: pd.DataFrame, fwd: pd.DataFrame, liq: pd.DataFrame, min_n=50) -> pd.Series:
    a = S.where(liq & fwd.notna())
    b = fwd.where(a.notna())
    ra, rb = a.rank(axis=1), b.rank(axis=1)
    ra = ra.sub(ra.mean(1), axis=0)
    rb = rb.sub(rb.mean(1), axis=0)
    num = (ra * rb).sum(1)
    den = np.sqrt((ra ** 2).sum(1) * (rb ** 2).sum(1))
    ic = num / den.replace(0, np.nan)
    return ic.where(a.notna().sum(1) >= min_n)


def stock_scores(Zs: dict, liq: pd.DataFrame, fwd20: pd.DataFrame, refit_days: int = 21, win: int = 500) -> dict:
    idx = liq.index
    ks = list(Zs)
    ew = sum(Zs[k].fillna(0) for k in ks) / len(ks)
    ew = ew.where(liq)
    # IC harian tiap proxy vs return 20 hari (hanya dipakai setelah targetnya diketahui -> embargo 20 hari)
    ics = pd.DataFrame({k: _xs_ic(Zs[k], fwd20, liq) for k in ks})
    pca = pd.DataFrame(np.nan, index=idx, columns=liq.columns)
    pls = pd.DataFrame(np.nan, index=idx, columns=liq.columns)
    w_pca = w_pls = None
    lw = {}
    for i in range(0, len(idx), refit_days):
        if i >= 400:
            lo = max(0, i - win)
            samp = list(range(lo, i, 5))
            M = np.column_stack([np.concatenate([Zs[k].values[s][liq.values[s]] for s in samp]) for k in ks])
            M = M[np.isfinite(M).all(1)]
            if len(M) > 2000:
                ev, V = np.linalg.eigh(np.corrcoef(M.T))
                w = V[:, -1]
                if w[ks.index("aturn")] < 0:
                    w = -w
                w_pca = w
            ic_past = ics.iloc[lo:max(lo + 1, i - 20)].mean()
            if ic_past.notna().all():
                w_pls = (ic_past / (ic_past.abs().sum() or 1)).values
            lw[str(idx[i].date())] = {"pca": dict(zip(ks, np.round(w_pca, 3))) if w_pca is not None else None,
                                      "pls": dict(zip(ks, np.round(w_pls, 3))) if w_pls is not None else None}
        j = min(i + refit_days, len(idx))
        if w_pca is not None:
            pca.iloc[i:j] = sum(Zs[k].iloc[i:j].fillna(0).values * w_pca[n] for n, k in enumerate(ks))
        if w_pls is not None:
            pls.iloc[i:j] = sum(Zs[k].iloc[i:j].fillna(0).values * w_pls[n] for n, k in enumerate(ks))
    return {"ew": ew, "pca": pca.where(liq), "pls": pls.where(liq), "ics": ics, "w": lw}


def stock_metrics(S: pd.DataFrame, fwd: pd.DataFrame, liq: pd.DataFrame, h: int, start=None) -> dict:
    ic = _xs_ic(S, fwd, liq)
    if start is not None:
        ic = ic[ic.index >= start]
    ic = ic.dropna()
    if len(ic) < 200:
        return {}
    mid = ic.index[len(ic) // 2]
    # selisih kuintil: rata-rata harian (Q5 − Q1)
    a = S.where(liq & fwd.notna())
    if start is not None:
        a = a[a.index >= start]
    q = a.rank(axis=1, pct=True)
    f = fwd.reindex_like(a)
    qs = [f.where((q > i / 5) & (q <= (i + 1) / 5)).mean(1) for i in range(5)]
    qm = [float(x.mean()) for x in qs]
    sp = (qs[4] - qs[0]).dropna()
    return {"ic": float(ic.mean()), "ir": float(ic.mean() / ic.std()) if ic.std() > 0 else None, "t": _nw_mean_t(ic.values, lag=h),
            "pos": float((ic > 0).mean()), "ic_h": [float(ic[ic.index < mid].mean()), float(ic[ic.index >= mid].mean())],
            "q": qm, "spread": float(sp.mean()), "t_spread": _nw_mean_t(sp.values, lag=h), "n": int(len(ic))}


# ------------------------------------------------------------------ main
def main(argv=None):
    import argparse
    from datetime import datetime
    from pathlib import Path

    import yaml

    from . import data, features, flowx, fundamentals
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
    try:
        flowx.compute(F, fundamentals.load(Path(a.cache).parent / "fundamentals.json"))
    except Exception as e:  # noqa: BLE001
        print("flowx dilewati", e)
    syms = {"IHSG": "^JKSE", "USDIDR": "IDR=X", "EIDO": "EIDO", "VIX": "^VIX", "DXY": "DX-Y.NYB", "EEM": "EEM"}
    got = data.fetch_yahoo(list(syms.values()), hist_start(cfg, now))
    macro = {k: got.get(s) for k, s in syms.items() if got.get(s) is not None}

    def P(*x):
        print("SNT|", *x, flush=True)
    P(f"DATA {F['c'].shape[1]} saham, {F['c'].index[0].date()} s/d {F['c'].index[-1].date()} | makro: {sorted(macro)}")
    ihs = macro["IHSG"]["Close"]
    ihs.index = pd.to_datetime(ihs.index).tz_localize(None).normalize() if getattr(ihs.index, "tz", None) else pd.to_datetime(ihs.index).normalize()
    ih = ihs[~ihs.index.duplicated(keep="last")].reindex(F["c"].index, method="ffill")

    # ================= PASAR =================
    R = market_proxies(F, ih, macro)
    P("== PASAR: proxy tersedia", list(R.columns), "| mulai", {k: str(R[k].first_valid_index().date()) if R[k].first_valid_index() is not None else None for k in R})
    mm = market_models(R, ih)
    S = mm["series"]
    start = max(s.first_valid_index() for s in S.values() if s.first_valid_index() is not None)
    P(f"jendela uji pasar: {start.date()} s/d {F['c'].index[-1].date()} | Kalman q={mm['kalman_q']}")
    last_load = list(mm["loadings"].items())[-1] if mm["loadings"] else None
    if last_load:
        P("bobot terakhir", last_load[0], "PCA", last_load[1]["pca"], "| PLS", last_load[1]["pls"])
    Zm = _rz(R)
    for name in ["v1", "pca", "pls", "kalman"] + list(R.columns):
        s = S.get(name, Zm[name] if name in Zm else None)
        if s is None:
            continue
        s = s[s.index >= start]
        row = []
        for h in (20, 60):
            o = market_metrics(s, ih, h)
            if o:
                row.append(f"{h}H IC {o['ic']:+.3f} (paruh {o['ic_h'][0]:+.2f}/{o['ic_h'][1]:+.2f}) Q5−Q1 {o['spread']*100:+.1f}% tNW {o['t_nw']:+.2f} R²oos {o.get('r2oos', float('nan'))*100:+.1f}%")
        rr = np.log(ih / ih.shift(1)).reindex(s.index).values
        fa, pa = _granger(rr, s.values)
        fb, pb = _granger(s.values, rr)
        P(f"{name:7s} | " + " | ".join(row) + f" | Granger sentimen→IHSG p={pa:.3f}  IHSG→sentimen p={pb:.3f}" if pa is not None else "")

    # ================= PER SAHAM =================
    liq = F["liquid"].fillna(False).astype(bool)
    sectors = {t: (universe.get(t) or {}).get("sector") for t in F["c"].columns}
    SP = stock_proxies(F, ih, sectors)
    Zs = {k: _xs_z(v, liq) for k, v in SP.items()}
    c = F["c"]
    fwd = {h: np.log(c.shift(-h) / c).clip(-1.5, 1.5) for h in (5, 20, 60)}
    sc = stock_scores(Zs, liq, fwd[20])
    st0 = c.index[400]
    P(f"== PER SAHAM: proxy {list(SP)} | uji mulai {st0.date()} | saham likuid rata-rata {liq.sum(1)[liq.index >= st0].mean():.0f}/hari")
    lw = list(sc["w"].items())[-1] if sc["w"] else None
    if lw:
        P("bobot terakhir", lw[0], "PCA", lw[1]["pca"], "| PLS (IC masa lalu)", lw[1]["pls"])
    for name in ["ew", "pca", "pls"] + list(Zs):
        Sx = sc[name] if name in ("ew", "pca", "pls") else Zs[name]
        row = []
        for h in (5, 20, 60):
            o = stock_metrics(Sx, fwd[h], liq, h, start=st0)
            if o:
                row.append(f"{h}H IC {o['ic']:+.3f} t {o['t']:+.1f} >0 {o['pos']*100:.0f}% paruh {o['ic_h'][0]:+.3f}/{o['ic_h'][1]:+.3f} Q5−Q1 {o['spread']*100:+.2f}% (t {o['t_spread']:+.1f})")
        P(f"{name:6s} | " + " | ".join(row))
        if name in ("ew", "pls"):
            o = stock_metrics(Sx, fwd[20], liq, 20, start=st0)
            if o:
                P(f"        kuintil 20H Q1..Q5: {[round(x*100, 2) for x in o['q']]}")
    P("SELESAI")


if __name__ == "__main__":
    main()
