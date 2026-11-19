"""Riset sementara: apakah vol targeting / gabungan tren + on-chain menurunkan drawdown
strategi TREN tanpa merusak return per risiko. Dijalankan di runner GitHub (data Binance
lewat data-api.binance.vision, MVRV dari CoinMetrics community).

Aturan keputusan (ditulis SEBELUM melihat hasil OOS):
  parameter dipilih di 2018-2021 (in-sample, Calmar terbaik), lalu varian dipasang hanya kalau
  di 2022-sekarang (out-of-sample), pada fee 0,1% DAN 0,2%:
    - max drawdown turun >= 5 poin persen dibanding TREN biasa,
    - Calmar (CAGR / MaxDD) tidak lebih rendah,
    - Sharpe tidak turun lebih dari 0,05.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np

H = {"User-Agent": "Mozilla/5.0 flowterm-research"}
DAY = 86400_000
UNIV = "BTC ETH BNB XRP ADA LTC TRX LINK DOGE XLM BCH ETC NEO IOTA VET EOS ATOM ALGO DOT SOL AVAX UNI NEAR FIL ZEC ICX ONT QTUM DASH XMR MATIC SAND MANA AAVE HBAR THETA".split()
MEME = "DOGE SHIB PEPE FLOKI BONK WIF BOME PEOPLE MEME 1000SATS TURBO NEIRO PNUT TRUMP PENGU ACT DOGS 1MBABYDOGE 1000CHEEMS 1000CAT".split()
TN, BN, ELIG = 50, 100, 200
ON, OBAND = 200, 0.02
T_IS0, T_IS1, T_OOS0 = "2018-03-06", "2021-12-31", "2022-01-01"   # 2018-03-06 = BTC punya 200 hari riwayat


def get(url, post=None, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(post).encode() if post else None, headers=H)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if k == tries - 1:
                raise
            time.sleep(1.5 * (k + 1))


def klines(sym):
    out, start = [], int(datetime(2017, 7, 1, tzinfo=timezone.utc).timestamp() * 1000)
    now = int(time.time() * 1000)
    while True:
        k = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}USDT&interval=1d&limit=1000&startTime={start}")
        if not k:
            break
        out += [x for x in k if int(x[6]) < now]
        if len(k) < 1000:
            break
        start = int(k[-1][0]) + DAY
    return {int(x[0]) // DAY: (float(x[1]), float(x[4])) for x in out}


def cm(asset, start):
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?frequency=1d&page_size=10000"
           f"&assets={asset}&metrics=PriceUSD,CapMVRVCur&start_time={start}")
    rows = []
    while url:
        j = get(url)
        rows += j.get("data", [])
        url = j.get("next_page_url")
    d = {}
    for r in rows:
        t = int(datetime.fromisoformat(r["time"][:10]).replace(tzinfo=timezone.utc).timestamp() * 1000) // DAY
        if r.get("CapMVRVCur"):
            d[t] = float(r["CapMVRVCur"])
    return d


def sma(a, n):
    o = np.full(len(a), np.nan)
    if len(a) >= n:
        c = np.cumsum(np.insert(a, 0, 0.0))
        o[n - 1:] = (c[n:] - c[:-n]) / n
    return o


def mvrv_sig(mv: dict):
    """sinyal MVRV per hari kalender (dict hari -> bool), sama seperti terminal (hysteresis 2%)."""
    days = sorted(mv)
    v = np.array([mv[d] for d in days])
    ma = sma(v, ON)
    on, out = False, {}
    for i, d in enumerate(days):
        if not np.isnan(ma[i]):
            if not on and v[i] > ma[i] * (1 + OBAND):
                on = True
            elif on and v[i] < ma[i] * (1 - OBAND):
                on = False
        out[d] = on
    return out


def vol30(c):
    lr = np.diff(np.log(c), prepend=np.nan)
    o = np.full(len(c), np.nan)
    for i in range(30, len(c)):
        o[i] = np.std(lr[i - 29:i + 1]) * math.sqrt(365)
    return o


class Book:
    """Portofolio sama bobot per koin (sleeve), tiap sleeve punya bobot target 0..1 diputuskan di close."""

    def __init__(self, days):
        self.days = days
        self.ix = {d: i for i, d in enumerate(days)}
        self.sum = np.zeros(len(days))
        self.cnt = np.zeros(len(days))
        self.w = np.zeros(len(days))
        self.turn = np.zeros(len(days))

    def add(self, d, o, c, target, fee, band=0.0):
        n = len(d)
        held = 0.0
        for k in range(ELIG, n):
            tgt = target[k - 1]
            new = held
            if (tgt == 0) != (held == 0) or abs(tgt - held) > band:
                new = tgt
            r = held * (o[k] / c[k - 1] - 1) + new * (c[k] / o[k] - 1) - fee * abs(new - held)
            i = self.ix.get(d[k])
            if i is not None:
                self.sum[i] += r
                self.cnt[i] += 1
                self.w[i] += new
                self.turn[i] += abs(new - held)
            held = new

    def returns(self):
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(self.cnt > 0, self.sum / np.maximum(self.cnt, 1), 0.0)
            x = np.where(self.cnt > 0, self.w / np.maximum(self.cnt, 1), 0.0)
            tv = np.where(self.cnt > 0, self.turn / np.maximum(self.cnt, 1), 0.0)
        return r, x, tv


def day_of(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000) // DAY


def metrics(days, r, x=None, tv=None, a=None, b=None):
    a = day_of(a) if a else days[0]
    b = day_of(b) if b else days[-1]
    m = np.array([(a <= d <= b) for d in days])
    rr = r[m]
    if len(rr) < 30:
        return None
    eq = np.cumprod(1 + rr)
    yrs = len(rr) / 365.25
    cagr = eq[-1] ** (1 / yrs) - 1
    dd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    sd = rr.std()
    return {
        "cagr": cagr * 100, "dd": dd * 100, "sharpe": (rr.mean() / sd * math.sqrt(365)) if sd else 0,
        "calmar": cagr / dd if dd else 0, "x": float(x[m].mean() * 100) if x is not None else None,
        "turn": float(tv[m].sum() / yrs) if tv is not None else None, "tot": (eq[-1] - 1) * 100,
    }


def fmt(name, m):
    if not m:
        return f"  {name:34s} (data kurang)"
    s = f"  {name:34s} CAGR {m['cagr']:7.1f}%  MaxDD {m['dd']:5.1f}%  Sharpe {m['sharpe']:5.2f}  Calmar {m['calmar']:5.2f}"
    if m.get("x") is not None:
        s += f"  di pasar {m['x']:4.0f}%  turnover {m['turn']:5.1f}x/thn"
    return s


def main():
    t0 = time.time()
    syms = list(dict.fromkeys(UNIV + MEME))
    K = {}
    for s in syms:
        try:
            K[s] = klines(s)
        except Exception as e:  # noqa: BLE001
            print("gagal", s, e)
    print(f"candle: {len(K)} koin, {time.time() - t0:.0f} dtk", flush=True)
    mv = {"btc": cm("btc", "2011-01-01"), "eth": cm("eth", "2016-01-01")}
    msig = {a: mvrv_sig(v) for a, v in mv.items()}
    print("MVRV:", {a: len(v) for a, v in mv.items()}, flush=True)

    btc = K["BTC"]
    bd = sorted(btc)
    bc = np.array([btc[d][1] for d in bd])
    bup = dict(zip(bd, bc > sma(bc, BN)))           # NaN -> False
    days = bd
    # filter pasar alternatif: sinyal MVRV BTC kemarin (data CoinMetrics telat 1 hari)
    fl = {
        "SMA100": lambda d: bool(bup.get(d, False)),
        "MVRV": lambda d: bool(msig["btc"].get(d - 1, False)),
        "SMA100&MVRV": lambda d: bool(bup.get(d, False)) and bool(msig["btc"].get(d - 1, False)),
        "SMA100|MVRV": lambda d: bool(bup.get(d, False)) or bool(msig["btc"].get(d - 1, False)),
    }

    prep = {}
    for s, kd in K.items():
        d = sorted(kd)
        o = np.array([kd[x][0] for x in d])
        c = np.array([kd[x][1] for x in d])
        prep[s] = (d, o, c, sma(c, TN), vol30(c))

    def run(coins, fee, filt="SMA100", tv=None, band=0.0, pvt=None):
        bk = Book(days)
        f = fl[filt]
        for s in coins:
            if s not in prep:
                continue
            d, o, c, sm, vo = prep[s]
            if len(d) < ELIG + 2:
                continue
            sig = np.array([(not np.isnan(sm[i])) and c[i] > sm[i] and f(d[i]) for i in range(len(d))], dtype=float)
            tgt = sig.copy()
            if tv:
                w = np.where(np.isnan(vo), 1.0, np.minimum(1.0, tv / np.maximum(vo, 1e-9)))
                tgt = sig * w
            bk.add(d, o, c, tgt, fee, band)
        r, x, t = bk.returns()
        if pvt:  # vol target di level portofolio: skala harian dari vol 30 hari return portofolio (s.d. kemarin)
            sc = np.ones(len(r))
            for i in range(31, len(r)):
                v = r[i - 30:i].std() * math.sqrt(365)
                sc[i] = min(1.0, pvt / v) if v > 0 else 1.0
            r = r * sc - fee * np.abs(np.diff(sc, prepend=1.0)) * x
            x = x * sc
        return r, x, t

    bh = np.array([0.0] + list(bc[1:] / bc[:-1] - 1))
    print("\n=== PERIODE: IS 2018-2021 | OOS 2022-sekarang | data s.d.", datetime.fromtimestamp(days[-1] * 86400, timezone.utc).date(), "===")

    def block(title, variants, coins, fees=(0.001, 0.002)):
        print(f"\n### {title}")
        res = {}
        for fee in fees:
            cache = {name: run(coins, fee, **kw) for name, kw in variants}
            for per, a, b in (("IS", T_IS0, T_IS1), ("OOS", T_OOS0, None), ("FULL", T_IS0, None)):
                print(f" fee {fee*100:.1f}% · {per}")
                print(fmt("BTC buy&hold", metrics(days, bh, a=a, b=b)))
                for name, kw in variants:
                    r, x, t = cache[name]
                    m = metrics(days, r, x, t, a, b)
                    res[(name, fee, per)] = m
                    print(fmt(name, m))
        return res

    # 1) pilih tv per-koin di IS saja
    grid = [("TREN", {})] + [(f"TREN+VT{int(tv*100)} band{int(bd_*100)}", {"tv": tv, "band": bd_}) for tv in (0.4, 0.6, 0.8, 1.0) for bd_ in (0.0, 0.1)]
    grid += [(f"TREN+PVT{int(p*100)}", {"pvt": p}) for p in (0.25, 0.35, 0.5)]
    grid += [(f"TREN filter {k}", {"filt": k}) for k in ("MVRV", "SMA100&MVRV", "SMA100|MVRV")]
    res = block("Portofolio 36 koin UNIV", grid, UNIV)

    def pick(prefix):
        c = [(n, res[(n, 0.001, "IS")]) for n, _ in grid if n.startswith(prefix) and res.get((n, 0.001, "IS"))]
        return max(c, key=lambda z: z[1]["calmar"])[0] if c else None

    cands = [x for x in (pick("TREN+VT"), pick("TREN+PVT"), pick("TREN filter")) if x]
    print("\n### Keputusan (parameter dipilih dari Calmar IS fee 0,1%):", cands)
    for n in cands:
        ok = True
        for fee in (0.001, 0.002):
            b0, v = res[("TREN", fee, "OOS")], res[(n, fee, "OOS")]
            c1 = v["dd"] <= b0["dd"] - 5
            c2 = v["calmar"] >= b0["calmar"]
            c3 = v["sharpe"] >= b0["sharpe"] - 0.05
            print(f"  {n:28s} fee {fee*100:.1f}%  DD {b0['dd']:.1f}->{v['dd']:.1f} {'OK' if c1 else 'X'}  "
                  f"Calmar {b0['calmar']:.2f}->{v['calmar']:.2f} {'OK' if c2 else 'X'}  Sharpe {b0['sharpe']:.2f}->{v['sharpe']:.2f} {'OK' if c3 else 'X'}")
            ok &= c1 and c2 and c3
        print(f"  => {n}: {'LOLOS' if ok else 'TIDAK LOLOS'}")

    # 2) BTC & ETH sendiri: tren vs MVRV vs gabungan (biner)
    for a in ("BTC", "ETH"):
        d, o, c, sm, vo = prep[a]
        mvs = msig[a.lower()]
        S = {
            "TREN": [(not np.isnan(sm[i])) and c[i] > sm[i] and bup.get(d[i], False) for i in range(len(d))],
            "MVRV": [mvs.get(d[i] - 1, False) for i in range(len(d))],
        }
        S["AND"] = [x and y for x, y in zip(S["TREN"], S["MVRV"])]
        S["OR"] = [x or y for x, y in zip(S["TREN"], S["MVRV"])]
        S["SETENGAH"] = [(0.5 * x + 0.5 * y) for x, y in zip(S["TREN"], S["MVRV"])]
        print(f"\n### {a} sendiri (biner, tanpa portofolio)")
        for fee in (0.001, 0.002):
            for per, a0, b0 in (("IS", T_IS0, T_IS1), ("OOS", T_OOS0, None)):
                print(f" fee {fee*100:.1f}% · {per}")
                hb = np.array([0.0] + list(c[1:] / c[:-1] - 1))
                print(fmt(f"{a} buy&hold", metrics(d, hb, a=a0, b=b0)))
                for k, sg in S.items():
                    bk = Book(d)
                    bk.add(d, o, c, np.array(sg, dtype=float), fee)
                    r, x, t = bk.returns()
                    print(fmt(k, metrics(d, r, x, t, a0, b0)))

    # 3) keranjang memecoin (yang masih listing sekarang -> bias survivorship!)
    print("\n### Memecoin (survivorship bias: hanya koin yang masih listing)")
    have = [s for s in MEME if s in prep and len(prep[s][0]) > ELIG + 30]
    print("  koin:", " ".join(f"{s}({datetime.fromtimestamp(prep[s][0][0]*86400, timezone.utc).date()})" for s in have))
    bk = Book(days)
    for s in have:
        d, o, c, *_ = prep[s]
        bk.add(d, o, c, np.ones(len(d)), 0.0)
    rbh, _, _ = bk.returns()
    MV = (("Meme TREN", {}), ("Meme TREN+VT60", {"tv": 0.6, "band": 0.1}), ("Meme TREN+VT100", {"tv": 1.0, "band": 0.1}))
    for fee in (0.001, 0.002):
        cache = {name: run(have, fee, **kw) for name, kw in MV}
        for per, a0, b0 in (("2021+", "2021-01-01", None), ("2023+", "2023-01-01", None), ("2024+", "2024-01-01", None)):
            print(f" fee {fee*100:.1f}% · {per}")
            print(fmt("BTC buy&hold", metrics(days, bh, a=a0, b=b0)))
            print(fmt("Meme buy&hold (sama bobot)", metrics(days, rbh, a=a0, b=b0)))
            for name, kw in MV:
                r, x, t = cache[name]
                print(fmt(name, metrics(days, r, x, t, a0, b0)))
    print(f"\nselesai {time.time() - t0:.0f} dtk")


if __name__ == "__main__":
    sys.exit(main())
