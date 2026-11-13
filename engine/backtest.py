"""Backtest walk-forward aturan sinyal (tanpa sentimen, karena histori berita tidak tersedia).
Eksekusi realistis: sinyal di close hari t -> eksekusi di OPEN t+1. Stop default berbasis CLOSE
(keluar besok pagi jika close <= stop) karena stop intraday rawan kena 'wick'; mode 'intraday'
tersedia di config. Fee beli/jual BEI, lot 100 lembar, slot posisi dibatasi rezim pasar."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .idx_rules import round_tick


def run(F: dict, comp: pd.DataFrame, cond: dict, reg: pd.DataFrame, cfg: dict, equity0: float | None = None):
    bt = cfg["backtest"]
    equity0 = float(equity0 if equity0 is not None else bt.get("initial_equity", 100_000_000))
    s = cfg["signal"]
    fee_b, fee_s = cfg["idx_rules"]["fee_buy"], cfg["idx_rules"]["fee_sell"]
    lot = cfg["idx_rules"]["lot_size"]
    maxpos = bt["max_positions"]
    expo = cfg["regime_exposure"]

    c, o, l = F["c"], F["o"], F["l"]
    dates = c.index
    # mulai saat cukup banyak saham punya histori (10 th lalu jumlah emiten jauh lebih sedikit dari sekarang)
    ready = (F["mom_6_1"].notna() & F["ma200"].notna()).sum(axis=1) >= max(5, min(40, int(0.5 * c.shape[1])))
    start_i = int(np.argmax(ready.values)) if ready.any() else 200
    first = dates[-1] - pd.Timedelta(days=int(float(bt["years"]) * 365.25))     # tepat N tahun kalender ke belakang
    start_i = max(start_i, int(dates.searchsorted(first)))
    tick = list(c.columns)
    C, O, L = c.values, o.values, l.values
    ENT, STR, EXT = cond["entry"].values, cond["strong"].values, cond["exit"].values
    COMP = comp.values
    ATR = F["atr14"].values
    CH = F["chandelier"].values
    REG = reg["label"].values

    cash = equity0
    pos: dict[int, dict] = {}
    equity, trades = [], []
    pending_exit: dict[int, str] = {}
    stop_mode = s.get("stop_mode", "close")
    pending_entry: list[int] = []
    n_entry = n_nolot = 0          # berapa sinyal beli yang gagal karena dana per posisi < harga 1 lot

    for i in range(start_i, len(dates)):
        # 1) eksekusi order dari sinyal kemarin di harga OPEN hari ini
        for j, why in list(pending_exit.items()):
            if j in pos:
                p = pos.pop(j)
                px = O[i, j]
                cash += p["sh"] * px * (1 - fee_s)
                trades.append(_trade(p, dates[i], px, tick[j], why, fee_b, fee_s))
        pending_exit.clear()
        eq_open = cash + sum(p["sh"] * O[i, j] for j, p in pos.items())
        for j in pending_entry:
            if j in pos or len(pos) >= maxpos:
                continue
            px = O[i, j]
            stop = pos_stop = round_tick(C[i - 1, j] - s["atr_stop_mult"] * ATR[i - 1, j], "down")
            if not np.isfinite(px) or px <= pos_stop:
                continue
            alloc = min(eq_open / maxpos, cash)
            sh = math.floor(alloc / (px * (1 + fee_b)) / lot) * lot
            n_entry += 1
            if sh <= 0:
                n_nolot += 1
                continue
            cash -= sh * px * (1 + fee_b)
            pos[j] = {"sh": sh, "entry": px, "d0": dates[i], "stop": stop, "i0": i}
        pending_entry = []

        # 2) stop loss intraday (hanya jika stop_mode = intraday; gap down -> keluar di open)
        for j in list(pos):
            p = pos[j]
            if stop_mode == "intraday" and p["i0"] < i and L[i, j] <= p["stop"]:
                px = min(O[i, j], p["stop"])
                cash += p["sh"] * px * (1 - fee_s)
                trades.append(_trade(p, dates[i], px, tick[j], "stop loss", fee_b, fee_s))
                pos.pop(j)

        # 3) mark-to-market & update trailing stop
        eq = cash + sum(p["sh"] * C[i, j] for j, p in pos.items())
        equity.append(eq)
        for j, p in pos.items():
            if np.isfinite(CH[i, j]):
                p["stop"] = max(p["stop"], round_tick(CH[i, j], "down"))

        # 4) sinyal di close -> order besok
        for j, p in pos.items():
            if stop_mode == "close" and C[i, j] <= p["stop"]:
                pending_exit[j] = "stop (close)"
            elif EXT[i, j]:
                pending_exit[j] = "sinyal exit"
        slots = int(round(maxpos * expo.get(REG[i], 0.7))) - (len(pos) - len(pending_exit))
        if slots > 0:
            cand = [j for j in range(len(tick)) if ENT[i, j] and j not in pos]
            cand.sort(key=lambda j: (not STR[i, j], -COMP[i, j]))
            pending_entry = cand[:slots]

    eq = pd.Series(equity, index=dates[start_i:])
    bench = reg["ihsg"].iloc[start_i:].ffill().bfill()
    if bench.isna().all() or bench.iloc[0] <= 0:
        bench = pd.Series(equity0, index=eq.index, dtype=float)
    bench = bench / bench.iloc[0] * equity0
    out = _stats(eq, bench, trades, cfg, equity0)
    out["final_equity"] = round(float(eq.iloc[-1]))
    out["lot_skips"] = {"signals": n_entry, "skipped": n_nolot}
    if n_nolot:
        out["assumptions"].insert(4, f"Modal awal Rp{equity0:,.0f}".replace(",", ".") + f": {n_nolot} dari {n_entry} sinyal beli "
                                  "dilewati karena dana per posisi tidak cukup untuk 1 lot (saham berharga tinggi)")
    liq = F["liquid"].iloc[start_i:]
    out["universe"] = {"liquid_start": int(liq.iloc[:21].sum(axis=1).mean()), "liquid_end": int(liq.iloc[-21:].sum(axis=1).mean())}
    return out


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
    yrs = max(len(eq) / 252, 1e-9)

    def pack(s):
        r = s.pct_change().dropna()
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
        vol = r.std() * math.sqrt(252)
        sharpe = (r.mean() * 252 - rf) / vol if vol > 0 else 0
        dn = r[r < 0].std() * math.sqrt(252)
        sortino = (r.mean() * 252 - rf) / dn if dn and dn > 0 else 0
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
        "kelly": {"full": round(float(kelly), 3), "half": round(float(max(kelly, 0) / 2), 3),
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
