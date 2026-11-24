"""Model kuantitatif per saham untuk tab QM (Quantitative Modeling). Semua deskriptif & titik-waktu.

1. Faktor   : regresi return harian saham pada faktor BEI yang dibangun dari universe sendiri —
              MKT (IHSG), SMB (kecil − besar, kapitalisasi), WML (momentum 12-1 menang − kalah), LIQ (tidak likuid − likuid).
              Plus beta CAPM 1/3 tahun, beta sisi turun, korelasi, alfa, porsi risiko spesifik, beta bergulir 60 hari.
2. Rezim    : Hidden Markov Model Gauss 2 keadaan (tenang vs bergejolak) atas return harian 3 tahun, EM (Baum-Welch)
              dijalankan serentak untuk semua saham. Peluang keadaan hari ini, durasi rata-rata, peluang tiap hari.
3. Perilaku : variance ratio Lo-MacKinlay (2/5/10/20 hari, z tahan heteroskedastisitas), Hurst dari variance ratio,
              autokorelasi, waktu paruh kembali ke MA50 (AR(1) Ornstein-Uhlenbeck).
4. Ekor     : VaR/ES 99% harian — historis, normal, Cornish-Fisher, EVT (Generalized Pareto, peaks-over-threshold, PWM);
              indeks ekor ξ; drawdown; porsi varians dari lompatan (bipower variation); hari menyentuh batas ARA & turun ≥ 7%.
5. Likuiditas: Amihud ILLIQ (+ persentil universe), spread Corwin-Schultz & Roll, nilai transaksi harian,
              hari tanpa transaksi — dampak pasar (hukum akar kuadrat) dihitung di dashboard dari ukuran posisi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 250


def _r(x, d=4):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


# ------------------------------------------------------------------ faktor
def factors(F: dict, ihsg: pd.Series, fund: dict, days: int = 800) -> pd.DataFrame:
    """Return harian faktor (sederhana, bukan log): MKT, SMB, WML, LIQ. Anggota portofolio ditetapkan tiap awal bulan
    dari data yang diketahui hari sebelumnya, bobot sama, saham likuid saja."""
    c = F["c"].iloc[-days - 260:]
    r = c.pct_change().clip(-0.35, 0.35)
    liq = F["liquid"].reindex_like(c).fillna(False).astype(bool)
    sh = pd.Series({t: (fund.get(t) or {}).get("shares") for t in c.columns}, dtype=float)
    size = c * sh                                                        # kolom tanpa data lembar -> NaN
    size = size.fillna(F["avg_val60"].reindex_like(c) * 250)            # tanpa data lembar: pakai nilai transaksi tahunan
    mom = F["mom_12_1"].reindex_like(c)
    ill = (r.abs() / F["value"].reindex_like(c).replace(0, np.nan)).rolling(60, min_periods=30).mean()
    idx = c.index
    first = np.r_[True, idx.month[1:] != idx.month[:-1]]
    out = {k: pd.Series(np.nan, index=idx) for k in ("SMB", "WML", "LIQ")}
    members = {}
    for i, d in enumerate(idx):
        if first[i] and i > 0:
            p = idx[i - 1]
            ok = liq.loc[p]
            for k, x, hi_is_long in (("SMB", size.loc[p], False), ("WML", mom.loc[p], True), ("LIQ", ill.loc[p], True)):
                v = x[ok & x.notna()]
                if len(v) >= 30:
                    lo_q, hi_q = v.quantile(0.3), v.quantile(0.7)
                    lo, hi = v.index[v <= lo_q], v.index[v >= hi_q]
                    members[k] = (hi, lo) if hi_is_long else (lo, hi)
        for k in out:
            if k in members:
                L, S = members[k]
                out[k].iloc[i] = r.loc[d, L].mean() - r.loc[d, S].mean()
    fac = pd.DataFrame(out)
    fac["MKT"] = ihsg.reindex(idx).pct_change()
    return fac[["MKT", "SMB", "WML", "LIQ"]].iloc[-days:]


def _ols(y, X):
    m = np.isfinite(y) & np.isfinite(X).all(1)
    y, X = y[m], X[m]
    if len(y) < 60:
        return None
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ coef
    dof = max(len(y) - A.shape[1], 1)
    s2 = res @ res / dof
    cov = s2 * np.linalg.pinv(A.T @ A)
    se = np.sqrt(np.diag(cov))
    r2 = 1 - res.var() / y.var() if y.var() > 0 else np.nan
    return coef, coef / se, r2, np.sqrt(s2), len(y)


def factor_block(rs: pd.Series, fac: pd.DataFrame, nb: int) -> dict:
    y = rs.reindex(fac.index).values
    out = {}
    full = _ols(y[-250:], fac.values[-250:])
    if full:
        coef, tt, r2, sres, n = full
        out["ff"] = {"alpha": _r(coef[0] * ANN), "t_alpha": _r(tt[0], 2), "r2": _r(r2, 3), "idio": _r(sres * np.sqrt(ANN)), "n": n,
                     "b": {k: _r(coef[i + 1], 3) for i, k in enumerate(fac.columns)},
                     "t": {k: _r(tt[i + 1], 2) for i, k in enumerate(fac.columns)}}
    m = fac["MKT"].values
    for lab, n in (("1y", 250), ("3y", 750)):
        res = _ols(y[-n:], m[-n:, None])
        if res:
            coef, tt, r2, sres, k = res
            out[f"capm{lab}"] = {"beta": _r(coef[1], 3), "t": _r(tt[1], 2), "alpha": _r(coef[0] * ANN), "r2": _r(r2, 3),
                                 "corr": _r(np.sign(coef[1]) * np.sqrt(max(r2, 0)), 3), "n": k}
    dn = m[-250:] < 0
    res = _ols(y[-250:][dn], m[-250:][dn][:, None])
    if res:
        out["beta_dn"] = _r(res[0][1], 3)
    up = m[-250:] > 0
    res = _ols(y[-250:][up], m[-250:][up][:, None])
    if res:
        out["beta_up"] = _r(res[0][1], 3)
    ys, ms = pd.Series(y, index=fac.index), fac["MKT"]
    rb = ys.rolling(60, min_periods=40).cov(ms) / ms.rolling(60, min_periods=40).var()
    out["rb"] = [_r(x, 3) for x in rb.iloc[-nb:].values]
    return out


# ------------------------------------------------------------------ HMM 2 keadaan
def hmm(R: pd.DataFrame, T: int = 750, iters: int = 40) -> dict:
    """Gaussian HMM 2 keadaan, EM serentak untuk semua kolom. Keadaan 1 = varians lebih besar."""
    X = R.iloc[-T:]
    ok = X.notna().values & (X.abs().values < 0.35)
    x = np.nan_to_num(X.values, nan=0.0)
    Tn, N = x.shape
    v = np.array([x[ok[:, j], j].var() if ok[:, j].sum() > 30 else 1e-4 for j in range(N)])
    v = np.where(v > 0, v, 1e-4)
    mu = np.zeros((N, 2))
    var = np.column_stack([v * 0.5, v * 2.5])
    A = np.tile(np.array([[0.97, 0.03], [0.06, 0.94]]), (N, 1, 1))
    pi = np.tile(np.array([0.7, 0.3]), (N, 1))
    for _ in range(iters):
        B = np.exp(-0.5 * (x[:, :, None] - mu[None]) ** 2 / var[None]) / np.sqrt(2 * np.pi * var[None])   # T×N×2
        B = np.where(ok[:, :, None], np.maximum(B, 1e-300), 1.0)
        al = np.empty((Tn, N, 2))
        sc = np.empty((Tn, N))
        a = pi * B[0]
        sc[0] = a.sum(1)
        al[0] = a / sc[0][:, None]
        for t in range(1, Tn):
            a = np.einsum("ni,nij->nj", al[t - 1], A) * B[t]
            sc[t] = a.sum(1)
            al[t] = a / sc[t][:, None]
        be = np.empty((Tn, N, 2))
        be[-1] = 1.0
        for t in range(Tn - 2, -1, -1):
            be[t] = np.einsum("nij,nj->ni", A, B[t + 1] * be[t + 1]) / sc[t + 1][:, None]
        ga = al * be
        ga /= ga.sum(2, keepdims=True)
        xi = (al[:-1, :, :, None] * A[None] * (B[1:] * be[1:])[:, :, None, :]) / sc[1:][:, :, None, None]
        A = xi.sum(0) / np.maximum(ga[:-1].sum(0)[:, :, None], 1e-12)
        A /= A.sum(2, keepdims=True)
        pi = ga[0]
        w = ga * ok[:, :, None]
        sw = np.maximum(w.sum(0), 1e-12)
        mu = (w * x[:, :, None]).sum(0) / sw
        var = np.maximum((w * (x[:, :, None] - mu[None]) ** 2).sum(0) / sw, 1e-7)
    swap = var[:, 0] > var[:, 1]                               # keadaan 1 = bergejolak
    for arr in (mu, var, pi):
        arr[swap] = arr[swap][:, ::-1]
    A[swap] = A[swap][:, ::-1, ::-1]
    ga[:, swap] = ga[:, swap][:, :, ::-1]
    al[:, swap] = al[:, swap][:, :, ::-1]
    out = {}
    for j, t in enumerate(X.columns):
        if ok[:, j].sum() < 250:
            continue
        p11, p00 = A[j, 1, 1], A[j, 0, 0]
        nxt = al[-1, j] @ A[j]
        out[t] = {"mu": [_r(mu[j, 0] * ANN), _r(mu[j, 1] * ANN)], "vol": [_r(np.sqrt(var[j, 0] * ANN)), _r(np.sqrt(var[j, 1] * ANN))],
                  "stay": [_r(p00, 3), _r(p11, 3)], "dur": [_r(1 / max(1 - p00, 1e-3), 1), _r(1 / max(1 - p11, 1e-3), 1)],
                  "now": _r(al[-1, j, 1], 3), "next": _r(nxt[1], 3), "share": _r(ga[:, j, 1].mean(), 3),
                  "p": [_r(z, 3) for z in ga[:, j, 1]]}
    return out


# ------------------------------------------------------------------ perilaku harga
def _vr(r, q):
    """Variance ratio Lo-MacKinlay dengan z* (tahan heteroskedastisitas)."""
    r = r[np.isfinite(r)]
    n = len(r)
    if n < q * 20:
        return None, None
    m = r.mean()
    s1 = ((r - m) ** 2).sum() / (n - 1)
    rq = np.convolve(r, np.ones(q), "valid")
    sq = ((rq - q * m) ** 2).sum() / (q * (n - q + 1) * (1 - q / n))
    vr = sq / s1 if s1 > 0 else np.nan
    e2 = (r - m) ** 2
    den = (e2.sum()) ** 2
    th = sum(((2 * (q - j) / q) ** 2) * ((e2[j:] * e2[:-j]).sum() * n / den) for j in range(1, q))
    z = (vr - 1) / np.sqrt(th / n) if th > 0 else np.nan
    return vr, z


def behavior(c: pd.Series, ma50: pd.Series) -> dict:
    lr = np.log(c / c.shift(1)).iloc[-750:].values
    lr = lr[np.isfinite(lr) & (np.abs(lr) < 0.35)]
    out = {"vr": {}}
    hs = []
    for q in (2, 5, 10, 20):
        vr, z = _vr(lr, q)
        out["vr"][str(q)] = [_r(vr, 3), _r(z, 2)]
        if vr and vr > 0:
            hs.append(0.5 + np.log(vr) / (2 * np.log(q)))
    out["hurst"] = _r(np.mean(hs), 3) if hs else None
    out["ac1"] = _r(pd.Series(lr).autocorr(1), 3) if len(lr) > 60 else None
    wk = pd.Series(lr).rolling(5).sum().iloc[::5].dropna()
    out["ac_w"] = _r(wk.autocorr(1), 3) if len(wk) > 40 else None
    dev = np.log(c / ma50).iloc[-500:].dropna()
    if len(dev) > 120:
        y, x = dev.values[1:], dev.values[:-1]
        phi = np.polyfit(x, y, 1)[0]
        out["hl"] = _r(-np.log(2) / np.log(phi), 1) if 0 < phi < 1 else None
        out["dev"] = _r(dev.iloc[-1], 4)
        out["dev_z"] = _r((dev.iloc[-1] - dev.mean()) / dev.std(), 2) if dev.std() > 0 else None
    z10 = out["vr"]["10"][1]
    out["label"] = None if z10 is None else ("trending" if z10 > 1.96 else "mean-reverting" if z10 < -1.96 else "acak")
    return out


# ------------------------------------------------------------------ ekor & lompatan
def _gpd_pwm(y):
    y = np.sort(y)
    n = len(y)
    b0 = y.mean()
    b1 = (y * (n - 1 - np.arange(n)) / (n - 1)).mean()        # PWM a₁ = E[X·(1−F)] (Hosking & Wallis 1987)
    den = b0 - 2 * b1
    if den <= 0:
        return None, None
    xi = 2 - b0 / den
    sig = 2 * b0 * b1 / den
    return xi, sig


def tails(c: pd.Series, h: pd.Series, l: pd.Series, ara_fn) -> dict:
    r = (c / c.shift(1) - 1)
    lr = np.log(1 + r)
    x = lr.iloc[-750:].dropna()
    x = x[x.abs() < 0.35].values
    out = {}
    if len(x) < 250:
        return out
    loss = -x
    m, s = x.mean(), x.std()
    sk = pd.Series(x).skew()
    ku = pd.Series(x).kurt()
    z = -2.326
    zcf = z + (z ** 2 - 1) * sk / 6 + (z ** 3 - 3 * z) * ku / 24 - (2 * z ** 3 - 5 * z) * sk ** 2 / 36
    out["var99"] = {"hist": _r(np.quantile(loss, 0.99)), "norm": _r(-(m + z * s)), "cf": _r(-(m + zcf * s))}
    out["es99_hist"] = _r(loss[loss >= np.quantile(loss, 0.99)].mean())
    u = np.quantile(loss, 0.95)
    ex = loss[loss > u] - u
    if len(ex) >= 20:
        xi, sig = _gpd_pwm(ex)
        if xi is not None and xi < 0.9:
            n, nu = len(loss), len(ex)
            vq = lambda p: u + sig / xi * (((n / nu) * (1 - p)) ** (-xi) - 1) if abs(xi) > 1e-6 else u - sig * np.log((n / nu) * (1 - p))  # noqa: E731
            v99, v995 = vq(0.99), vq(0.995)
            out["evt"] = {"xi": _r(xi, 3), "sigma": _r(sig), "u": _r(u), "var99": _r(v99), "var995": _r(v995),
                          "es99": _r((v99 + sig - xi * u) / (1 - xi)), "n": int(nu)}
    eq = c.iloc[-750:].dropna()
    dd = eq / eq.cummax() - 1
    out["dd"] = {"now": _r(dd.iloc[-1]), "max1y": _r(dd.iloc[-250:].min() if len(dd) >= 250 else dd.min()),
                 "max3y": _r((eq / eq.cummax() - 1).min())}
    y1 = lr.iloc[-250:].dropna().values
    if len(y1) > 120:
        rv = (y1 ** 2).sum()
        bv = (np.pi / 2) * (np.abs(y1[1:]) * np.abs(y1[:-1])).sum()
        out["jump"] = _r(max(rv - bv, 0) / rv if rv > 0 else None, 3)
    prev = c.shift(1).iloc[-250:]
    rr = r.iloc[-250:]
    lim = prev.apply(lambda p: ara_fn(p) if np.isfinite(p) and p > 0 else np.nan)
    out["ara_days"] = int(((rr >= lim - 0.005) & lim.notna()).sum())
    out["down7_days"] = int((rr <= -0.065).sum())
    out["up10_days"] = int((rr >= 0.10).sum())
    out["skew"], out["kurt"] = _r(sk, 2), _r(ku, 2)
    return out


# ------------------------------------------------------------------ likuiditas
def liquidity(F: dict, cols) -> dict:
    c, h, l, v, val = F["c"], F["h"], F["l"], F["v"], F["value"]
    r = c.pct_change()
    ill = (r.abs() / val.replace(0, np.nan)).iloc[-60:].mean() * 1e9          # % gerak per Rp1 miliar
    liq_last = F["liquid"].iloc[-1].fillna(False).astype(bool)
    ref = ill[liq_last].dropna()
    # Corwin-Schultz (2012) dari high/low dua hari
    hl = np.log(h / l) ** 2
    beta = hl + hl.shift(1)
    h2, l2 = pd.concat([h, h.shift(1)]).groupby(level=0).max(), pd.concat([l, l.shift(1)]).groupby(level=0).min()
    gam = np.log(h2 / l2) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gam / k)
    cs = (2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))).clip(lower=0).iloc[-60:].mean()
    dp = c.diff()
    out = {}
    for t in cols:
        if t not in c.columns:
            continue
        dpt = dp[t].iloc[-120:].dropna()
        cv = dpt.autocorr(1) * dpt.var() if len(dpt) > 30 else np.nan
        roll = 2 * np.sqrt(-cv) / c[t].iloc[-1] if np.isfinite(cv) and cv < 0 else 0.0
        vv = v[t].iloc[-60:]
        out[t] = {"amihud": _r(ill.get(t), 5), "amihud_pct": _r((ref < ill.get(t)).mean(), 3) if np.isfinite(ill.get(t, np.nan)) and len(ref) else None,
                  "cs": _r(cs.get(t)), "roll": _r(roll), "adv20": _r(val[t].iloc[-20:].mean(), 0), "adv60": _r(val[t].iloc[-60:].mean(), 0),
                  "zero": _r((vv.fillna(0) == 0).mean(), 3), "vol_lot": _r(vv.median() / 100, 0)}
    return out


# ------------------------------------------------------------------ gabungan
def build(F: dict, tickers: list[str], ihsg: pd.Series, fund: dict, nb: int, log=None) -> dict:
    import time

    from .idx_rules import ara_pct

    t0 = time.time()
    out = {t: {} for t in tickers}
    try:
        fac = factors(F, ihsg, fund or {})
        rs = F["c"].pct_change().clip(-0.35, 0.35)
        for t in tickers:
            out[t]["fac"] = factor_block(rs[t], fac, nb)
        fy = (1 + fac.iloc[-250:]).prod() - 1
        fac_sum = {k: _r(fy[k]) for k in fac.columns}
    except Exception as e:  # noqa: BLE001
        fac_sum = None
        if log:
            log.warning("QM faktor dilewati: %s", e)
    t1 = time.time()
    try:
        R = np.log(F["c"][tickers] / F["c"][tickers].shift(1))
        H = hmm(R)
        for t, v in H.items():
            p = v.pop("p")
            v["p"] = p[-nb:]
            out[t]["hmm"] = v
    except Exception as e:  # noqa: BLE001
        if log:
            log.warning("QM HMM dilewati: %s", e)
    t2 = time.time()
    try:
        L = liquidity(F, tickers)
    except Exception as e:  # noqa: BLE001
        L = {}
        if log:
            log.warning("QM likuiditas dilewati: %s", e)
    for t in tickers:
        try:
            out[t]["beh"] = behavior(F["c"][t], F["ma50"][t])
            out[t]["tail"] = tails(F["c"][t], F["h"][t], F["l"][t], ara_pct)
        except Exception:  # noqa: BLE001
            pass
        if t in L:
            out[t]["liq"] = L[t]
    if log:
        log.info("QM: faktor %.1f dtk, HMM %.1f dtk, sisanya %.1f dtk", t1 - t0, t2 - t1, time.time() - t2)
    return {"stocks": out, "factors_1y": fac_sum}


# ------------------------------------------------------------------ penilaian ringkas (sama persis dengan qmVerdicts di site/app.js)
def _kelly3(pw, pl, b, L=1.0):
    return (pw * b - pl * L) / (b * L * (pw + pl)) if pw + pl > 0 and b > 0 else None


def verdicts(s: dict, v: dict | None, q: dict | None, gate_open: bool, prob_meta: dict | None, kel: dict | None, cfg: dict,
             sent_m: dict | None = None) -> list:
    """[(model, +1/0/−1)] untuk satu saham. Ukuran posisi memakai pengaturan portofolio default di config."""
    q = q or {}
    f, h, b, t, l = q.get("fac") or {}, q.get("hmm"), q.get("beh") or {}, q.get("tail") or {}, q.get("liq") or {}
    c1 = f.get("capm1y") or {}
    g = (v or {}).get("g")
    ir = cfg.get("idx_rules", {})
    fee = float(ir.get("fee_buy", 0.0015)) + float(ir.get("fee_sell", 0.0025))
    out = []
    if g and g.get("s1") and g.get("lr"):
        r = g["s1"] * 250 ** 0.5 / g["lr"]
        out.append(("vol", 1 if r < 0.9 else -1 if r > 1.2 else 0))
    if c1.get("beta") is not None:
        bb = c1["beta"]
        out.append(("beta", (1 if bb > 1.2 else 0) if gate_open else (-1 if bb > 1.2 else 1 if bb < 0.8 else 0)))
    if f.get("beta_dn") is not None and f.get("beta_up") is not None:
        r = f["beta_dn"] / (f["beta_up"] or 1e-9)
        out.append(("downside", -1 if r > 1.15 else 1 if r < 0.85 else 0))
    if f.get("ff"):
        ta = f["ff"].get("t_alpha") or 0
        out.append(("alpha", 1 if ta >= 1.96 else -1 if ta <= -1.96 else 0))
    if h and h.get("vol") and h["vol"][0]:
        ok = h["vol"][1] / h["vol"][0] >= 1.3
        out.append(("hmm", 0 if not ok else 1 if h["now"] < 0.3 else -1 if h["now"] > 0.7 else 0))
    if b.get("label"):
        up, z = (b.get("dev") or 0) > 0, b.get("dev_z") or 0
        out.append(("beh", (1 if up else -1) if b["label"] == "trending" else (-1 if z > 1 else 1 if z < -1 else 0) if b["label"] == "mean-reverting" else 0))
    var99 = (t.get("evt") or {}).get("var99") if t.get("evt") else (t.get("var99") or {}).get("hist")
    if var99 is not None:
        out.append(("tail", 1 if var99 < 0.05 else -1 if var99 > 0.08 else 0))
    if t.get("jump") is not None:
        ara = t.get("ara_days") or 0
        bad, good = ara >= 3 or t["jump"] > 0.3, ara == 0 and t["jump"] < 0.1
        out.append(("jump", -1 if bad else 1 if good else 0))
    if (t.get("dd") or {}).get("now") is not None:
        d = t["dd"]["now"]
        out.append(("dd", 1 if d > -0.1 else -1 if d < -0.3 else 0))
    L = s.get("levels") or {}
    pdft = cfg.get("portfolio_defaults", {})
    eq, rk, mw = float(pdft.get("equity", 1e8)), float(pdft.get("risk_per_trade", 0.01)), float(pdft.get("max_weight", 0.2))
    en = L.get("entry_high") or s.get("last")
    if l.get("adv20") and en:
        rps = en - (L.get("sl") or 0)
        lots = int(min(eq * rk / rps, eq * mw / en) // 100) if rps > 0 and L.get("sl") else int(eq * mw / s["last"] // 100)
        part = max(lots, 0) * 100 * en / l["adv20"]
        cost = 2 * g["s1"] * part ** 0.5 + (l.get("cs") or 0) + fee if g and g.get("s1") else None
        out.append(("liq", 1 if part < 0.05 and (cost is None or cost < 0.008) else -1 if part > 0.2 or (cost is not None and cost > 0.015) else 0))
    st = (prob_meta or {}).get("states", {}).get((s.get("prob") or {}).get("st"))
    allst = (prob_meta or {}).get("states", {}).get("all")
    if st and st.get("up20") is not None and allst:
        d = st["up20"] - allst["up20"]
        out.append(("prob", 1 if d > 0.03 else -1 if d < -0.02 else 0))
    if st and st.get("tp1") is not None and st.get("sl1") is not None and L.get("sl") and L.get("tp1") and en:
        risk = en - L["sl"]
        if risk > 0:
            fr = fee / (risk / en)
            k = _kelly3(st["tp1"], st["sl1"], (L["tp1"] - en) / risk - fr, 1 + fr)
            if k is not None:
                out.append(("kplan", 1 if k > 0.005 else -1 if k < 0 else 0))
    if kel and kel.get("full") is not None:
        fr = rk / kel["full"] if kel["full"] > 0 else None
        out.append(("kmodel", 1 if fr is not None and fr <= 0.5 else -1 if fr is None or fr > 1 else 0))
    sx, sm = s.get("sx"), (sent_m or {})
    if sx:                                                     # hanya temuan sentimen yang lolos uji
        e60 = (sm.get("ext20") or {}).get("60") or {}
        q20 = (sm.get("ew") or {}).get("20") or {}
        hot = bool(e60.get("pass") and (e60.get("ic") or 0) < 0 and (sx.get("extp") or 0) >= 90 and (sx.get("ext") or 0) >= 2)
        cold = bool(sx.get("q1") and (q20.get("t_spread") or 0) >= 1.96)
        out.append(("sent", -1 if hot or cold else 0))
    return out
