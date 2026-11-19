"""Mesin harian Crypto Flow Terminal (GitHub Actions, tiap 07:05 WIB = 00:05 UTC).

Yang dikerjakan, semuanya dari data publik tanpa API key, hanya pustaka standar Python:
  1. track.json  - catatan sinyal harian yang tidak pernah ditulis ulang (forward test jujur):
                   sinyal TREN per koin (portofolio inti + keranjang meme), skala vol-target
                   portofolio, sinyal on-chain MVRV BTC/ETH, dan harga close. Baris yang
                   terlambat dicatat (late=true) tidak boleh dipakai untuk mengubah posisi.
  2. deriv.json  - arus taker harian derivatif & spot dari OKX (rubik) dan Bitget futures,
                   dalam USD. Bybit dan Binance futures memblokir server GitHub (lokasi AS).
  3. snap.json   - potret harian aset & arus bersih wallet exchange (DefiLlama /cexs) yang
                   riwayatnya tidak tersedia gratis; terkumpul mulai mesin ini jalan.
  4. meta.json   - daftar token saham (tokenized stock) Binance untuk disaring dari daftar
                   koin, plus status jalannya mesin.

Aturan sinyal sama persis dengan terminal (site/crypto/index.html):
  TREN  : close koin > SMA50 DAN close BTC > SMA100, dihitung di close harian (00:00 UTC),
          posisi dipegang hari berikutnya. Koin ikut portofolio setelah punya 200 hari riwayat.
  VT50  : seluruh portofolio TREN diskalakan min(1, 50% / vol tahunan 30 hari return
          portofolio) - satu-satunya varian yang lolos uji out-of-sample (tools/crypto_research.py).
  MVRV  : BELI saat MVRV > rata-rata 200 hari x 1,02, JUAL saat < x 0,98 (data CoinMetrics,
          telat 1 hari).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (crypto-flow-terminal daily engine)"}
DAY = 86_400_000
UNIV = ("BTC ETH BNB XRP ADA LTC TRX LINK DOGE XLM BCH ETC NEO IOTA VET EOS ATOM ALGO DOT SOL AVAX UNI NEAR FIL "
        "ZEC ICX ONT QTUM DASH XMR MATIC SAND MANA AAVE HBAR THETA").split()
MEME = ("DOGE SHIB PEPE FLOKI BONK WIF BOME PEOPLE MEME 1000SATS TURBO NEIRO PNUT TRUMP PENGU ACT DOGS "
        "1MBABYDOGE 1000CHEEMS 1000CAT").split()
DERIV = "BTC ETH SOL XRP BNB DOGE ADA LINK AVAX SUI LTC TRX PEPE SHIB WIF".split()
TN, BN, ELIG, FEE = 50, 100, 200, 0.001
PVT, PVW = 0.5, 30
ON, OBAND = 200, 0.02
LATE_H = 6          # baris yang dihitung > 6 jam setelah candle tutup dianggap terlambat
ERR: list[str] = []


def get(url, post=None, tries=3, timeout=30):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(post).encode() if post else None,
                                         headers={**UA, **({"Content-Type": "application/json"} if post else {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def iso(day: int) -> str:
    return datetime.fromtimestamp(day * 86400, timezone.utc).strftime("%Y-%m-%d")


def dnum(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()) // 86400


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        f.write("\n")
    os.replace(tmp, path)


def rnd(x, sig=6):
    if x is None or not math.isfinite(x):
        return None
    if x == 0:
        return 0
    return float(f"{x:.{sig}g}")


# ---------------------------------------------------------------- Binance spot (candle harian)
def klines(sym: str, now_ms: int, limit=400):
    k = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}USDT&interval=1d&limit={limit}")
    rows = [x for x in k if int(x[6]) < now_ms]            # buang candle yang belum tutup
    return {"d": [int(x[0]) // DAY for x in rows], "o": [float(x[1]) for x in rows],
            "c": [float(x[4]) for x in rows], "full": len(k) >= limit}


def sma_at(c, i, n):
    return sum(c[i - n + 1:i + 1]) / n if i >= n - 1 else None


def tren(c, i, btc_up):
    m = sma_at(c, i, TN)
    return m is not None and c[i] > m and btc_up


def eligible(K, i):
    """sama seperti terminal: sleeve dihitung mulai indeks ke-200 dari seluruh riwayat koin."""
    return K["full"] or i >= ELIG


# ---------------------------------------------------------------- CoinMetrics (MVRV)
def cm_mvrv(asset, start):
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?frequency=1d&page_size=10000"
           f"&assets={asset}&metrics=PriceUSD,CapMVRVCur&start_time={start}")
    rows = []
    while url:
        j = get(url, timeout=60)
        rows += j.get("data", [])
        url = j.get("next_page_url")
    out = []
    for r in rows:
        if r.get("CapMVRVCur") and r.get("PriceUSD"):
            out.append((dnum(r["time"][:10]), float(r["CapMVRVCur"]), float(r["PriceUSD"])))
    out.sort()
    on, sig, mv = False, {}, [x[1] for x in out]
    for i, (d, v, _) in enumerate(out):
        if i >= ON - 1:
            ma = sum(mv[i - ON + 1:i + 1]) / ON
            if not on and v > ma * (1 + OBAND):
                on = True
            elif on and v < ma * (1 - OBAND):
                on = False
        sig[d] = (on, out[i][2])
    return sig


# ---------------------------------------------------------------- 1. track record
def build_rows(track, K, oc, now):
    btc = K["BTC"]
    bix = {d: i for i, d in enumerate(btc["d"])}
    last_closed = btc["d"][-1]
    rows = track["rows"]
    have = dnum(rows[-1]["d"]) if rows else None
    todo = [last_closed] if have is None else list(range(have + 1, last_closed + 1))
    uni = track["uni"]
    idx = {s: {d: i for i, d in enumerate(K[s]["d"])} for s in K}

    def btc_up(d):
        i = bix.get(d)
        m = sma_at(btc["c"], i, BN) if i is not None else None
        return m is not None and btc["c"][i] > m

    def sig_bits(names, d, up):
        out = []
        for s in names:
            k, i = K.get(s), idx.get(s, {}).get(d)
            if k is None or i is None or not eligible(k, i):
                out.append("-")
            else:
                out.append("1" if tren(k["c"], i, up) else "0")
        return "".join(out)

    def base_ret(d):
        """return portofolio TREN (tanpa skala) di hari d, rumus sama dengan riset & terminal."""
        tot, n = 0.0, 0
        for s in uni["core"]:
            k = K.get(s)
            i = idx.get(s, {}).get(d)
            if k is None or i is None or i < 2 or not eligible(k, i):
                continue
            want = 1.0 if tren(k["c"], i - 1, btc_up(k["d"][i - 1])) else 0.0
            held = 1.0 if (eligible(k, i - 1) and tren(k["c"], i - 2, btc_up(k["d"][i - 2]))) else 0.0
            c, o = k["c"], k["o"]
            tot += held * (o[i] / c[i - 1] - 1) + want * (c[i] / o[i] - 1) - FEE * abs(want - held)
            n += 1
        return tot / n if n else 0.0

    added = []
    for d in todo:
        if d not in bix:
            continue
        up = btc_up(d)
        r = [base_ret(x) for x in range(d - PVW + 1, d + 1)]
        mu = sum(r) / len(r)
        vol = math.sqrt(sum((x - mu) ** 2 for x in r) / len(r)) * math.sqrt(365)
        sc = min(1.0, PVT / vol) if vol > 0 else 1.0
        px = {}
        for s in dict.fromkeys(uni["core"] + uni["meme"]):
            i = idx.get(s, {}).get(d)
            if i is not None:
                px[s] = rnd(K[s]["c"][i], 8)
        late = (d != last_closed) or (now.timestamp() * 1000 > (d + 1) * DAY + LATE_H * 3600_000)
        row = {"d": iso(d), "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "late": late, "btcUp": up,
               "core": sig_bits(uni["core"], d, up), "meme": sig_bits(uni["meme"], d, up),
               "sc": round(sc, 4), "vol": round(vol, 4), "px": px}
        if oc:
            o = {}
            for a, sg in oc.items():
                avail = [x for x in sg if x <= d - 1]       # data CoinMetrics telat 1 hari
                if avail:
                    dd = max(avail)
                    o[a] = {"on": sg[dd][0], "d": iso(dd)}
            row["oc"] = o
        rows.append(row)
        added.append(row["d"])
    return added


# ---------------------------------------------------------------- 2. taker derivatif
def deriv(prev, K):
    out = prev if prev.get("coins") else {"coins": {}}
    try:
        sup = get("https://www.okx.com/api/v5/rubik/stat/trading-data/support-coin")["data"]
        okx_spot, okx_ctr = set(sup.get("spot", [])), set(sup.get("contract", []))
    except Exception as e:  # noqa: BLE001
        ERR.append(f"okx support-coin: {e}")
        okx_spot, okx_ctr = set(DERIV), set(DERIV)

    def price_on(sym, d):
        k = K.get(sym)
        if not k:
            return None
        try:
            return k["c"][k["d"].index(d)]
        except ValueError:
            return None

    def hk_day(ts):   # OKX & Bitget memakai hari Hong Kong (mulai 16:00 UTC = 23:00 WIB)
        return (int(ts) + 8 * 3600_000) // DAY

    for sym in DERIV:
        cur = out["coins"].setdefault(sym, {})
        series = {}
        try:
            if sym in okx_ctr:
                j = get(f"https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy={sym}&instType=CONTRACTS&period=1D")
                for ts, sell, buy in [x[:3] for x in j.get("data", [])]:
                    series.setdefault(hk_day(ts), {})["of"] = [rnd(float(buy)), rnd(float(sell))]
            time.sleep(0.45)
            if sym in okx_spot:
                j = get(f"https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy={sym}&instType=SPOT&period=1D")
                for ts, sell, buy in [x[:3] for x in j.get("data", [])]:
                    p = price_on(sym, hk_day(ts))
                    if p:
                        series.setdefault(hk_day(ts), {})["os"] = [rnd(float(buy) * p), rnd(float(sell) * p)]
            time.sleep(0.45)
        except Exception as e:  # noqa: BLE001
            ERR.append(f"okx {sym}: {e}")
        try:
            j = get(f"https://api.bitget.com/api/v2/mix/market/taker-buy-sell?symbol={sym}USDT&productType=usdt-futures&period=1d")
            for x in j.get("data", []) or []:
                d = hk_day(x["ts"])
                p = price_on(sym, d)
                if p:
                    series.setdefault(d, {})["bf"] = [rnd(float(x["buyVolume"]) * p), rnd(float(x["sellVolume"]) * p)]
        except Exception as e:  # noqa: BLE001
            ERR.append(f"bitget {sym}: {e}")
        for d, v in series.items():                 # gabung dengan riwayat lama, data terbaru menimpa
            cur.setdefault(iso(d), {}).update(v)
        if not cur:
            out["coins"].pop(sym, None)
        else:
            out["coins"][sym] = dict(sorted(cur.items()))
    return out


# ---------------------------------------------------------------- 3. potret exchange (DefiLlama)
def cex_snap(snap, now):
    j = get("https://api.llama.fi/cexs", timeout=45)
    rows = []
    for c in j.get("cexs", []):
        tvl = c.get("cleanAssetsTvl") or c.get("currentTvl")
        if tvl:
            rows.append([c.get("name"), rnd(tvl), rnd(c.get("inflows_24h")), rnd(c.get("inflows_1w")), rnd(c.get("inflows_1m"))])
    rows.sort(key=lambda r: -(r[1] or 0))
    day = now.strftime("%Y-%m-%d")
    snap["rows"] = [r for r in snap.get("rows", []) if r["d"] != day]   # satu potret per hari (yang terakhir)
    snap["rows"].append({"d": day, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "tot": [rnd(sum(r[i] or 0 for r in rows)) for i in (1, 2, 3, 4)], "ex": rows[:20]})
    return snap


def stocks():
    j = get("https://data-api.binance.vision/api/v3/exchangeInfo?permissions=%5B%22TRD_GRP_261%22%5D&showPermissionSets=false", timeout=45)
    return sorted({s["baseAsset"] for s in j.get("symbols", []) if s.get("quoteAsset") == "USDT"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/crypto/data")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    P = lambda n: os.path.join(a.out, n)  # noqa: E731

    track = load(P("track.json"), None)
    if not track:
        track = {"v": 1, "fee": FEE, "pvt": PVT, "start": None, "uni": {"core": [], "meme": []}, "rows": [],
                 "note": "Dicatat otomatis tiap 07:05 WIB. Baris lama tidak pernah diubah. late=true = dihitung terlambat, tidak dipakai untuk mengubah posisi."}

    K = {}
    for s in dict.fromkeys(["BTC"] + UNIV + MEME + DERIV):
        try:
            K[s] = klines(s, now_ms)
        except Exception as e:  # noqa: BLE001
            if s in track["uni"]["core"] + track["uni"]["meme"] or s == "BTC":
                ERR.append(f"klines {s}: {e}")
    if "BTC" not in K:
        raise SystemExit("candle BTC gagal dimuat")
    # semesta dikunci saat pertama kali jalan; koin baru hanya ditambah di belakang
    for key, names in (("core", UNIV), ("meme", MEME)):
        for s in names:
            if s in K and s not in track["uni"][key]:
                track["uni"][key].append(s)

    oc = {}
    for asset, start in (("btc", "2011-01-01"), ("eth", "2016-01-01")):
        try:
            oc[asset] = cm_mvrv(asset, start)
        except Exception as e:  # noqa: BLE001
            ERR.append(f"coinmetrics {asset}: {e}")
    added = build_rows(track, K, oc, now)
    if track["rows"] and not track["start"]:
        track["start"] = track["rows"][0]["d"]
    save(P("track.json"), track)

    try:
        save(P("deriv.json"), {**deriv(load(P("deriv.json"), {}), K), "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    except Exception as e:  # noqa: BLE001
        ERR.append(f"deriv: {e}")
    try:
        save(P("snap.json"), cex_snap(load(P("snap.json"), {}), now))
    except Exception as e:  # noqa: BLE001
        ERR.append(f"cex: {e}")
    meta = load(P("meta.json"), {})
    try:
        meta["stocks"] = stocks()
    except Exception as e:  # noqa: BLE001
        ERR.append(f"stocks: {e}")
    meta.update({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "added": added, "errors": ERR[:20]})
    save(P("meta.json"), meta)
    print(f"baris baru: {added or 'tidak ada'} | koin inti {len(track['uni']['core'])} meme {len(track['uni']['meme'])}"
          f" | saham {len(meta.get('stocks', []))} | error {len(ERR)}")
    for e in ERR:
        print("  !", e)
    if track["rows"]:
        r = track["rows"][-1]
        print("  terakhir:", r["d"], "late" if r["late"] else "tepat waktu", "BTC>SMA100" if r["btcUp"] else "BTC<SMA100",
              "inti", r["core"].count("1"), "/", len(r["core"]) - r["core"].count("-"),
              "meme", r["meme"].count("1"), "/", len(r["meme"]) - r["meme"].count("-"), "skala", r["sc"], "oc", r.get("oc"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
