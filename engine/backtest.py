"""Backtest walk-forward aturan sinyal (tanpa sentimen, karena histori berita tidak tersedia).
Eksekusi realistis: sinyal di close hari t -> eksekusi di OPEN t+1. Stop default berbasis CLOSE
(keluar besok pagi jika close <= stop) karena stop intraday rawan kena 'wick'; mode 'intraday'
tersedia di config. Fee beli/jual BEI, lot 100 lembar, slot posisi dibatasi rezim pasar."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from .idx_rules import ara_pct, round_tick


def run(F: dict, comp: pd.DataFrame, cond: dict, reg: pd.DataFrame, cfg: dict, equity0: float | None = None,
        detail: bool = False):
    """Simulasi portofolio. Aturan risiko dibaca dari cfg["backtest"]:
      sizing            equal | risk  (risk = modal x risk_per_trade / jarak stop, dibatasi max_weight)
      realistic_fills   tidak bisa beli saat terkunci ARA / tanpa transaksi, tidak bisa jual saat terkunci ARB
      weight_cap        posisi yang membengkak > cap x 1,25 dipangkas kembali ke cap
      tighten_after_r   setelah untung >= N x risiko awal, trailing stop dirapatkan ke tight_trail_atr x ATR
      partial_tp_r      jual sebagian (partial_tp_frac) saat untung >= N x risiko awal
      cooldown_days     jeda beli ulang saham yang baru kena stop
      dd_brake          saat drawdown portofolio > X, jumlah slot dipangkas separuh
    detail=True -> (hasil, rincian harian) untuk engine.diagnose."""
    bt, s = cfg["backtest"], cfg["signal"]
    equity0 = float(equity0 if equity0 is not None else bt.get("initial_equity", 100_000_000))
    fee_b, fee_s = cfg["idx_rules"]["fee_buy"], cfg["idx_rules"]["fee_sell"]
    lot = cfg["idx_rules"]["lot_size"]
    maxpos = int(bt["max_positions"])
    expo = cfg["regime_exposure"]
    sizing = bt.get("sizing", "equal")
    risk_pct, max_w = float(bt.get("risk_per_trade", 0.01)), float(bt.get("max_weight", 0.20))
    realistic = bool(bt.get("realistic_fills", False))
    wcap = bt.get("weight_cap")
    tighten_r, tight_mult = bt.get("tighten_after_r"), float(bt.get("tight_trail_atr", 2.0))
    ptp_r, ptp_frac = bt.get("partial_tp_r"), float(bt.get("partial_tp_frac", 0.5))
    cooldown = int(bt.get("cooldown_days") or 0)
    dd_brake = bt.get("dd_brake")
    stop_mode = s.get("stop_mode", "close")

    c = F["c"]
    dates = c.index
    # mulai saat cukup banyak saham punya histori (10 th lalu jumlah emiten jauh lebih sedikit dari sekarang)
    ready = (F["mom_6_1"].notna() & F["ma200"].notna()).sum(axis=1) >= max(5, min(40, int(0.5 * c.shape[1])))
    start_i = int(np.argmax(ready.values)) if ready.any() else 200
    first = dates[-1] - pd.Timedelta(days=int(float(bt["years"]) * 365.25))     # tepat N tahun kalender ke belakang
    start_i = max(start_i, int(dates.searchsorted(first)))
    tick = list(c.columns)
    C, O, H, L, V = c.values, F["o"].values, F["h"].values, F["l"].values, F["v"].values
    ENT, STR, EXT = cond["entry"].values, cond["strong"].values, cond["exit"].values
    COMP, ATR, CH, HH = comp.values, F["atr14"].values, F["chandelier"].values, F["hh22"].values
    if cond.get("trail") is not None:                 # riset: trailing stop alternatif (mis. Parabolic SAR)
        CH = cond["trail"].reindex(index=c.index, columns=c.columns).values
    SM = None
    if cond.get("slot_mult") is not None:             # riset: pengali jumlah slot per hari (mis. gerbang bertahap)
        SM = pd.Series(cond["slot_mult"]).reindex(c.index).fillna(0).values
    REG = reg["label"].values

    cash, peak = equity0, equity0
    pos: dict[int, dict] = {}
    equity, trades, xtr, rows, attrib = [], [], [], [], []
    pending_exit: dict[int, str] = {}
    pending_trim: dict[int, tuple] = {}
    pending_entry: list[int] = []
    last_stop: dict[int, int] = {}
    n_entry = n_nolot = n_nofill = 0
    day: dict = defaultdict(float)

    def no_sell(i, j):     # tidak ada transaksi / terkunci ARB seharian -> tidak ada pembeli
        return realistic and (V[i, j] <= 0 or (H[i, j] == L[i, j] and C[i, j] <= C[i - 1, j] * 0.935))

    def no_buy(i, j, px):  # tidak ada transaksi / dibuka di batas ARA -> antrean beli tidak kebagian
        return realistic and (V[i, j] <= 0 or px >= C[i - 1, j] * (1 + ara_pct(C[i - 1, j]) - 0.01))

    def sell(i, j, shares, px, why):
        nonlocal cash
        p = pos[j]
        got = shares * px * (1 - fee_s)
        cost = shares * p["entry"] * (1 + fee_b)
        part = p["mark"] * shares / p["sh"]
        cash += got
        day[j] += got - part
        trades.append({"ticker": tick[j], "entry_date": p["d0"].strftime("%Y-%m-%d"), "exit_date": dates[i].strftime("%Y-%m-%d"),
                       "entry": float(p["entry"]), "exit": float(px), "ret": round(float(got / cost - 1), 4),
                       "days": int(np.busday_count(p["d0"].date(), dates[i].date())), "reason": why})
        if detail:
            xtr.append({"t": tick[j], "d0": p["d0"], "d1": dates[i], "ret": got / cost - 1, "pnl": got - cost,
                        "w": p["w"] * shares / p["sh0"], "stopdist": p["stopdist"], "atrp": p["atrp"], "why": why, "eq0": p["eq0"]})
        p["mark"] -= part
        p["sh"] -= shares
        if p["sh"] <= 0:
            pos.pop(j)
            if why.startswith("stop"):
                last_stop[j] = i

    for i in range(start_i, len(dates)):
        day = defaultdict(float)
        # 1) eksekusi order dari sinyal kemarin di harga OPEN hari ini
        for j, why in list(pending_exit.items()):
            if j not in pos:
                pending_exit.pop(j)
            elif not no_sell(i, j):
                pending_exit.pop(j)
                sell(i, j, pos[j]["sh"], O[i, j], why)
        for j, (k, why) in list(pending_trim.items()):
            pending_trim.pop(j)
            if j in pos and j not in pending_exit and not no_sell(i, j):
                k = min(k, pos[j]["sh"] - lot)
                if k > 0:
                    sell(i, j, k, O[i, j], why)
        eq_open = cash + sum(p["sh"] * O[i, j] for j, p in pos.items())
        for j in pending_entry:
            if j in pos or len(pos) >= maxpos:
                continue
            px = O[i, j]
            stop = round_tick(C[i - 1, j] - s["atr_stop_mult"] * ATR[i - 1, j], "down")
            if not np.isfinite(px) or px <= stop:
                continue
            if no_buy(i, j, px):
                n_nofill += 1
                continue
            if sizing == "risk":
                sh = min(eq_open * risk_pct / (px - stop), eq_open * max_w / px, cash / (px * (1 + fee_b)))
            else:
                sh = min(eq_open / maxpos, cash) / (px * (1 + fee_b))
            sh = math.floor(sh / lot) * lot
            n_entry += 1
            if sh <= 0:
                n_nolot += 1
                continue
            cost = sh * px * (1 + fee_b)
            cash -= cost
            pos[j] = {"sh": sh, "sh0": sh, "entry": px, "d0": dates[i], "stop": stop, "i0": i, "R0": px - stop, "mark": cost,
                      "tight": False, "tp": False, "w": cost / eq_open, "stopdist": (px - stop) / px,
                      "atrp": ATR[i - 1, j] / C[i - 1, j], "eq0": eq_open}
        pending_entry = []

        # 2) stop loss intraday (hanya jika stop_mode = intraday; gap down -> keluar di open)
        if stop_mode == "intraday":
            for j in list(pos):
                p = pos[j]
                if p["i0"] < i and L[i, j] <= p["stop"] and not no_sell(i, j):
                    pending_exit.pop(j, None)
                    sell(i, j, p["sh"], min(O[i, j], p["stop"]), "stop loss")

        # 3) mark-to-market & update trailing stop
        eq, unreal, vmax = cash, 0.0, 0.0
        for j, p in pos.items():
            val = p["sh"] * C[i, j]
            day[j] += val - p["mark"]
            p["mark"] = val
            eq += val
            unreal += val - p["sh"] * p["entry"] * (1 + fee_b)
            vmax = max(vmax, val)
            trail = CH[i, j]
            if tighten_r and not p["tight"] and C[i, j] - p["entry"] >= tighten_r * p["R0"]:
                p["tight"] = True
            if p["tight"]:
                t2 = HH[i, j] - tight_mult * ATR[i, j]
                trail = t2 if not np.isfinite(trail) else max(trail, t2)
            if np.isfinite(trail):
                p["stop"] = max(p["stop"], round_tick(trail, "down"))
        equity.append(eq)
        peak = max(peak, eq)
        if detail:
            rows.append((eq, cash, len(pos), unreal / eq, vmax / eq))
            attrib.append(dict(day))

        # 4) sinyal di close -> order besok
        for j, p in pos.items():
            if j in pending_exit:
                continue
            if stop_mode == "close" and C[i, j] <= p["stop"]:
                pending_exit[j] = "stop (close)"
            elif EXT[i, j]:
                pending_exit[j] = "sinyal exit"
            else:
                val = p["sh"] * C[i, j]
                if ptp_r and not p["tp"] and C[i, j] >= p["entry"] + ptp_r * p["R0"]:
                    p["tp"] = True
                    pending_trim[j] = (math.floor(p["sh"] * ptp_frac / lot) * lot, "ambil untung sebagian")
                elif wcap and val > wcap * 1.25 * eq:
                    pending_trim[j] = (math.floor((val - wcap * eq) / C[i, j] / lot) * lot, "pangkas bobot")
        target = int(round(maxpos * expo.get(REG[i], 0.7) * (SM[i] if SM is not None else 1)))
        if dd_brake and eq / peak - 1 < -float(dd_brake):
            target = max(1, target // 2)
        slots = target - (len(pos) - sum(1 for j in pending_exit if j in pos))
        if slots > 0:
            cand = [j for j in range(len(tick)) if ENT[i, j] and j not in pos
                    and (not cooldown or i - last_stop.get(j, -10**9) > cooldown)]
            cand.sort(key=lambda j: (not STR[i, j], -COMP[i, j]))
            pending_entry = cand[:slots]

    eq = pd.Series(equity, index=dates[start_i:])
    bench = reg["ihsg"].iloc[start_i:].ffill().bfill()
    if bench.isna().all() or bench.iloc[0] <= 0:
        bench = pd.Series(equity0, index=eq.index, dtype=float)
    bench = bench / bench.iloc[0] * equity0
    out = _stats(eq, bench, trades, cfg, equity0)
    out["final_equity"] = round(float(eq.iloc[-1]))
    out["lot_skips"] = {"signals": n_entry, "skipped": n_nolot, "nofill": n_nofill}
    out["assumptions"] = _assumptions(cfg, equity0, n_entry, n_nolot, n_nofill)
    liq = F["liquid"].iloc[start_i:]
    out["universe"] = {"liquid_start": int(liq.iloc[:21].sum(axis=1).mean()), "liquid_end": int(liq.iloc[-21:].sum(axis=1).mean())}
    if detail:
        df = pd.DataFrame(rows, index=eq.index, columns=["eq", "cash", "npos", "unreal", "wmax"])
        df["inv"] = 1 - df["cash"] / df["eq"]
        df["reg"] = REG[start_i:]
        df["ihsg"] = reg["ihsg"].iloc[start_i:].ffill().bfill().values
        return out, {"df": df, "trades": pd.DataFrame(xtr), "attrib": attrib, "tick": tick}
    return out


def _assumptions(cfg, equity0, n_entry, n_nolot, n_nofill):
    bt, s, r = cfg["backtest"], cfg["signal"], cfg["idx_rules"]
    rp = lambda x: f"Rp{x:,.0f}".replace(",", ".")  # noqa: E731
    a = ["Sinyal dihitung saat close; eksekusi di harga open hari berikutnya"]
    if bt.get("sizing") == "risk":
        a.append(f"Ukuran posisi berbasis risiko: {bt.get('risk_per_trade', 0.01)*100:g}% modal per trade ÷ jarak stop, "
                 f"maks {bt.get('max_weight', 0.2)*100:g}% modal per saham, maks {bt['max_positions']} posisi")
    else:
        a.append(f"Maks {bt['max_positions']} posisi bobot sama")
    a.append("Slot posisi dikurangi saat rezim NEUTRAL/RISK-OFF")
    stop = f"Stop awal {s['atr_stop_mult']:g}×ATR lalu naik mengikuti chandelier ({s['trail_atr_mult']:g}×ATR)"
    if bt.get("tighten_after_r"):
        stop += f"; setelah untung ≥ {bt['tighten_after_r']:g}R trailing dirapatkan ke {bt.get('tight_trail_atr', 2.0):g}×ATR"
    a.append(stop + ("; dicek di harga CLOSE, keluar di open besok" if s.get("stop_mode", "close") == "close"
                     else "; stop intraday (keluar saat harga menyentuh stop)"))
    if bt.get("weight_cap"):
        a.append(f"Posisi yang membengkak > {bt['weight_cap']*125:g}% modal dipangkas kembali ke {bt['weight_cap']*100:g}%")
    if bt.get("partial_tp_r"):
        a.append(f"Jual {bt.get('partial_tp_frac', 0.5)*100:g}% posisi saat untung ≥ {bt['partial_tp_r']:g}R")
    if s.get("min_mom_score") or s.get("min_flow_score"):
        a.append(f"Beli hanya saham dengan skor momentum ≥ {s.get('min_mom_score') or 0:g} dan skor inflow (akumulasi) ≥ "
                 f"{s.get('min_flow_score') or 0:g}")
    if s.get("market_filter"):
        a.append(f"Beli baru hanya saat IHSG di atas {str(s['market_filter']).upper()}")
    if s.get("max_atr_pct"):
        a.append(f"Saham dengan ATR > {s['max_atr_pct']*100:g}%/hari tidak dibeli (terlalu liar)")
    if bt.get("cooldown_days"):
        a.append(f"Saham yang baru kena stop tidak dibeli ulang selama {bt['cooldown_days']} hari bursa")
    if bt.get("dd_brake"):
        a.append(f"Saat drawdown portofolio > {bt['dd_brake']*100:g}%, jumlah slot dipangkas separuh")
    if bt.get("realistic_fills"):
        a.append(f"Eksekusi realistis: tidak beli saat dibuka di batas ARA / tanpa transaksi ({n_nofill} sinyal batal), "
                 "jual ditunda saat terkunci ARB")
    else:
        a.append("ARA/ARB & antrean tidak dimodelkan (order selalu dianggap terisi)")
    a.append(f"Fee beli {r['fee_buy']*100:.2f}% / jual {r['fee_sell']*100:.2f}%, lot 100 lembar")
    if n_nolot:
        a.append(f"Modal awal {rp(equity0)}: {n_nolot} dari {n_entry} sinyal beli dilewati karena dana tidak cukup untuk 1 lot")
    a += ["Tanpa sentimen (histori berita tidak tersedia) & tanpa dividen",
          "Universe = saham yang MASIH tercatat saat ini; emiten yang delisting/bangkrut dalam 10 tahun terakhir tidak ikut "
          "(survivorship bias) — hasil cenderung optimistis",
          "Aturan BEI dianggap tetap sepanjang periode (fee, lot, batas ARA saat ini)"]
    return a


def _trade(p, d1, px, t, why, fb, fs):
    ret = (px * (1 - fs)) / (p["entry"] * (1 + fb)) - 1
    return {"ticker": t, "entry_date": p["d0"].strftime("%Y-%m-%d"), "exit_date": d1.strftime("%Y-%m-%d"),
            "entry": float(p["entry"]), "exit": float(px), "ret": round(float(ret), 4),
            "days": int(np.busday_count(p["d0"].date(), d1.date())), "reason": why}


def _dd(s):
    return s / s.cummax() - 1


def _yearly(eq, bench, trades):
    """Return per tahun kalender: strategi vs IHSG (tahun pertama/terakhir bisa parsial)."""
    rows = []
    ntr = {}
    for t in trades:
        ntr[t["exit_date"][:4]] = ntr.get(t["exit_date"][:4], 0) + 1
    prev_e, prev_b = float(eq.iloc[0]), float(bench.iloc[0])
    for y, g in eq.groupby(eq.index.year):
        e1, b1 = float(g.iloc[-1]), float(bench[g.index[-1]])
        seg = pd.concat([pd.Series([prev_e]), g])
        rows.append({"year": int(y), "ret": round(e1 / prev_e - 1, 4), "bench": round(b1 / prev_b - 1, 4),
                     "max_dd": round(float((seg / seg.cummax() - 1).min()), 4), "trades": ntr.get(str(y), 0),
                     "partial": bool(g.index[0].month > 1 or (y == eq.index[-1].year and g.index[-1].month < 12))})
        prev_e, prev_b = e1, b1
    return rows


def _stats(eq, bench, trades, cfg, equity0):
    rf = cfg["backtest"]["risk_free_rate"]
    # tahun kalender sebenarnya (BEI ±242 hari bursa/tahun; membagi dengan 252 membuat CAGR sedikit terlalu tinggi)
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ann = len(eq) / yrs

    def pack(s):
        r = s.pct_change().dropna()
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
        vol = r.std() * math.sqrt(ann)
        sharpe = (r.mean() * ann - rf) / vol if vol > 0 else 0
        dn = r[r < 0].std() * math.sqrt(ann)
        sortino = (r.mean() * ann - rf) / dn if dn and dn > 0 else 0
        mdd = _dd(s).min()
        return {"total_return": round(float(s.iloc[-1] / s.iloc[0] - 1), 4), "cagr": round(float(cagr), 4),
                "vol": round(float(vol), 4), "sharpe": round(float(sharpe), 2), "sortino": round(float(sortino), 2),
                "max_dd": round(float(mdd), 4), "calmar": round(float(cagr / abs(mdd)), 2) if mdd < 0 else 0}

    st = pack(eq)
    bs = pack(bench)
    rets = np.array([t["ret"] for t in trades]) if trades else np.array([])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    win = float(len(wins) / len(rets)) if len(rets) else 0
    aw = float(wins.mean()) if len(wins) else 0
    al = float(-losses.mean()) if len(losses) else 0
    payoff = aw / al if al > 0 else 0
    kelly = win - (1 - win) / payoff if payoff > 0 else 0
    kx = _kelly_ext(rets, win, aw, al)
    dr = eq.pct_change().dropna()
    if len(dr) > 250 and dr.var() > 0:                 # Kelly portofolio: leverage optimal seluruh model = (μ − rf) / σ²
        mu_a, var_a = float(dr.mean() * 250), float(dr.var() * 250)
        rf_k = float(rf)
        kx["port"] = round((mu_a - rf_k) / var_a, 2)
        kx["port_mu"], kx["port_vol"], kx["rf"] = round(mu_a, 4), round(var_a ** 0.5, 4), rf_k
    st.update({
        "trades": int(len(rets)), "win_rate": round(win, 3), "avg_win": round(aw, 4), "avg_loss": round(al, 4),
        "payoff": round(payoff, 2),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else 0,
        "avg_days": round(float(np.mean([t["days"] for t in trades])), 1) if trades else 0,
        "expectancy": round(float(rets.mean()), 4) if len(rets) else 0,
    })
    step = max(1, len(eq) // 400)
    ds = eq.index[::step].append(eq.index[-1:]).unique()
    return {
        "start": eq.index[0].strftime("%Y-%m-%d"), "end": eq.index[-1].strftime("%Y-%m-%d"),
        "equity0": int(round(equity0)), "stats": st, "bench": bs,
        "kelly": {"full": round(float(kelly), 3), "half": round(float(max(kelly, 0) / 2), 3), **kx,
                  "note": "Kelly dari win-rate & payoff backtest (per trade, bukan per portofolio). "
                          "Gunakan maksimal half-Kelly; estimasi sangat sensitif terhadap sampel."},
        "dates": [d.strftime("%Y-%m-%d") for d in ds],
        "equity": [round(float(eq[d])) for d in ds],
        "bench_equity": [round(float(bench[d])) for d in ds],
        "drawdown": [round(float(_dd(eq)[d]), 4) for d in ds],
        "yearly": _yearly(eq, bench, trades),
        "trades": trades[-60:][::-1],
        "assumptions": [
            "Sinyal dihitung saat close; eksekusi di harga open hari berikutnya",
            "Stop awal 2xATR lalu naik mengikuti chandelier; dicek pada harga CLOSE, keluar di open besok",
            f"Fee beli {cfg['idx_rules']['fee_buy']*100:.2f}% / jual {cfg['idx_rules']['fee_sell']*100:.2f}%, lot 100 lembar",
            f"Maks {cfg['backtest']['max_positions']} posisi bobot sama; slot dikurangi saat NEUTRAL/RISK-OFF",
            "Tanpa sentimen (histori berita tidak tersedia) & tanpa dividen; ARB/likuiditas antrean tidak dimodelkan",
            "Universe = saham yang MASIH tercatat saat ini; emiten yang delisting/bangkrut dalam 10 tahun terakhir tidak ikut "
            "(survivorship bias) — makin panjang periodenya makin besar biasnya, hasil cenderung optimistis",
            "Aturan BEI dianggap tetap sepanjang periode (fee, lot 100, tanpa perubahan fraksi/ARA-ARB historis)",
        ],
    }


def _kelly_ext(rets: np.ndarray, win: float, aw: float, al: float, nboot: int = 1000) -> dict:
    """Kelly lanjutan dari return per trade (bagian dari nilai posisi).
    risk  = W − (1−W)/b  -> bagian modal yang boleh HILANG per trade (rumus biner klasik)
    pos   = risk / rata-rata rugi -> bagian modal yang ditaruh di satu posisi
    log   = f yang memaksimalkan rata-rata log(1 + f·r) memakai SEBARAN trade sebenarnya (tanpa asumsi biner)
    boot  = persentil 5/50/95 dari bootstrap trade (ketidakpastian estimasi)"""
    if len(rets) < 30:
        return {}
    r = np.clip(rets.astype(float), -0.99, None)
    fmax = min(3.0, 0.99 / max(-r.min(), 1e-6))
    grid = np.linspace(0, fmax, 301)
    G = np.log1p(np.outer(grid, r)).mean(1)
    i = int(np.argmax(G))
    rng = np.random.default_rng(42)
    bl, br = [], []
    for _ in range(nboot):
        x = r[rng.integers(0, len(r), len(r))]
        gx = np.log1p(np.outer(grid, x)).mean(1)
        bl.append(grid[int(np.argmax(gx))])
        w = (x > 0).mean()
        a_w, a_l = (x[x > 0].mean() if (x > 0).any() else 0), (-x[x <= 0].mean() if (x <= 0).any() else 0)
        br.append(w - (1 - w) / (a_w / a_l) if a_w > 0 and a_l > 0 else 0)
    pts = np.linspace(0, min(fmax, max(grid[i] * 2.5, 0.2)), 26)
    curve = [[round(float(f), 3), round(float(np.log1p(f * r).mean()), 5)] for f in pts]
    kr = win - (1 - win) / (aw / al) if aw > 0 and al > 0 else 0
    return {"n": int(len(r)), "pos": round(float(kr / al), 3) if al > 0 else None, "log": round(float(grid[i]), 3),
            "g_log": round(float(G[i]), 5), "boot_risk": [round(float(np.percentile(br, q)), 3) for q in (5, 50, 95)],
            "boot_log": [round(float(np.percentile(bl, q)), 3) for q in (5, 50, 95)], "curve": curve,
            "p_neg": round(float(np.mean(np.array(br) <= 0)), 3)}
