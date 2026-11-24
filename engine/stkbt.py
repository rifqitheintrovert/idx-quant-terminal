"""Backtest PER SAHAM (modal Rp10 jt, satu saham saja) — ditampilkan di halaman saham.

    python -m engine.stkbt --cache .cache/panels.pkl          (workflow "Backtest per Saham", mingguan)

Posisi BELI SAJA; keluar dengan menjual TEPAT di harga wajar (order jual di harga wajar).
Harga wajar per tahun buku (dipakai 95 hari setelah tutup buku): DCF tab DCF (FCF rata-rata ≤ 3 thn, pertumbuhan
= CAGR pendapatan s/d tahun itu 2–15% atau angka pilihanmu, utang bersih tahun itu); bila DCF tidak bisa
(bank/keuangan, FCF negatif) → PBV wajar dari ROE (Gordon).
1. QM (tab GP): beli saat skor QM > 0 DAN harga < harga wajar × (1 − margin). Skor QM harian = jumlah vonis
   14 model ringkasan QM (qmodels.verdicts), dihitung ulang TITIK-WAKTU (GARCH & HMM tiap kuartal, perilaku
   harga & VaR tiap bulan, sisanya harian).
2. DCF (tab DCF): beli saat harga < harga wajar × (1 − margin).
Mesin ini mengirim harga & skor QM harian (sejak 2021) ke site/data/sbt/KODE.json; simulasi dengan asumsi yang
kamu atur dihitung di browser (sbtFV / sbtSim di app.js). _summary.json = hasil dengan asumsi bawaan.
Eksekusi beli di harga pembukaan hari berikutnya, lot 100, fee beli/jual dari config, modal tidak terpakai = kas.
Keterbatasan: jumlah saham = sekarang (Yahoo), laporan Yahoo ±4–5 tahun → harga wajar baru ada ±2022.
"""
from __future__ import annotations

import argparse
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
from .flowmom import BASE, build, extras
from .idx_rules import WIB
from .qmbt import _ara_vec, _hmm_params
from .run import hist_start

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "sbt"
ANN = np.sqrt(250)
KEYS = ["vol", "beta", "downside", "alpha", "hmm", "beh", "tail", "jump", "dd", "liq", "prob", "kplan", "kmodel", "sent"]


def P(*a):
    print("SBT|", *a, flush=True)


def _f(x, d=4):
    try:
        x = float(x)
        return round(x, d) if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def stats(dates, eq, trades, start, o, c, eq0):
    if start is None:
        return None
    e = pd.Series(eq[start:], index=dates[start:]).ffill().dropna()
    if len(e) < 60:
        return None
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    tot = e.iloc[-1] / eq0 - 1
    cagr = (e.iloc[-1] / eq0) ** (1 / yrs) - 1 if yrs > 0.3 and e.iloc[-1] > 0 else None
    dd = (e / e.cummax() - 1).min()
    cc = pd.Series(c[start:], index=dates[start:]).ffill()
    p0 = o[start + 1] if start + 1 < len(o) and np.isfinite(o[start + 1]) else c[start]
    bh_tot = cc.iloc[-1] / p0 - 1 if p0 and np.isfinite(p0) else None
    bh_cagr = (1 + bh_tot) ** (1 / yrs) - 1 if bh_tot is not None and yrs > 0.3 and bh_tot > -1 else None
    bh_dd = (cc / cc.cummax() - 1).min()
    closed = [t for t in trades if not t.get("open")]
    rets = np.array([t["ret"] for t in closed])
    inpos = 0
    for t in trades:
        d0 = pd.Timestamp(t["d0"])
        d1 = pd.Timestamp(t["d1"]) if t.get("d1") else e.index[-1]
        inpos += (d1 - d0).days
    return {"start": str(e.index[0].date()), "end": str(e.index[-1].date()), "years": _f(yrs, 2), "final": _f(e.iloc[-1], 0),
            "tot": _f(tot), "cagr": _f(cagr), "mdd": _f(dd), "trades": len(closed), "win": _f((rets > 0).mean(), 3) if len(rets) else None,
            "avg": _f(rets.mean()) if len(rets) else None, "hold": _f(np.mean([t["days"] for t in closed]), 0) if closed else None,
            "expo": _f(inpos / max(1, (e.index[-1] - e.index[0]).days), 3), "bh_tot": _f(bh_tot), "bh_cagr": _f(bh_cagr), "bh_mdd": _f(bh_dd)}


def setup(demo=False, cache=None, config=str(ROOT / "config.yaml")):
    """Muat data, fitur, rezim & model sinyal sekarang -> konteks."""
    T0 = time.time()
    cfg = yaml.safe_load(open(config, encoding="utf-8"))
    now = datetime.now(WIB)
    universe, _, _ = uni_mod.load(cfg, refresh=False)
    fund = {}
    if demo:
        universe = {k: universe[k] for k in list(universe)[:120]}
        panels, macro = data.demo_data(universe, cfg["macro"], days=2600)
        F = extras(features.compute(panels, cfg))
        flowx.compute(F, {})
        last = {t: float(F["c"][t].dropna().iloc[-1]) for t in F["c"].columns if F["c"][t].notna().any()}
        fund = fundamentals.demo(list(F["c"].columns), last)
    else:
        cache = data.load_cache(cache)
        cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
        frames = {t: f for t, f in cache["frames"].items() if t in universe and len(f) and f.index[-1] >= cutoff}
        F = extras(features.compute(data.build_panels(frames, list(frames)), cfg))
        try:
            fund = fundamentals.load(Path(cache).parent / "fundamentals.json") or {}
            flowx.compute(F, fund)
        except Exception as e:  # noqa: BLE001
            P("fundamental/flowx dilewati", e)
        got = data.fetch_yahoo(["^JKSE", "IDR=X"], hist_start(cfg, now))
        macro = {"IHSG": got["^JKSE"], "USDIDR": got.get("IDR=X")}
    ihs = macro["IHSG"]["Close"]
    ihs.index = pd.to_datetime(ihs.index).tz_localize(None).normalize() if getattr(ihs.index, "tz", None) else pd.to_datetime(ihs.index).normalize()
    ih = ihs[~ihs.index.duplicated(keep="last")].reindex(F["c"].index, method="ffill")
    usd = None
    if macro.get("USDIDR") is not None:
        u = macro["USDIDR"]["Close"]
        u.index = pd.to_datetime(u.index).tz_localize(None).normalize() if getattr(u.index, "tz", None) else pd.to_datetime(u.index).normalize()
        usd = u[~u.index.duplicated(keep="last")].reindex(F["c"].index, method="ffill")
    reg = regime.compute(ih, F, usd)
    comp, cond = build(F, cfg, reg, BASE)
    c_all = F["c"]
    idx = c_all.index
    liq = F["liquid"].fillna(False).astype(bool)
    return dict(T0=T0, cfg=cfg, now=now, universe=universe, fund=fund, F=F, ih=ih, usd=usd, reg=reg, comp=comp, cond=cond, c_all=c_all, idx=idx, liq=liq)


def qm_panel(ctx, T):
    """Vonis harian 14 model ringkasan QM (titik-waktu) untuk saham T. -> dict(V={model: D×N}, S=skor D×N)."""
    T0, cfg, universe, fund, F, ih, usd, reg, comp, cond = (ctx[k] for k in ("T0", "cfg", "universe", "fund", "F", "ih", "usd", "reg", "comp", "cond"))
    c_all, idx, liq = ctx["c_all"], ctx["idx"], ctx["liq"]
    ir = cfg["idx_rules"]
    fb, fsl = float(ir["fee_buy"]), float(ir["fee_sell"])
    fee = fb + fsl
    eq0 = float(cfg["backtest"].get("initial_equity", 10_000_000))
    s_cfg = cfg["signal"]
    rk = float(cfg.get("portfolio_defaults", {}).get("risk_per_trade", 0.01))
    if rk > 0.5:
        rk /= 100.0
    c, o, h, l = c_all[T], F["o"][T], F["h"][T], F["l"][T]
    lr = np.log(c / c.shift(1))
    rs = c.pct_change().clip(-0.35, 0.35)
    m = ih.pct_change()
    N, D = len(T), len(idx)
    V = {k: np.full((D, N), np.nan) for k in KEYS}

    # ---------- beta (CAPM 1 th) & sisi turun — jumlah bergulir ----------
    def roll_beta(mask):
        y = rs.where(mask)
        x = pd.DataFrame(np.where(y.notna(), m.values[:, None], np.nan), index=idx, columns=T)
        n = y.notna().rolling(250, min_periods=60).sum()
        sx, sy = x.rolling(250, min_periods=60).sum(), y.rolling(250, min_periods=60).sum()
        sxy, sxx = (x * y).rolling(250, min_periods=60).sum(), (x * x).rolling(250, min_periods=60).sum()
        den = n * sxx - sx ** 2
        return ((n * sxy - sx * sy) / den.where(den > 0)).values
    allm = pd.DataFrame(True, index=idx, columns=T)
    beta = roll_beta(allm)
    gate = (ih > ih.rolling(200).mean()).values
    vb = np.where(gate[:, None], np.where(beta > 1.2, 1, 0), np.where(beta > 1.2, -1, np.where(beta < 0.8, 1, 0)))
    V["beta"] = np.where(np.isfinite(beta), vb, np.nan)
    dnm = pd.DataFrame(np.repeat((m < 0).values[:, None], N, 1), index=idx, columns=T)
    upm = pd.DataFrame(np.repeat((m > 0).values[:, None], N, 1), index=idx, columns=T)
    bd, bu = roll_beta(dnm), roll_beta(upm)
    rr = bd / np.where(np.abs(bu) > 1e-9, bu, 1e-9)
    V["downside"] = np.where(np.isfinite(rr), np.where(rr > 1.15, -1, np.where(rr < 0.85, 1, 0)), np.nan)
    P(f"beta selesai {time.time() - T0:.0f} dtk")

    # ---------- drawdown 3 th, lompatan & ARA 1 th ----------
    ddn = (c / c.rolling(750, min_periods=250).max() - 1).values
    V["dd"] = np.where(np.isfinite(ddn), np.where(ddn > -0.1, 1, np.where(ddn < -0.3, -1, 0)), np.nan)
    rv = (lr ** 2).rolling(250, min_periods=121).sum()
    bv = (np.pi / 2) * (lr.abs() * lr.abs().shift(1)).rolling(250, min_periods=121).sum()
    jmp = ((rv - bv).clip(lower=0) / rv.where(rv > 0)).values
    lim = pd.DataFrame(_ara_vec(c.shift(1).values), index=idx, columns=T)
    ara = ((rs >= lim - 0.005) & c.shift(1).notna()).rolling(250, min_periods=121).sum().values
    V["jump"] = np.where(np.isfinite(jmp), np.where((ara >= 3) | (jmp > 0.3), -1, np.where((ara == 0) & (jmp < 0.1), 1, 0)), np.nan)

    # ---------- GJR-GARCH & HMM: fit ulang tiap kuartal, filter harian ----------
    qtr = idx.to_period("Q")
    starts = [i for i in range(1, D) if qtr[i] != qtr[i - 1]]
    S1 = np.full((D, N), np.nan)
    LR = np.full((D, N), np.nan)
    HM = np.full((D, N), np.nan)
    HOK = np.zeros((D, N), bool)
    lrv = lr.values
    t1 = time.time()
    for qi, i0p in enumerate(starts):
        i0 = i0p - 1
        if i0 < 400:
            continue
        i1 = starts[qi + 1] if qi + 1 < len(starts) else D
        st = max(0, i0 - 1499)
        try:
            Pg = VM.fit(lr.iloc[st:i0 + 1])
        except Exception:  # noqa: BLE001
            Pg = {}
        if Pg:
            js = [j for j, t in enumerate(T) if t in Pg]
            A_ = np.array([[Pg[T[j]][k] for k in ("a", "b", "g", "w", "v0", "mu")] for j in js])
            a_, b_, g_, w_, v0_, mu_ = A_.T
            s2 = v0_.copy()
            for t in range(st, i1):
                rr_ = lrv[t, js]
                ok = np.isfinite(rr_) & (np.abs(rr_) < 0.35)
                e = np.where(ok, rr_ - mu_, 0.0)
                s2 = np.where(ok, w_ + (a_ + g_ * (e < 0)) * e ** 2 + b_ * s2, s2)
                if t >= i0p:
                    S1[t, js] = np.sqrt(s2)
                    LR[t, js] = np.sqrt(v0_) * ANN
        hs = max(0, i0 - 749)
        try:
            Ph = _hmm_params(lr.iloc[hs:i0 + 1], iters=25)
        except Exception:  # noqa: BLE001
            Ph = {}
        if Ph:
            js = [j for j, t in enumerate(T) if t in Ph]
            mu = np.array([Ph[T[j]][0] for j in js])
            var = np.array([Ph[T[j]][1] for j in js])
            A = np.array([Ph[T[j]][2] for j in js])
            al = np.array([Ph[T[j]][3] for j in js])
            sep = var[:, 1] / np.maximum(var[:, 0], 1e-12) >= 1.69
            for t in range(hs, i1):
                x = lrv[t, js]
                ok = np.isfinite(x) & (np.abs(x) < 0.35)
                pr = np.einsum("ni,nij->nj", al, A)
                bb = np.exp(-0.5 * (np.where(ok, x, 0)[:, None] - mu) ** 2 / var) / np.sqrt(2 * np.pi * var)
                al = np.where(ok[:, None], pr * np.maximum(bb, 1e-300), pr)
                al /= al.sum(1, keepdims=True)
                if t >= i0p:
                    HM[t, js] = al[:, 1]
                    HOK[t, js] = sep
        if qi % 8 == 0:
            P(f"  kuartal {qtr[i0p]} ({time.time() - t1:.0f} dtk)")
    r_ = S1 * ANN / LR
    V["vol"] = np.where(np.isfinite(r_), np.where(r_ < 0.9, 1, np.where(r_ > 1.2, -1, 0)), np.nan)
    V["hmm"] = np.where(np.isfinite(HM), np.where(~HOK, 0, np.where(HM < 0.3, 1, np.where(HM > 0.7, -1, 0))), np.nan)
    P(f"GARCH & HMM kuartalan selesai {time.time() - t1:.0f} dtk")

    # ---------- alfa 4 faktor (mingguan), perilaku harga & VaR99 (bulanan) ----------
    try:
        fac = QM.factors(F, ih, fund, days=D - 270).reindex(idx).values
    except Exception as e:  # noqa: BLE001
        fac = None
        P("faktor dilewati", e)
    ma50 = F["ma50"][T]
    rsv = rs.values
    wk = [i for i in range(1, D) if idx[i].isocalendar()[1] != idx[i - 1].isocalendar()[1]]
    mo = [i for i in range(1, D) if idx[i].month != idx[i - 1].month]
    t1 = time.time()
    for j, t in enumerate(T):
        if fac is not None:
            for i in wk:
                if i < 300:
                    continue
                ff = QM._ols(rsv[i - 249:i + 1, j], fac[i - 249:i + 1])
                if ff:
                    ta = ff[1][0]
                    V["alpha"][i, j] = 1 if ta >= 1.96 else -1 if ta <= -1.96 else 0
        for i in mo:
            if i < 300:
                continue
            lo = max(0, i - 800)
            try:
                b = QM.behavior(c[t].iloc[lo:i + 1], ma50[t].iloc[lo:i + 1])
                if b.get("label"):
                    upd, z = (b.get("dev") or 0) > 0, b.get("dev_z") or 0
                    V["beh"][i, j] = (1 if upd else -1) if b["label"] == "trending" else (-1 if z > 1 else 1 if z < -1 else 0) if b["label"] == "mean-reverting" else 0
            except Exception:  # noqa: BLE001
                pass
            x = lrv[max(0, i - 749):i + 1, j]
            x = x[np.isfinite(x) & (np.abs(x) < 0.35)]
            if len(x) >= 250:
                loss = -x
                u = np.quantile(loss, 0.95)
                ex = loss[loss > u] - u
                v99 = None
                if len(ex) >= 20:
                    xi, sig = QM._gpd_pwm(ex)
                    if xi is not None and xi < 0.9:
                        nn, nu = len(loss), len(ex)
                        v99 = u + sig / xi * (((nn / nu) * 0.01) ** (-xi) - 1) if abs(xi) > 1e-6 else u - sig * np.log((nn / nu) * 0.01)
                if v99 is None:
                    v99 = np.quantile(loss, 0.99)
                V["tail"][i, j] = 1 if v99 < 0.05 else -1 if v99 > 0.08 else 0
    for k in ("alpha", "beh", "tail"):
        V[k] = pd.DataFrame(V[k], index=idx).ffill(limit=70 if k != "alpha" else 10).values
    P(f"alfa/perilaku/ekor selesai {time.time() - t1:.0f} dtk")

    # ---------- likuiditas (posisi Rp10 jt penuh) ----------
    hl2 = np.log(h / l) ** 2
    bcs = hl2 + hl2.shift(1)
    gam = np.log(np.maximum(h, h.shift(1)) / np.minimum(l, l.shift(1))) ** 2
    kk = 3 - 2 * np.sqrt(2)
    alp = (np.sqrt(2 * bcs) - np.sqrt(bcs)) / kk - np.sqrt(gam / kk)
    cs60 = (2 * (np.exp(alp) - 1) / (1 + np.exp(alp))).clip(lower=0).rolling(60, min_periods=30).mean().values
    adv20 = F["value"][T].rolling(20, min_periods=10).mean().values
    part = eq0 / np.where(adv20 > 0, adv20, np.nan)
    cost = 2 * S1 * np.sqrt(part) + np.nan_to_num(cs60) + fee
    V["liq"] = np.where(np.isfinite(part), np.where((part < 0.05) & (~np.isfinite(cost) | (cost < 0.008)), 1,
                                                     np.where((part > 0.2) | (np.isfinite(cost) & (cost > 0.015)), -1, 0)), np.nan)

    # ---------- peluang historis & Kelly rencana per kondisi sinyal (hasil yang sudah diketahui) ----------
    Y = PR._targets(F, cfg)
    L_all = liq.values
    ent = cond["entry"].fillna(False).values.astype(bool) & L_all
    stg = cond["strong"].fillna(False).values.astype(bool) & ent
    exm = cond["exit"].fillna(False).values.astype(bool) & L_all & ~ent
    masks = {"strong": stg, "buy": ent & ~stg, "exit": exm, "none": L_all & ~ent & ~exm, "all": L_all}
    ES = {}
    for key, msk in masks.items():
        for name, hz in (("up20", 20), ("tp1", 60), ("sl1", 60)):
            y = Y[name]
            ok = msk & np.isfinite(y)
            cs_ = np.cumsum(np.where(ok, y, 0).sum(1))
            cn_ = np.cumsum(ok.sum(1))
            sh = np.full(D, np.nan)
            sh[hz:] = cs_[:-hz] / np.maximum(cn_[:-hz], 1)
            sh[hz:][cn_[:-hz] < 200] = np.nan
            ES[(key, name)] = sh
    col = [list(c_all.columns).index(t) for t in T]
    atr = F["atr14"][T].values
    cv = c.values
    for j, jj in enumerate(col):
        stt = np.where(masks["strong"][:, jj], "strong", np.where(masks["buy"][:, jj], "buy", np.where(masks["exit"][:, jj], "exit", "none")))
        for key in ("strong", "buy", "exit", "none"):
            sel = stt == key
            u20, a20 = ES[(key, "up20")], ES[("all", "up20")]
            dlt = u20 - a20
            V["prob"][sel, j] = np.where(np.isfinite(dlt[sel]), np.where(dlt[sel] > 0.03, 1, np.where(dlt[sel] < -0.02, -1, 0)), np.nan)
            tp, sl = ES[(key, "tp1")][sel], ES[(key, "sl1")][sel]
            R_ = s_cfg["atr_stop_mult"] * atr[sel, j]
            fr = fee / (R_ / cv[sel, j])
            bb = float(s_cfg["tp1_r"]) - fr
            Lr = 1 + fr
            ks = np.full(sel.sum(), np.nan)
            for n_, (p_, q_, b_, l_) in enumerate(zip(tp, sl, bb, Lr)):
                if np.isfinite(p_) and np.isfinite(q_) and np.isfinite(b_):
                    kq = QM._kelly3(p_, q_, b_, l_)
                    if kq is not None:
                        ks[n_] = 1 if kq > 0.005 else -1 if kq < 0 else 0
            V["kplan"][sel, j] = ks

    # ---------- Kelly model: dari trade backtest model yang sudah selesai ----------
    _, det = backtest.run(F, comp, cond, reg, cfg, detail=True)
    tr = det["trades"].sort_values("d1")
    kmod = np.full(D, -1.0)
    d1 = pd.DatetimeIndex(tr["d1"]).values
    rets = tr["ret"].values
    for i in range(D):
        k_ = np.searchsorted(d1, idx[i].to_datetime64(), side="right")
        if k_ >= 30:
            x = rets[:k_]
            win = (x > 0).mean()
            aw, al_ = x[x > 0].mean() if (x > 0).any() else 0, -x[x <= 0].mean() if (x <= 0).any() else 0
            full = win - (1 - win) / (aw / al_) if al_ > 0 and aw > 0 else None
            fr = rk / full if full and full > 0 else None
            kmod[i] = 1 if fr is not None and fr <= 0.5 else -1 if fr is None or fr > 1 else 0
    V["kmodel"] = np.repeat(kmod[:, None], N, 1)

    # ---------- sentimen (aturan lolos uji) ----------
    try:
        SP = SR.stock_proxies(F, ih, {t: (universe.get(t) or {}).get("sector") for t in c_all.columns})
        Zs = {k: SR._xs_z(v, liq) for k, v in SP.items()}
        scs = SR.stock_scores(Zs, liq, np.log(c_all.shift(-20) / c_all).clip(-1.5, 1.5))
        p_ew = scs["ew"].rank(axis=1, pct=True)[T].values
        p_rd = scs["ridge"].rank(axis=1, pct=True)[T].values
        ext = SP["ext20"]
        hot = ((ext >= 2) & (ext.where(liq).rank(axis=1, pct=True) >= 0.9))[T].values
        bad = hot | (p_ew <= 0.2) | (p_rd <= 0.2)
        good = p_rd >= 0.8
        V["sent"] = np.where(np.isfinite(p_rd), np.where(bad, -1, np.where(good, 1, 0)), np.nan)
    except Exception as e:  # noqa: BLE001
        P("sentimen dilewati", e)

    S_ = np.zeros((D, N))
    navail = np.zeros((D, N))
    for k in KEYS:
        S_ += np.nan_to_num(V[k])
        navail += np.isfinite(V[k])
    S_ = np.where(navail >= 10, S_, np.nan)
    P(f"skor QM harian siap ({time.time() - T0:.0f} dtk) · model per hari rata-rata {np.nanmean(np.where(navail > 0, navail, np.nan)):.1f}")
    return dict(V=V, S=S_, navail=navail, c=c, o=o, h=h)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    ctx = setup(a.demo, a.cache, a.config)
    T0, cfg, now, universe, fund, F, usd = (ctx[k] for k in ("T0", "cfg", "now", "universe", "fund", "F", "usd"))
    c_all, idx, liq = ctx["c_all"], ctx["idx"], ctx["liq"]
    T = [t for t in c_all.columns if bool(liq[t].iloc[-1])]
    if a.limit:
        T = T[:a.limit]
    P(f"DATA {len(T)} saham likuid · {idx[0].date()}–{idx[-1].date()}")
    ir = cfg["idx_rules"]
    fb, fsl = float(ir["fee_buy"]), float(ir["fee_sell"])
    eq0 = float(cfg["backtest"].get("initial_equity", 10_000_000))
    Q = qm_panel(ctx, T)
    V, S_, c, o, h = Q["V"], Q["S"], Q["c"], Q["o"], Q["h"]
    cv = c.values
    D = len(idx)
    # ---------- harga wajar titik-waktu (sama persis dengan sbtFV di app.js, asumsi bawaan) ----------
    usd_now = float(usd.dropna().iloc[-1]) if usd is not None and usd.notna().any() else None

    def fv_series(t, w=0.11, tg=0.04, coe=0.13, g_fix=None):
        f = fund.get(t) or {}
        A = (f.get("fs") or {}).get("a") or {}
        fx = 1.0 if f.get("cur") in (None, "IDR") else usd_now if f.get("cur") == "USD" else None
        sh = f.get("shares")
        if not A.get("p"):
            return None, "laporan tahunan tidak tersedia"
        if not fx:
            return None, f"mata uang laporan {f.get('cur')} belum didukung"
        if not sh:
            return None, "jumlah saham tidak tersedia"
        fin = (universe.get(t) or {}).get("sector") == "Financials"
        ps = A["p"]
        ends = A.get("end") or [f"{p}-12-31" for p in ps]
        col = lambda k: A.get(k) or [None] * len(ps)  # noqa: E731
        fcf, rev, debt, cash, ni, eq = col("fcf"), col("rev"), col("debt"), col("cash"), col("ni"), col("eq")
        fv = np.full(D, np.nan)
        any_ = False
        for i in range(len(ps)):
            v = None
            if not fin:
                hist = [x for x in fcf[max(0, i - 2):i + 1] if x is not None]
                base = float(np.mean(hist)) if hist else None
                if g_fix is None:
                    rv_ = [(int(str(ps[k])[:4]), rev[k]) for k in range(i + 1) if rev[k] and rev[k] > 0]
                    g = 0.08
                    if len(rv_) >= 2 and rv_[-1][0] > rv_[0][0]:
                        g = (rv_[-1][1] / rv_[0][1]) ** (1 / (rv_[-1][0] - rv_[0][0])) - 1
                    g = round(max(0.02, min(0.15, g)), 2)
                else:
                    g = g_fix
                nd = ((debt[i] or 0) - (cash[i] or 0)) * fx if (debt[i] is not None or cash[i] is not None) else 0.0
                if base and base > 0 and w - tg >= 0.02:
                    cc_, pv = base * fx, 0.0
                    for k in range(1, 6):
                        cc_ *= 1 + g
                        pv += cc_ / (1 + w) ** k
                    vv = (pv + cc_ * (1 + tg) / (w - tg) / (1 + w) ** 5 - nd) / sh
                    v = vv if vv > 0 else None
            if v is None and eq[i] and eq[i] > 0 and ni[i] is not None:
                roe = ni[i] / eq[i]
                if roe > tg and coe - tg >= 0.02:
                    v = eq[i] * fx / sh * (roe - tg) / (coe - tg)
            if v is not None and v > 0:
                ai = int(np.searchsorted(idx, pd.Timestamp(ends[i]) + pd.Timedelta(days=95)))
                if ai < D:
                    fv[ai:] = v
                    any_ = True
        return (fv, None) if any_ else (None, "harga wajar tidak bisa dihitung (arus kas & ROE tidak mendukung)")

    def sim_fv(o_, h_, c_, fv, sc=None, mos=0.0):
        cash, shs, pend, cur, trades = eq0, 0, False, None, []
        eqv = np.full(D, np.nan)
        start = None
        for t in range(D):
            if pend and shs == 0:
                px = o_[t] if np.isfinite(o_[t]) and o_[t] > 0 else c_[t]
                lots = int(cash // (px * 100 * (1 + fb))) if np.isfinite(px) and px > 0 else 0
                if lots > 0:
                    shs = lots * 100
                    cur = {"d0": str(idx[t].date()), "p0": float(px), "c0": shs * px * (1 + fb)}
                    cash -= cur["c0"]
                pend = False
            if shs > 0 and np.isfinite(fv[t]) and fv[t] > 0:
                sp = o_[t] if np.isfinite(o_[t]) and o_[t] >= fv[t] else fv[t] if np.isfinite(h_[t]) and h_[t] >= fv[t] else None
                if sp:
                    cash += shs * sp * (1 - fsl)
                    cur.update({"d1": str(idx[t].date()), "p1": float(sp), "ret": shs * sp * (1 - fsl) / cur["c0"] - 1,
                                "days": int((idx[t] - pd.Timestamp(cur["d0"])).days)})
                    trades.append(cur)
                    cur, shs = None, 0
            if np.isfinite(c_[t]):
                eqv[t] = cash + shs * c_[t]
            ok = np.isfinite(fv[t]) and fv[t] > 0 and (sc is None or np.isfinite(sc[t]))
            if ok and start is None:
                start = t
            if shs == 0 and not pend and ok and np.isfinite(c_[t]) and c_[t] < fv[t] * (1 - mos) and (sc is None or sc[t] > 0):
                pend = True
        if cur is not None:
            last = c_[np.isfinite(c_)][-1]
            cur.update({"d1": None, "p1": float(last), "ret": shs * last * (1 - fsl) / cur["c0"] - 1,
                        "days": int((idx[-1] - pd.Timestamp(cur["d0"])).days), "open": True})
            trades.append(cur)
        return eqv, trades, start

    def sim_qm(o_, c_, sc, ok=None):
        """Aturan v0.27: beli saat skor QM > 0 (dan syarat batas minimum terpenuhi), jual saat skor < 0 (atau syarat gugur)."""
        cash, shs, pend, cur, trades = eq0, 0, None, None, []
        eqv = np.full(D, np.nan)
        start = None
        for t in range(D):
            if pend is not None:
                px = o_[t] if np.isfinite(o_[t]) and o_[t] > 0 else c_[t]
                if pend == 1 and shs == 0 and np.isfinite(px) and px > 0:
                    lots = int(cash // (px * 100 * (1 + fb)))
                    if lots > 0:
                        shs = lots * 100
                        cur = {"d0": str(idx[t].date()), "p0": float(px), "c0": shs * px * (1 + fb)}
                        cash -= cur["c0"]
                elif pend == 0 and shs > 0 and np.isfinite(px) and px > 0:
                    cash += shs * px * (1 - fsl)
                    cur.update({"d1": str(idx[t].date()), "p1": float(px), "ret": shs * px * (1 - fsl) / cur["c0"] - 1,
                                "days": int((idx[t] - pd.Timestamp(cur["d0"])).days)})
                    trades.append(cur)
                    cur, shs = None, 0
                pend = None
            if np.isfinite(c_[t]):
                eqv[t] = cash + shs * c_[t]
            if not np.isfinite(sc[t]):
                continue
            if start is None:
                start = t
            good = ok is None or ok[t]
            if shs == 0 and sc[t] > 0 and good:
                pend = 1
            elif shs > 0 and (sc[t] < 0 or not good):
                pend = 0
        if cur is not None:
            last = c_[np.isfinite(c_)][-1]
            cur.update({"d1": None, "p1": float(last), "ret": shs * last * (1 - fsl) / cur["c0"] - 1,
                        "days": int((idx[-1] - pd.Timestamp(cur["d0"])).days), "open": True})
            trades.append(cur)
        return eqv, trades, start

    # ---------- keluaran per saham: data harian untuk simulasi di browser + ringkasan asumsi bawaan ----------
    OUT.mkdir(parents=True, exist_ok=True)
    for p_ in OUT.glob("*.json"):
        p_.unlink()
    i0 = int(np.searchsorted(idx, pd.Timestamp("2017-01-01")))
    enc = lambda arr: "".join("." if not np.isfinite(x) else "+" if x > 0 else "-" if x < 0 else "0" for x in arr)  # noqa: E731
    ov, hv = o.values, h.values
    summ = {}
    t1 = time.time()
    for j, t in enumerate(T):
        cj, oj, hj = cv[:, j], ov[:, j], hv[:, j]
        sc = S_[:, j]
        fvh, why = fv_series(t)
        res = {"t": t, "asof": str(idx[-1].date()), "eq0": eq0, "fb": fb, "fs": fsl, "d": [str(x.date()) for x in idx[i0:]],
               "o": [None if not np.isfinite(x) else round(float(x)) for x in oj[i0:]], "h": [None if not np.isfinite(x) else round(float(x)) for x in hj[i0:]],
               "c": [None if not np.isfinite(x) else round(float(x)) for x in cj[i0:]],
               "vs": {k: enc(V[k][i0:, j]) for k in KEYS}}
        row = {"qm_now": None if not np.isfinite(sc[-1]) else int(sc[-1]), "why": why}
        eqv, trades, start = sim_qm(oj, cj, sc)
        stt = stats(idx, eqv, trades, start, oj, cj, eq0)
        if stt:
            row["qm"] = stt
        if fvh is not None:
            eqv, trades, start = sim_fv(oj, hj, cj, fvh, None)
            stt = stats(idx, eqv, trades, start, oj, cj, eq0)
            if stt:
                row["dcf"] = stt
            row["fv_now"] = _f(fvh[-1], 0)
        (OUT / f"{t}.json").write_text(json.dumps(res, separators=(",", ":")))
        summ[t] = row
    P(f"simulasi {len(summ)} saham {time.time() - t1:.0f} dtk")

    def agg(k):
        xs = [v[k] for v in summ.values() if v.get(k)]
        if not xs:
            return {}
        cg = np.array([x["cagr"] for x in xs if x.get("cagr") is not None])
        bh = np.array([x["bh_cagr"] for x in xs if x.get("cagr") is not None and x.get("bh_cagr") is not None])
        cg2 = np.array([x["cagr"] for x in xs if x.get("cagr") is not None and x.get("bh_cagr") is not None])
        md = np.array([x["mdd"] for x in xs if x.get("mdd") is not None])
        bmd = np.array([x["bh_mdd"] for x in xs if x.get("mdd") is not None and x.get("bh_mdd") is not None])
        tr = np.array([x["trades"] for x in xs])
        return {"n": len(xs), "cagr_med": _f(np.median(cg)) if len(cg) else None, "bh_med": _f(np.median(bh)) if len(bh) else None,
                "beat": _f((cg2 > bh).mean(), 3) if len(bh) else None, "pos": _f((cg > 0).mean(), 3) if len(cg) else None,
                "mdd_med": _f(np.median(md)) if len(md) else None, "bh_mdd_med": _f(np.median(bmd)) if len(bmd) else None,
                "trades_med": _f(np.median(tr), 1), "notrade": int((tr == 0).sum())}
    meta = {"asof": str(idx[-1].date()), "run": str(now.date()), "eq0": eq0, "n": len(summ), "minutes": round((time.time() - T0) / 60, 1),
            "qm": agg("qm"), "dcf": agg("dcf"), "demo": bool(a.demo), "rule": "QM: beli saat skor > 0, jual saat < 0 (tanpa batas minimum). DCF: beli saja, jual di harga wajar; asumsi bawaan WACC 11%, terminal 4%, biaya ekuitas 13%, margin 0%"}
    (OUT / "_summary.json").write_text(json.dumps({"meta": meta, "stocks": summ}, separators=(",", ":")))
    P("RINGKASAN QM saja:", json.dumps(meta["qm"]))
    P("RINGKASAN DCF:", json.dumps(meta["dcf"]))
    P(f"SELESAI {meta['minutes']} menit")


if __name__ == "__main__":
    main()
