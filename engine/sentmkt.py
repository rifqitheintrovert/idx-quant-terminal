"""Indeks Sentimen BEI (gaya fear & greed) + peluang IHSG ke depan per zona sentimen.

Enam komponen objektif yang bisa dihitung mundur (bukan berita, karena berita tidak punya riwayat):
  mom   momentum IHSG       : jarak IHSG ke MA125
  brd   lebar pasar         : % saham likuid di atas MA50
  hilo  tertinggi vs terendah: (saham di puncak 52 minggu − di dasar 52 minggu) / jumlah keduanya, rata-rata 10 hari
  vol   volatilitas IHSG    : volatilitas 20 hari (dibalik: tenang = serakah)
  flow  akumulasi           : % saham likuid dengan CMF 20 hari > 0
  fx    rupiah              : USD/IDR vs MA50 (dibalik: rupiah melemah = takut)
Tiap komponen diubah ke persentil terhadap 250 hari sebelumnya (0 = paling takut setahun terakhir, 100 = paling serakah),
indeks = rata-rata komponen yang tersedia.

Peluang: untuk setiap hari dalam histori, catat zona indeks lalu apakah IHSG lebih tinggi 5/20/60 hari kemudian.
Hari-hari berurutan saling tumpang tindih, jadi jumlah kejadian "efektif" jauh lebih kecil dari n — karena itu
ditampilkan juga hasil per paruh histori (konsisten atau tidak).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ZONES = [(0, 25, "Takut ekstrem"), (25, 45, "Takut"), (45, 55, "Netral"), (55, 75, "Serakah"), (75, 101, "Serakah ekstrem")]
COMP = {"mom": "Momentum IHSG", "brd": "Lebar pasar", "hilo": "Puncak vs dasar 52 minggu", "vol": "Volatilitas IHSG",
        "flow": "Akumulasi (CMF)", "fx": "Rupiah"}


def _zone(x):
    for lo, hi, name in ZONES:
        if lo <= x < hi:
            return name
    return None


def _r(x, d=3):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


def build(F: dict, ihsg: pd.Series, usd: pd.Series | None, news_mkt: dict | None, gate_ma: int = 200, nhist: int = 500,
          entry: pd.DataFrame | None = None, Y: dict | None = None) -> dict:
    c = F["c"]
    idx = c.index
    ih = ihsg.reindex(idx).ffill()
    liq = F["liquid"].fillna(False).astype(bool)
    nliq = liq.sum(1).replace(0, np.nan)
    raw = {
        "mom": ih / ih.rolling(125, min_periods=100).mean() - 1,
        "brd": ((c > F["ma50"]) & liq).sum(1) / nliq,
        "vol": -(np.log(ih / ih.shift(1)).rolling(20).std() * np.sqrt(250)),
        "flow": ((F["cmf20"] > 0) & liq).sum(1) / nliq,
    }
    hi = (c >= c.rolling(250, min_periods=200).max()) & liq
    lo = (c <= c.rolling(250, min_periods=200).min()) & liq
    nh, nl = hi.sum(1), lo.sum(1)
    raw["hilo"] = ((nh - nl) / (nh + nl).replace(0, np.nan)).fillna(0).rolling(10, min_periods=5).mean()
    if usd is not None and len(usd.dropna()) > 300:
        u = usd.reindex(idx).ffill()
        raw["fx"] = -(u / u.rolling(50, min_periods=40).mean() - 1)
    R = pd.DataFrame(raw)
    P = R.rolling(250, min_periods=200).rank(pct=True) * 100            # persentil 1 tahun terakhir
    comp = P.mean(axis=1, skipna=True).where(P.notna().sum(1) >= 4)
    gate = ih > ih.rolling(gate_ma, min_periods=gate_ma).mean()

    # ---- peluang IHSG ke depan per zona (semua hari) ----
    fwd = {h: ih.shift(-h) / ih - 1 for h in (5, 20, 60)}
    z = comp.apply(lambda x: _zone(x) if np.isfinite(x) else None)
    valid = comp.notna()
    mid = idx[valid][len(idx[valid]) // 2] if valid.any() else idx[0]

    def stats(mask):
        o = {}
        for h, f in fwd.items():
            m = mask & f.notna()
            if m.sum() < 20:
                continue
            o[f"up{h}"] = _r((f[m] > 0).mean())
            o[f"r{h}"] = _r(f[m].mean(), 4)
            o[f"n{h}"] = int(m.sum())
            o[f"h{h}"] = [_r((f[m & (idx < mid)] > 0).mean()) if (m & (idx < mid)).sum() >= 20 else None,
                          _r((f[m & (idx >= mid)] > 0).mean()) if (m & (idx >= mid)).sum() >= 20 else None]
        return o

    base = stats(valid)
    zones = {name: stats(valid & (z == name)) for _, _, name in ZONES}
    gates = {"buka": stats(valid & gate), "tutup": stats(valid & ~gate)}
    now_z = _zone(comp.iloc[-1]) if np.isfinite(comp.iloc[-1]) else None
    combo = stats(valid & (z == now_z) & (gate == bool(gate.iloc[-1]))) if now_z else {}

    # ---- angka historis terbaik ----
    hb = {"buckets": [], "comp": {}, "sig": {}}
    for lo_ in range(0, 100, 10):
        st = stats(valid & (comp >= lo_) & (comp < lo_ + 10 + (1 if lo_ == 90 else 0)))
        st.update({"lo": lo_, "hi": lo_ + 10})
        h = st.get("h60") or [None, None]
        st["ok"] = bool(h[0] is not None and h[1] is not None and base.get("h60") and h[0] > base["h60"][0] and h[1] > base["h60"][1])
        hb["buckets"].append(st)
    cand = [b for b in hb["buckets"] if b["ok"] and (b.get("n60") or 0) >= 100]
    if cand:
        bst = max(cand, key=lambda b: b["up60"])
        hb["best"] = {"lo": bst["lo"], "hi": bst["hi"], "up60": bst["up60"], "r60": bst.get("r60"), "n60": bst.get("n60")}
    else:
        hb["best"] = None
    for k in P.columns:
        row = []
        for q0 in range(0, 100, 20):
            m = valid & (P[k] >= q0) & (P[k] < q0 + 20 + (1 if q0 == 80 else 0))
            st = stats(m)
            h = st.get("h60") or [None, None]
            row.append({"lo": q0, "up60": st.get("up60"), "r60": st.get("r60"), "n60": st.get("n60"),
                        "ok": bool(h[0] is not None and h[1] is not None and base.get("h60") and
                                   np.sign(h[0] - base["h60"][0]) == np.sign(h[1] - base["h60"][1]))})
        cur = P[k].iloc[-1]
        hb["comp"][k] = {"label": COMP[k], "q": row, "cur": int(min(cur // 20, 4)) if np.isfinite(cur) else None}
    if entry is not None and Y is not None and "tp1" in Y:
        e = entry.reindex(index=idx, columns=c.columns).fillna(False).values.astype(bool) & liq.values
        zarr = z.values
        for _, _, name in ZONES + [(0, 0, "Semua")]:
            rm = np.ones(len(idx), bool) if name == "Semua" else (zarr == name)
            m = e & rm[:, None]
            o = {"n": int(m.sum())}
            for kk in ("tp1", "tp2", "up20", "up60"):
                y = Y.get(kk)
                if y is None:
                    continue
                mm = m & np.isfinite(y)
                if mm.sum() >= 30:
                    o[kk] = _r(y[mm].mean())
                    o["n_" + kk] = int(mm.sum())
            hb["sig"][name] = o

    # ---- rezim IHSG (HMM 2 keadaan) ----
    hm = None
    try:
        from .qmodels import hmm
        hr = hmm(pd.DataFrame({"IHSG": np.log(ih / ih.shift(1))}), T=750)
        hm = hr.get("IHSG")
        if hm:
            hm["p"] = hm["p"][-nhist:]
    except Exception:  # noqa: BLE001
        hm = None

    last = {k: {"label": COMP[k], "raw": _r(R[k].iloc[-1], 4), "score": _r(P[k].iloc[-1], 1)} for k in R.columns}
    last["brd"]["txt"] = f"{R['brd'].iloc[-1]*100:.0f}% saham likuid di atas MA50" if np.isfinite(R["brd"].iloc[-1]) else ""
    last["mom"]["txt"] = f"IHSG {R['mom'].iloc[-1]*100:+.1f}% dari MA125" if np.isfinite(R["mom"].iloc[-1]) else ""
    last["vol"]["txt"] = f"volatilitas 20 hari {-R['vol'].iloc[-1]*100:.0f}%/thn" if np.isfinite(R["vol"].iloc[-1]) else ""
    last["flow"]["txt"] = f"{R['flow'].iloc[-1]*100:.0f}% saham likuid diakumulasi (CMF > 0)" if np.isfinite(R["flow"].iloc[-1]) else ""
    last["hilo"]["txt"] = f"{int(nh.iloc[-1])} saham di puncak vs {int(nl.iloc[-1])} di dasar 52 minggu"
    if "fx" in last:
        last["fx"]["txt"] = f"USD/IDR {-R['fx'].iloc[-1]*100:+.1f}% dari MA50" if np.isfinite(R["fx"].iloc[-1]) else ""
    tail = comp.iloc[-nhist:]
    return {
        "now": {"score": _r(comp.iloc[-1], 1), "zone": now_z, "w1": _r(comp.iloc[-6], 1) if len(comp) > 6 else None,
                "m1": _r(comp.iloc[-22], 1) if len(comp) > 22 else None, "gate": bool(gate.iloc[-1])},
        "comp": last,
        "news": news_mkt,
        "hist": {"d": [str(d.date()) for d in tail.index], "s": [_r(x, 1) for x in tail.values],
                 "ih": [_r(x, 1) for x in ih.reindex(tail.index).values]},
        "prob": {"base": base, "zones": zones, "gate": gates, "combo": combo, "since": str(idx[valid][0].date()) if valid.any() else None,
                 "mid": str(mid.date())},
        "hmm": hm,
        "hist_best": hb,
    }
