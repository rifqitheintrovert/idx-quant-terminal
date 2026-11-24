"""Backtest tiap model Quantitative Modeling (tab QM) di model asli — modal Rp10 jt, ±10 tahun. Hanya ANALISIS.

    python -m engine.qmbt --cache .cache/panels.pkl        (workflow "Backtest Model QM")

Setiap model dihitung ulang TITIK-WAKTU di setiap hari sinyal beli (hanya data sampai hari itu), dengan aturan
Positif/Netral/Negatif yang sama dengan ringkasan QM (qmodels.verdicts):
  vol (GJR-GARCH, refit bulanan + filter harian) · beta & sisi turun (CAPM 1 th) · alfa (faktor BEI 4, 1 th)
  HMM (refit bulanan + filter maju harian) · perilaku harga (variance ratio, deviasi MA50) · VaR99 EVT
  lompatan & ARA · drawdown · likuiditas (modal Rp10 jt) · peluang historis & Kelly rencana (frekuensi per kondisi
  sinyal, hanya hasil yang sudah diketahui) · sentimen saham (aturan lolos uji) · skor QM total.
Tiap model diuji 3 cara: (1) blokir sinyal saat Negatif, (2) beli hanya saat Positif, (3) prioritas slot.
Pembanding kebetulan (placebo): blokir ACAK dengan porsi sama (beberapa seed) & prioritas acak.
LOLOS = Calmar lebih baik di KEDUA paruh DAN di atas persentil-90 placebo. Kelly model diuji sebagai ukuran posisi
(risiko per trade 0,5–3%).
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, data, features, flowx, fundamentals, regime
from . import prob as PR
from . import qmodels as QM
from . import sentres as SR
from . import universe as uni_mod
from . import volmc as VM
from .flowmom import BASE, build, extras, kpi, pc
from .idx_rules import WIB
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]
ANN = np.sqrt(250)
MODELS = [("vol", "Volatilitas (GJR-GARCH)"), ("beta", "Beta ke IHSG"), ("downside", "Beta sisi turun"), ("alpha", "Alfa faktor BEI"),
          ("hmm", "Rezim (HMM)"), ("beh", "Perilaku harga (VR/OU)"), ("tail", "Risiko ekor (VaR99 EVT)"), ("jump", "Lompatan & ARA"),
          ("dd", "Drawdown"), ("liq", "Likuiditas & eksekusi"), ("prob", "Peluang historis sinyal"), ("kplan", "Kelly rencana trade"),
          ("sent", "Sentimen saham")]


def P(*a):
    print("QBT|", *a, flush=True)


def _ara_vec(p):
    return np.select([p <= 10, p <= 200, p <= 5000], [1 / np.maximum(p, 1), 0.35, 0.25], 0.20)


def _hmm_params(R: pd.DataFrame, iters=30):
    """Fit HMM Gauss 2 keadaan (kode sama dengan qmodels.hmm) dan kembalikan parameter per kolom."""
    X = R
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
        B = np.exp(-0.5 * (x[:, :, None] - mu[None]) ** 2 / var[None]) / np.sqrt(2 * np.pi * var[None])
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
    swap = var[:, 0] > var[:, 1]
    for arr in (mu, var, pi):
        arr[swap] = arr[swap][:, ::-1]
    A[swap] = A[swap][:, ::-1, ::-1]
    return {t: (mu[j], var[j], A[j], pi[j]) for j, t in enumerate(X.columns) if ok[:, j].sum() >= 250}


def _hmm_filter(x: np.ndarray, prm) -> float:
    mu, var, A, pi = prm
    a = pi.copy()
    for v in x:
        if not np.isfinite(v) or abs(v) >= 0.35:
            a = a @ A
            continue
        b = np.exp(-0.5 * (v - mu) ** 2 / var) / np.sqrt(2 * np.pi * var)
        a = (a @ A) * np.maximum(b, 1e-300)
        a /= a.sum()
    return float(a[1])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    a = ap.parse_args(argv)
    T0 = time.time()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    now = datetime.now(WIB)
    universe, _, _ = uni_mod.load(cfg, refresh=False)
    fund = {}
    if a.demo:
        universe = {k: universe[k] for k in list(universe)[:150]}
        panels, macro = data.demo_data(universe, cfg["macro"], days=2600)
        F = extras(features.compute(panels, cfg))
        flowx.compute(F, {})
    else:
        cache = data.load_cache(a.cache)
        cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
        frames = {t: f for t, f in cache["frames"].items() if t in universe and len(f) and f.index[-1] >= cutoff}
        F = extras(features.compute(data.build_panels(frames, list(frames)), cfg))
        try:
            fund = fundamentals.load(Path(a.cache).parent / "fundamentals.json") or {}
            flowx.compute(F, fund)
        except Exception as e:  # noqa: BLE001
            P("flowx dilewati", e)
        got = data.fetch_yahoo(["^JKSE", "IDR=X"], hist_start(cfg, now))
        macro = {"IHSG": got["^JKSE"], "USDIDR": got.get("IDR=X")}
    ihs = macro["IHSG"]["Close"]
    ihs.index = pd.to_datetime(ihs.index).tz_localize(None).normalize() if getattr(ihs.index, "tz", None) else pd.to_datetime(ihs.index).normalize()
    ih = ihs[~ihs.index.duplicated(keep="last")].reindex(F["c"].index, method="ffill")
    reg = regime.compute(ih, F, macro["USDIDR"]["Close"] if macro.get("USDIDR") is not None else None)
    comp, cond = build(F, cfg, reg, BASE)
    c, h, l = F["c"], F["h"], F["l"]
    liq = F["liquid"].fillna(False).astype(bool)
    idx, cols = c.index, list(c.columns)
    E = cond["entry"].fillna(False).astype(bool) & liq
    ST = cond["strong"].fillna(False).astype(bool)
    pts = np.argwhere(E.values)                                  # (i hari, j saham)
    eq0 = float(cfg["backtest"].get("initial_equity", 10_000_000))
    P(f"DATA {c.shape[1]} saham {idx[0].date()}–{idx[-1].date()} | sinyal beli {len(pts)} | modal Rp{eq0:,.0f}")

    def run(c2, cp=None, cfg2=None):
        _, det = backtest.run(F, comp if cp is None else cp, c2, reg, cfg2 or cfg, detail=True)
        return kpi(det["df"], len(det["trades"]))

    t1 = time.time()
    q0 = run(cond)
    P(f"satu backtest {time.time() - t1:.1f} dtk")

    # ------------------------------------------------------------------ panel bantu (vektor)
    lr = np.log(c / c.shift(1))
    rs = c.pct_change().clip(-0.35, 0.35)
    m = ih.pct_change()
    ma50 = F["ma50"]
    atr = F["atr14"]
    value = F["value"]
    adv20 = value.rolling(20, min_periods=10).mean()
    hl2 = np.log(h / l) ** 2
    betaCS = hl2 + hl2.shift(1)
    h2 = np.maximum(h, h.shift(1))
    l2 = np.minimum(l, l.shift(1))
    gam = np.log(h2 / l2) ** 2
    kk = 3 - 2 * np.sqrt(2)
    alp = (np.sqrt(2 * betaCS) - np.sqrt(betaCS)) / kk - np.sqrt(gam / kk)
    cs60 = (2 * (np.exp(alp) - 1) / (1 + np.exp(alp))).clip(lower=0).rolling(60, min_periods=30).mean()
    try:
        fac = QM.factors(F, ih, fund, days=len(idx) - 270)
        fac = fac.reindex(idx)
        P(f"faktor BEI: {fac.notna().all(axis=1).sum()} hari lengkap")
    except Exception as e:  # noqa: BLE001
        fac = None
        P("faktor dilewati", e)

    # ---- peluang historis per kondisi sinyal: hanya hasil yang SUDAH diketahui pada hari itu ----
    Y = PR._targets(F, cfg)
    liqv = liq.values
    strong_m = (ST & E).values
    buy_m = E.values & ~strong_m
    exp_stats = {}
    for key, msk in (("strong", strong_m), ("buy", buy_m), ("all", liqv)):
        for name, horizon in (("up20", 20), ("tp1", 60), ("sl1", 60)):
            y = Y[name]
            ok = msk & np.isfinite(y)
            s_ = np.where(ok, y, 0).sum(1)
            n_ = ok.sum(1)
            cs_ = np.cumsum(s_)
            cn_ = np.cumsum(n_)
            sh = np.full(len(idx), np.nan)                     # hasil sinyal hari t diketahui di t+horizon
            sh[horizon:] = cs_[:-horizon] / np.maximum(cn_[:-horizon], 1)
            sh[horizon:][cn_[:-horizon] < 200] = np.nan
            exp_stats[(key, name)] = sh

    # ---- sentimen saham (walk-forward, sama dengan sentbt) ----
    t1 = time.time()
    try:
        SP = SR.stock_proxies(F, ih, {t: (universe.get(t) or {}).get("sector") for t in cols})
        Zs = {k: SR._xs_z(v, liq) for k, v in SP.items()}
        scs = SR.stock_scores(Zs, liq, np.log(c.shift(-20) / c).clip(-1.5, 1.5))
        p_ew = scs["ew"].rank(axis=1, pct=True)
        p_rd = scs["ridge"].rank(axis=1, pct=True)
        ext = SP["ext20"]
        ext_p = ext.where(liq).rank(axis=1, pct=True)
        hot_m = (ext >= 2) & (ext_p >= 0.9)
        sent_ok = True
    except Exception as e:  # noqa: BLE001
        sent_ok = False
        P("sentimen dilewati", e)
    P(f"sentimen {time.time() - t1:.0f} dtk")

    # ---- GARCH & HMM: refit bulanan (data sampai akhir bulan sebelumnya), filter harian ----
    t1 = time.time()
    months = pd.Series(idx.to_period("M"), index=idx)
    by_month = {}
    for (i, j) in pts:
        by_month.setdefault(months.iloc[i], set()).add(j)
    G_par, H_par = {}, {}
    for mo, js in sorted(by_month.items()):
        i0 = int(np.searchsorted(idx, mo.start_time)) - 1       # hari bursa terakhir sebelum bulan ini
        if i0 < 300:
            continue
        tick = [cols[j] for j in js]
        Rw = lr[tick].iloc[max(0, i0 - 1499):i0 + 1]
        try:
            gp = VM.fit(Rw)
            for t, p in gp.items():
                G_par[(mo, t)] = (p, max(0, i0 - 1499))
        except Exception:  # noqa: BLE001
            pass
        try:
            hp = _hmm_params(lr[tick].iloc[max(0, i0 - 749):i0 + 1])
            for t, p in hp.items():
                H_par[(mo, t)] = p
        except Exception:  # noqa: BLE001
            pass
    P(f"GARCH & HMM refit bulanan: {len(by_month)} bulan, {time.time() - t1:.0f} dtk")

    # ------------------------------------------------------------------ penilaian titik-waktu per sinyal
    t1 = time.time()
    fee = float(cfg["idx_rules"]["fee_buy"]) + float(cfg["idx_rules"]["fee_sell"])
    s_cfg = cfg["signal"]
    rk, mw = float(cfg["backtest"].get("risk_per_trade", 0.01)), float(cfg["backtest"].get("max_weight", 0.2))
    V = {k: np.zeros(len(pts), dtype=np.int8) for k, _ in MODELS}
    fwd60 = (c.shift(-60) / c - 1).values
    cv, lrv, rsv, mv = c.values, lr.values, rs.values, m.values
    facv = fac.values if fac is not None else None
    for n, (i, j) in enumerate(pts):
        t = cols[j]
        d = idx[i]
        mo = months.iloc[i]
        price = cv[i, j]
        # vol (GJR-GARCH)
        gp = G_par.get((mo, t))
        s1 = None
        if gp:
            p, st = gp
            rr = lrv[st:i + 1, j]
            okm = np.isfinite(rr) & (np.abs(rr) < 0.35)
            e = np.where(okm, rr - p["mu"], 0.0)
            s2 = VM._cond(e, okm, p)
            s1 = float(np.sqrt(s2[-1]))
            lrun = np.sqrt(p["v0"]) * ANN
            r_ = s1 * ANN / lrun if lrun > 0 else None
            if r_ is not None:
                V["vol"][n] = 1 if r_ < 0.9 else -1 if r_ > 1.2 else 0
        # beta, sisi turun, alfa (1 tahun)
        y = rsv[max(0, i - 249):i + 1, j]
        mm = mv[max(0, i - 249):i + 1]
        res = QM._ols(y, mm[:, None])
        if res:
            bb = res[0][1]
            V["beta"][n] = 1 if bb > 1.2 else 0                  # sinyal beli hanya muncul saat gerbang terbuka
        dn, up = mm < 0, mm > 0
        rd, ru = QM._ols(y[dn], mm[dn][:, None]), QM._ols(y[up], mm[up][:, None])
        if rd and ru:
            rr_ = rd[0][1] / (ru[0][1] or 1e-9)
            V["downside"][n] = -1 if rr_ > 1.15 else 1 if rr_ < 0.85 else 0
        if facv is not None:
            ff = QM._ols(y, facv[max(0, i - 249):i + 1])
            if ff:
                ta = ff[1][0]
                V["alpha"][n] = 1 if ta >= 1.96 else -1 if ta <= -1.96 else 0
        # HMM
        hp = H_par.get((mo, t))
        if hp and hp[1][0] > 0 and hp[1][1] / hp[1][0] >= 1.69:   # vol rezim beda ≥ 1,3× (varians 1,69×)
            i0 = int(np.searchsorted(idx, mo.start_time)) - 1
            pnow = _hmm_filter(lrv[max(0, i0 - 749):i + 1, j], hp)
            V["hmm"][n] = 1 if pnow < 0.3 else -1 if pnow > 0.7 else 0
        # perilaku harga & ekor (fungsi yang sama dengan tab QM, data sampai hari itu)
        lo = max(0, i - 800)
        try:
            b = QM.behavior(c[t].iloc[lo:i + 1], ma50[t].iloc[lo:i + 1])
            if b.get("label"):
                upd, z = (b.get("dev") or 0) > 0, b.get("dev_z") or 0
                V["beh"][n] = (1 if upd else -1) if b["label"] == "trending" else (-1 if z > 1 else 1 if z < -1 else 0) if b["label"] == "mean-reverting" else 0
        except Exception:  # noqa: BLE001
            pass
        x = lrv[max(0, i - 749):i + 1, j]
        x = x[np.isfinite(x) & (np.abs(x) < 0.35)]
        if len(x) >= 250:
            loss = -x
            u = np.quantile(loss, 0.95)
            ex = loss[loss > u] - u
            var99 = None
            if len(ex) >= 20:
                xi, sig = QM._gpd_pwm(ex)
                if xi is not None and xi < 0.9:
                    nn, nu = len(loss), len(ex)
                    var99 = u + sig / xi * (((nn / nu) * 0.01) ** (-xi) - 1) if abs(xi) > 1e-6 else u - sig * np.log((nn / nu) * 0.01)
            if var99 is None:
                var99 = np.quantile(loss, 0.99)
            V["tail"][n] = 1 if var99 < 0.05 else -1 if var99 > 0.08 else 0
            eqw = cv[max(0, i - 749):i + 1, j]
            eqw = eqw[np.isfinite(eqw)]
            ddn = eqw[-1] / eqw.max() - 1
            V["dd"][n] = 1 if ddn > -0.1 else -1 if ddn < -0.3 else 0
        y1 = lrv[max(0, i - 249):i + 1, j]
        y1 = y1[np.isfinite(y1)]
        if len(y1) > 120:
            rv = (y1 ** 2).sum()
            bv = (np.pi / 2) * (np.abs(y1[1:]) * np.abs(y1[:-1])).sum()
            jmp = max(rv - bv, 0) / rv if rv > 0 else 0
            pr = cv[max(0, i - 250):i, j]
            rr1 = rsv[max(0, i - 249):i + 1, j]
            k_ = min(len(pr), len(rr1))
            lim = _ara_vec(pr[-k_:])
            ara = int(np.nansum(rr1[-k_:] >= lim - 0.005))
            V["jump"][n] = -1 if (ara >= 3 or jmp > 0.3) else 1 if (ara == 0 and jmp < 0.1) else 0
        # likuiditas: ukuran posisi dengan modal backtest
        a20, csv_ = adv20.iat[i, j], cs60.iat[i, j]
        R_ = s_cfg["atr_stop_mult"] * atr.iat[i, j]
        if np.isfinite(a20) and a20 > 0 and np.isfinite(R_) and R_ > 0:
            lots = int(min(eq0 * rk / R_, eq0 * mw / price) // 100)
            part = max(lots, 0) * 100 * price / a20
            cost = 2 * s1 * part ** 0.5 + (csv_ if np.isfinite(csv_) else 0) + fee if s1 else None
            V["liq"][n] = 1 if part < 0.05 and (cost is None or cost < 0.008) else -1 if part > 0.2 or (cost is not None and cost > 0.015) else 0
        # peluang historis & Kelly rencana (per kondisi sinyal, hasil yang sudah diketahui)
        key = "strong" if strong_m[i, j] else "buy"
        u20, a20_ = exp_stats[(key, "up20")][i], exp_stats[("all", "up20")][i]
        if np.isfinite(u20) and np.isfinite(a20_):
            dlt = u20 - a20_
            V["prob"][n] = 1 if dlt > 0.03 else -1 if dlt < -0.02 else 0
        tp, sl = exp_stats[(key, "tp1")][i], exp_stats[(key, "sl1")][i]
        if np.isfinite(tp) and np.isfinite(sl) and np.isfinite(R_) and R_ > 0:
            fr = fee / (R_ / price)
            kq = QM._kelly3(tp, sl, float(s_cfg["tp1_r"]) - fr, 1 + fr)
            if kq is not None:
                V["kplan"][n] = 1 if kq > 0.005 else -1 if kq < 0 else 0
        # sentimen (aturan lolos uji)
        if sent_ok:
            hot = bool(hot_m.iat[i, j])
            cold = bool(p_ew.iat[i, j] <= 0.2) if np.isfinite(p_ew.iat[i, j]) else False
            rdp = p_rd.iat[i, j]
            bad = hot or cold or (np.isfinite(rdp) and rdp <= 0.2)
            good = np.isfinite(rdp) and rdp >= 0.8
            V["sent"][n] = -1 if bad else 1 if good else 0
        if n and n % 2000 == 0:
            P(f"  {n}/{len(pts)} sinyal dinilai ({time.time() - t1:.0f} dtk)")
    P(f"penilaian {len(pts)} sinyal: {time.time() - t1:.0f} dtk")
    Qs = sum(V[k].astype(int) for k, _ in MODELS)

    # ------------------------------------------------------------------ analisis tingkat sinyal (tanpa portofolio)
    f60 = fwd60[pts[:, 0], pts[:, 1]]
    mid_i = len(idx) // 2
    half = pts[:, 0] < mid_i
    sig_rows = {}

    def sig_stats(vv):
        out = {}
        for lab, val in (("pos", 1), ("neu", 0), ("neg", -1)):
            msk = (vv == val) & np.isfinite(f60)
            x = f60[msk]
            out[lab] = {"n": int(msk.sum()), "share": round(float((vv == val).mean()), 3),
                        "m60": round(float(np.mean(x)), 4) if len(x) >= 30 else None,
                        "h": [round(float(np.mean(f60[msk & half])), 4) if (msk & half).sum() >= 15 else None,
                              round(float(np.mean(f60[msk & ~half])), 4) if (msk & ~half).sum() >= 15 else None]}
        return out
    allm = np.isfinite(f60)
    base_sig = {"m60": round(float(np.mean(f60[allm])), 4), "h": [round(float(np.mean(f60[allm & half])), 4), round(float(np.mean(f60[allm & ~half])), 4)]}
    P(f"rata-rata return 60H semua sinyal beli: {pc(base_sig['m60'])} (paruh {pc(base_sig['h'][0])} / {pc(base_sig['h'][1])})")
    for k, lab in MODELS:
        sig_rows[k] = sig_stats(V[k])
        s_ = sig_rows[k]
        P(f"SINYAL {lab:28s} " + " | ".join(f"{nm} {s_[nm]['share'] * 100:4.0f}% ret60 {pc(s_[nm]['m60']) if s_[nm]['m60'] is not None else '–'}"
                                                f" ({pc(s_[nm]['h'][0]) if s_[nm]['h'][0] is not None else '–'}/{pc(s_[nm]['h'][1]) if s_[nm]['h'][1] is not None else '–'})"
                                                for nm in ("pos", "neu", "neg")))

    # ------------------------------------------------------------------ backtest portofolio
    def to_df(vv):
        a_ = np.zeros(E.shape, dtype=float)
        a_[pts[:, 0], pts[:, 1]] = vv
        return pd.DataFrame(a_, index=idx, columns=cols)

    def with_mask(keep):
        c2 = dict(cond)
        c2["entry"] = cond["entry"] & keep
        c2["strong"] = cond["strong"] & c2["entry"]
        return c2

    n_sig = len(pts)
    rng0 = np.random.default_rng(123)
    P("== PLACEBO: blokir sinyal ACAK dengan porsi tertentu (5 seed) ==")
    plc = {}
    for frac in (0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.85):
        res = []
        for seed in range(5):
            rng = np.random.default_rng(1000 * seed + int(frac * 100))
            drop = rng.uniform(size=n_sig) < frac
            q = run(with_mask(~to_df(drop.astype(float)).astype(bool)))
            res.append(q["calmar"])
        plc[frac] = res
        P(f"  acak blokir {frac * 100:3.0f}%: Calmar {np.median(res):.2f} (rentang {min(res):.2f}–{max(res):.2f}, p90 {np.percentile(res, 90):.2f})")
    P("== PLACEBO: prioritas acak (6 seed, k=8) ==")
    pp = []
    for seed in range(6):
        rr_ = np.random.default_rng(77 + seed).integers(-1, 2, size=n_sig)
        pp.append(run(cond, cp=comp + 8 * to_df(rr_))["calmar"])
    P(f"  prioritas acak: Calmar median {np.median(pp):.2f}, rentang {min(pp):.2f}–{max(pp):.2f}, p90 {np.percentile(pp, 90):.2f}")

    def p90_for(frac):
        if frac <= 0.001:
            return q0["calmar"]
        g = min(plc, key=lambda f: abs(f - frac))
        return float(np.percentile(plc[g], 90))

    def line(lab, q, extra=""):
        P(f"{lab:44s} CAGR {pc(q['cagr'])} | DD {pc(q['mdd'])} | Calmar {q['calmar']:.2f} | Sharpe {q['sharpe']:.2f} | "
          f"paruh C {q['h'][0][2]:.2f}/{q['h'][1][2]:.2f} | trade/thn {q['tpy']:.0f} {extra}")
    line("MODEL SEKARANG", q0)
    results = {"base": {"cagr": q0["cagr"], "mdd": q0["mdd"], "calmar": q0["calmar"], "sharpe": q0["sharpe"], "h": [x[2] for x in q0["h"]],
                        "tpy": q0["tpy"], "final": q0["final"]}, "models": {}, "signal": {"base": base_sig, "models": sig_rows}}

    def judge(q, p90):
        both = q["h"][0][2] > q0["h"][0][2] and q["h"][1][2] > q0["h"][1][2]
        return bool(both), bool(both and q["calmar"] > p90)

    def pack(q, frac=None, p90=None, both=None, ok=None):
        return {"cagr": round(q["cagr"], 4), "mdd": round(q["mdd"], 4), "calmar": round(q["calmar"], 3), "sharpe": round(q["sharpe"], 3),
                "h": [round(x[2], 3) for x in q["h"]], "tpy": round(q["tpy"], 1), "frac": None if frac is None else round(frac, 3),
                "p90": None if p90 is None else round(p90, 3), "both": both, "ok": ok}

    for k, lab in MODELS + [("qms", "Skor QM total")]:
        vv = V[k] if k != "qms" else Qs
        D = to_df(vv)
        row = {"label": lab}
        neg = (vv < 0) if k != "qms" else (vv < 0)
        frac = float(neg.mean())
        if 0 < frac < 0.97:
            q = run(with_mask(~(D < 0)))
            p90 = p90_for(frac)
            both, ok = judge(q, p90)
            row["block"] = pack(q, frac, p90, both, ok)
            line(f"[{lab}] blokir Negatif ({frac * 100:.0f}%)", q, f"| p90 acak {p90:.2f} {'LOLOS' if ok else ''}")
        posr = float((vv > 0).mean()) if k != "qms" else float((vv >= 2).mean())
        if 0.03 < posr < 1:
            q = run(with_mask(D > 0 if k != "qms" else D >= 2))
            p90 = p90_for(1 - posr)
            both, ok = judge(q, p90)
            row["only"] = pack(q, 1 - posr, p90, both, ok)
            line(f"[{lab}] hanya Positif ({posr * 100:.0f}% sinyal)", q, f"| p90 acak {p90:.2f} {'LOLOS' if ok else ''}")
        if (vv != 0).any():
            q = run(cond, cp=comp + (8 if k != "qms" else 2) * D)
            p90 = float(np.percentile(pp, 90))
            both, ok = judge(q, p90)
            row["prio"] = pack(q, None, p90, both, ok)
            line(f"[{lab}] prioritas", q, f"| p90 acak {p90:.2f} {'LOLOS' if ok else ''}")
        results["models"][k] = row

    P("== KELLY MODEL: risiko per trade (ukuran posisi) ==")
    sizing = {}
    for rk_ in (0.005, 0.01, 0.015, 0.02, 0.03):
        cfg2 = copy.deepcopy(cfg)
        cfg2["backtest"]["risk_per_trade"] = rk_
        q = run(cond, cfg2=cfg2)
        sizing[str(rk_)] = pack(q)
        line(f"risiko {rk_ * 100:.1f}%/trade", q)
    results["sizing"] = sizing
    results["meta"] = {"n_sig": n_sig, "start": str(idx[0].date()), "end": str(idx[-1].date()), "equity": eq0,
                       "placebo_block": {str(k): [round(x, 3) for x in v] for k, v in plc.items()}, "placebo_prio": [round(x, 3) for x in pp],
                       "minutes": round((time.time() - T0) / 60, 1), "demo": bool(a.demo), "run": str(now.date())}
    P("JSON " + json.dumps(results, default=float))
    out = ROOT / "site" / "data" / "qmbt.json"
    try:
        out.write_text(json.dumps(results, default=float))
    except Exception:  # noqa: BLE001
        pass
    P(f"SELESAI {(time.time() - T0) / 60:.1f} menit")


if __name__ == "__main__":
    main()
