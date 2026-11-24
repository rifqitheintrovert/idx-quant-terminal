"""Orkestrator: ambil data -> hitung model -> tulis site/data/latest.json -> alert.

    python -m engine.run              # data live (Yahoo Finance + berita)
    python -m engine.run --demo       # data simulasi (untuk uji tampilan)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, crypto, data, features, notify, regime, sentiment, signals
from . import beneish, flowx, fundamentals, globalmkt, prob, qmodels, sentmkt, track, volmc
from . import universe as uni_mod
from .idx_rules import WIB, market_status, rules_table

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("run")
VERSION = "0.21.0"


def load_cfg(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def hist_start(cfg, now) -> str:
    """Tanggal mulai histori (YYYY-MM-DD) dari `history_years`; fallback ke `history_period` gaya Yahoo."""
    yrs = cfg.get("history_years")
    if not yrs:
        return cfg.get("history_period", "5y")
    return (now - timedelta(days=int(float(yrs) * 365.25))).strftime("%Y-%m-%d")


def _fetch_prices(cfg, tickers, core, args, now, warnings):
    """Histori harga semua saham. Sekali sehari unduh penuh; run berikutnya di hari yang sama
    hanya menyegarkan saham aktif (hemat request Yahoo), sisanya dari cache."""
    period = hist_start(cfg, now)
    today = now.strftime("%Y-%m-%d")
    jk = lambda ts: [t + ".JK" for t in ts]            # noqa: E731
    strip = lambda d: {k[:-3]: v for k, v in d.items()}  # noqa: E731
    cache = data.load_cache(args.cache) if args.cache else None
    hist = str(cfg.get("history_years", cfg.get("history_period")))
    light = bool(cache) and cache.get("date") == today and cache.get("hist") == hist and not args.full
    if light:
        frames, nodata = cache["frames"], set(cache.get("nodata", []))
        min_val = cfg["filters"].get("light_refresh_min_value_bn", 1) * 1e9
        active = [t for t in tickers if t in frames and (t in core or data.avg_value(frames[t]) >= min_val)]
        broken = data.merge_frames(frames, strip(data.fetch_yahoo(jk(active), "5d")))
        redo = sorted(set(broken) | {t for t in tickers if t not in frames and t not in nodata})
        if redo:
            got = strip(data.fetch_yahoo(jk(redo), period)) if redo else {}
            frames.update(got)
            nodata |= {t for t in redo if t not in got}
        mode = f"ringan ({len(active)} saham aktif disegarkan)"
    else:
        got = strip(data.fetch_yahoo(jk(tickers), period))
        old = (cache or {}).get("frames", {}) if (cache or {}).get("hist") == hist else {}   # histori lama lebih pendek -> buang
        kept = [t for t in tickers if t not in got and t in old]     # gagal diunduh kali ini -> pakai histori lama
        frames = {**{t: old[t] for t in kept}, **got}
        nodata = {t for t in tickers if t not in frames}
        if len(kept) > 25:
            warnings.append(f"{len(kept)} saham gagal diperbarui dari Yahoo — memakai data terakhir yang tersimpan")
        base = sum(t in old for t in tickers)               # yang berhasil pada unduhan sebelumnya
        ok = len(got) >= (0.9 * base if base else 0.5 * len(tickers))
        today = today if ok else ""                       # unduhan tidak lengkap -> ulang penuh di run berikutnya
        mode = "penuh"
    if args.cache:
        try:
            data.save_cache(args.cache, {"date": today, "hist": hist, "frames": frames, "nodata": sorted(nodata)})
        except Exception as e:  # noqa: BLE001
            log.warning("cache gagal disimpan: %s", e)
    # saham yang sudah lama tidak punya bar harga (delisting / suspensi > 1 tahun) tidak ditampilkan
    cutoff = pd.Timestamp(now.date()) - pd.Timedelta(days=int(cfg["filters"].get("max_stale_days", 370)))
    tset = set(tickers)
    live = {t: f for t, f in frames.items() if t in tset and len(f) and f.index[-1] >= cutoff}
    dead = sorted(t for t in frames if t in tset and t not in live)
    return live, sorted((nodata & tset) | set(dead)), mode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out", default=str(ROOT / "site" / "data" / "latest.json"))
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--cache", default=None, help="file cache histori harga (pickle)")
    ap.add_argument("--full", action="store_true", help="paksa unduh ulang semua histori")
    ap.add_argument("--inline-series", action="store_true", help="data chart disatukan di latest.json")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = load_cfg(Path(args.config))
    core = cfg["universe"]
    site_url = os.environ.get("SITE_URL")
    warnings: list[str] = []
    now = datetime.now(WIB)
    prev = None if args.demo else data.fetch_previous(site_url)
    nodata: list[str] = []
    refresh_mode = "demo"

    # ---------------- universe & harga ----------------
    if args.demo:
        universe = {**(cfg.get("universe_extra") or {}), **core}
        uinfo = {"mode": "demo", "source": "config.yaml"}
        panels, macro = data.demo_data(universe, cfg["macro"], days=int(float(cfg.get("history_years", 5)) * 252),
                                       end=now.replace(tzinfo=None))
        foreign = None
    else:
        universe, uinfo, uw = uni_mod.load(cfg)
        warnings += uw
        tickers = list(universe)
        try:
            frames, nodata, refresh_mode = _fetch_prices(cfg, tickers, core, args, now, warnings)
        except Exception as e:  # noqa: BLE001
            log.error("Gagal ambil harga: %s", e)
            if prev:
                prev["meta"]["warnings"] = [f"Update gagal ({e}); menampilkan data sebelumnya"] + prev["meta"].get("warnings", [])
                prev["meta"]["stale"] = True
                _write(prev, args.out)
                return 0
            raise
        miss_core = [t for t in core if t not in frames]
        if miss_core:
            warnings.append("Data tidak tersedia: " + ", ".join(miss_core))
        tickers = [t for t in tickers if t in frames]
        universe = {t: universe[t] for t in tickers}
        panels = data.build_panels(frames, tickers)
        del frames
        mframes = {}
        try:
            got = data.fetch_yahoo(list(cfg["macro"].values()), hist_start(cfg, now))
            mframes = {name: got.get(sym) for name, sym in cfg["macro"].items()}
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Data makro gagal: {e}")
        macro = {k: v for k, v in mframes.items() if v is not None}
        foreign = None
        if cfg.get("foreign_flow", {}).get("enabled"):
            days = list(panels["Close"].index[-cfg["foreign_flow"]["days"]:])
            foreign = data.fetch_foreign_flow(days, tickers)
            if foreign is None:
                warnings.append("Foreign flow BEI tidak bisa diakses — flow memakai estimasi OHLCV")

    # ---------------- model ----------------
    F = features.compute(panels, cfg, foreign)
    fprev = {}
    try:                          # inflow lanjutan (modal pemegang, siang vs semalam, rotasi float, serapan)
        if args.demo:
            fprev = fundamentals.demo(list(F["c"].columns), F["c"].iloc[-1].to_dict())
        elif args.cache:
            fprev = fundamentals.load(Path(args.cache).parent / "fundamentals.json")
        flowx.compute(F, fprev)
    except Exception as e:  # noqa: BLE001
        log.warning("Inflow lanjutan dilewati: %s", e)
    try:                          # Beneish M-score titik-waktu (dipakai saringan beli kalau signal.beneish_max diisi)
        F["ben"] = beneish.panel(fprev, {t: universe[t].get("sector") for t in F["c"].columns}, F["c"].index, F["c"].columns,
                                 int(cfg["signal"].get("beneish_lag_days", 95)))
        lb = F["ben"].iloc[-1]
        log.info("Beneish: %d saham punya skor | berisiko (M > %.2f): %d | abu-abu: %d", int(lb.notna().sum()), beneish.RISK,
                 int((lb > beneish.RISK).sum()), int(((lb > beneish.GREY) & (lb <= beneish.RISK)).sum()))
    except Exception as e:  # noqa: BLE001
        log.warning("Beneish dilewati: %s", e)
    if "IHSG" in macro:
        ihsg = macro["IHSG"]["Close"]
    else:
        warnings.append("IHSG tidak tersedia — memakai indeks equal-weight universe")
        ihsg = (F["c"].pct_change().mean(axis=1).fillna(0) + 1).cumprod() * 1000
    reg = regime.compute(ihsg, F, macro["USDIDR"]["Close"] if "USDIDR" in macro else None)
    regime_label = reg["label"].iloc[-1]
    liq_now = F["liquid"].iloc[-1].astype(bool)

    # ---------------- sentimen ----------------
    if args.demo:
        sent = sentiment.demo_sentiment(universe)
    elif args.no_news:
        sent = sentiment.aggregate([], universe, cfg)
    else:
        sent = None
        ps = (prev or {}).get("sentiment")
        if ps and ps.get("updated") and len(prev.get("stocks", [])) >= 0.9 * len(universe):
            age = datetime.now(WIB) - datetime.fromisoformat(ps["updated"]).astimezone(WIB)
            if age < timedelta(minutes=110):
                sent = ps
                sent["per_ticker"] = {s["ticker"]: s.get("sent", {}) for s in prev["stocks"]}
                sent["market"] = prev["market"]["sentiment"]
                sent["news"] = prev.get("news", [])
        if sent is None:
            try:
                # berita per saham hanya untuk yang paling likuid; saham lain terdeteksi lewat kode di headline
                rank = F["avg_val20"].iloc[-1].where(liq_now).dropna().sort_values(ascending=False)
                focus = list(dict.fromkeys(list(rank.index[:int(cfg["sentiment"].get("max_ticker_feeds", 120))])
                                           + [t for t in core if t in universe]))
                news = sentiment.fetch_news(universe, cfg, focus)
                llm = sentiment.llm_scores(news, cfg["sentiment"]["llm_model"])
                sent = sentiment.aggregate(news, universe, cfg, llm)
                if not news:
                    warnings.append("Tidak ada berita terambil — sentimen netral")
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Sentimen gagal: {e}")
                sent = sentiment.aggregate([], universe, cfg)

    sent_panel = pd.DataFrame(50.0, index=F["c"].index, columns=F["c"].columns)
    sent_panel.iloc[-1] = [sent["per_ticker"].get(t, {}).get("score", 50.0) for t in F["c"].columns]
    comp_live = features.composite(F, cfg["weights"], sent_panel)
    comp_hist = features.composite(F, cfg["weights"], None)
    cond_live = features.conditions(F, comp_live, cfg, reg)
    cond_hist = features.conditions(F, comp_hist, cfg, reg)

    bt = backtest.run(F, comp_hist, cond_hist, reg, cfg)
    try:
        k = bt.get("kelly", {})
        log.info("Kelly: risiko/trade %s (bootstrap %s, P≤0 %s) | log-optimal posisi %s %s | portofolio %s× (μ %s σ %s) | n %s",
                 k.get("full"), k.get("boot_risk"), k.get("p_neg"), k.get("log"), k.get("boot_log"), k.get("port"), k.get("port_mu"), k.get("port_vol"), k.get("n"))
    except Exception:  # noqa: BLE001
        pass
    nb = cfg["chart_bars"]
    stocks, dates, series = signals.snapshot(F, comp_live, comp_hist, cond_live, sent, universe, cfg, regime_label, nb)
    prob_meta, prob_Y = None, None
    try:                          # probabilitas arah: frekuensi historis per kondisi sinyal (aturan = backtest)
        t0 = time.time()
        prob_Y = prob._targets(F, cfg)
        prob_meta = prob.by_state(F, cond_hist, cfg, prob_Y)
        st = prob_meta["states"]
        for s in stocks:
            k = prob.LIVE2STATE.get(s["signal"])
            if k and k in st:
                s["prob"] = {x: st[k][x] for x in ("up5", "up20", "up60", "tp1", "tp2") if x in st[k]}
                s["prob"]["st"] = k
        log.info("Probabilitas per kondisi (%.1f dtk): %s", time.time() - t0,
                 {k: (v.get("up20"), v.get("tp1"), v.get("n")) for k, v in st.items()})
    except Exception as e:  # noqa: BLE001
        log.warning("Probabilitas dilewati: %s", e)
    for s in stocks:              # ringkasan Beneish per saham (sumber yang sama dengan saringan)
        try:
            b = beneish.latest(fprev.get(s["ticker"]) or {}, s["sector"], F["c"].index[-1], int(cfg["signal"].get("beneish_lag_days", 95)))
            if b:
                s["ben"] = b
        except Exception as e:  # noqa: BLE001
            log.debug("beneish %s: %s", s["ticker"], e)
    if "cost" in F:
        for s in stocks:
            t = s["ticker"]
            try:
                s["fx"] = flowx.latest(F, t)
                if s["signal"] != "AVOID" and t in series:
                    series[t]["chip"] = flowx.chip(F, t)
            except Exception as e:  # noqa: BLE001
                log.debug("flowx %s: %s", t, e)
    try:                          # volatilitas & GARCH(1,1) untuk tab MC
        t0 = time.time()
        vm = volmc.build(F, [t for t in series if t in F["c"].columns], nb, cfg)
        for t, v in vm.items():
            series[t]["vol"] = v
        if vm:
            ga = np.array([v["g"]["a"] for v in vm.values()]); gb = np.array([v["g"]["b"] for v in vm.values()])
            log.info("GARCH: %d saham, %.1f dtk | median α %.3f β %.3f persistensi %.3f | contoh %s", len(vm), time.time() - t0,
                     np.median(ga), np.median(gb), np.median(ga + gb),
                     {t: (vm[t]["g"]["a"], vm[t]["g"]["b"], vm[t]["g"]["lr"]) for t in ("BBCA", "TLKM", "ADRO", "ANTM") if t in vm})
    except Exception as e:  # noqa: BLE001
        log.warning("GARCH dilewati: %s", e)
    qm_meta = None
    try:                          # model kuant lain untuk tab QM (faktor, HMM, perilaku, ekor, likuiditas)
        tq = [t for t in series if t in F["c"].columns]
        qm = qmodels.build(F, tq, ihsg, fprev, nb, log)
        for t, v in qm["stocks"].items():
            series[t]["qm"] = v
        qm_meta = {"factors_1y": qm["factors_1y"]}
        hh = [v["hmm"]["now"] for v in qm["stocks"].values() if v.get("hmm") and v["hmm"].get("now") is not None]
        log.info("QM: %d saham | median peluang rezim bergejolak %.2f | faktor 1 thn %s", len(tq), float(np.median(hh)) if hh else -1, qm["factors_1y"])
        for t in ("BBCA", "TLKM", "ANTM"):
            v = qm["stocks"].get(t) or {}
            if v:
                log.info("  QM %s: beta1y %s | FF %s | HMM vol %s sekarang %s | Hurst %s %s | EVT %s | ARA %s | Amihud pct %s | CS %s", t,
                         (v.get("fac") or {}).get("capm1y", {}).get("beta"), ((v.get("fac") or {}).get("ff") or {}).get("b"),
                         (v.get("hmm") or {}).get("vol"), (v.get("hmm") or {}).get("now"), (v.get("beh") or {}).get("hurst"),
                         (v.get("beh") or {}).get("label"), (v.get("tail") or {}).get("evt"), (v.get("tail") or {}).get("ara_days"),
                         (v.get("liq") or {}).get("amihud_pct"), (v.get("liq") or {}).get("cs"))
    except Exception as e:  # noqa: BLE001
        log.warning("QM dilewati: %s", e)
    market = signals.market_block(F, reg, macro, stocks, sent, cfg, nb)
    if prob_meta:
        market["prob"] = prob_meta
    if qm_meta:
        market["qm"] = qm_meta
    try:                          # Indeks Sentimen BEI + peluang IHSG per zona
        t0 = time.time()
        sm = sentmkt.build(F, ihsg, macro["USDIDR"]["Close"] if "USDIDR" in macro else None, market.get("sentiment"),
                           entry=cond_hist["entry"], Y=prob_Y)
        market["sentx"] = sm
        pz = sm["prob"]["zones"].get(sm["now"]["zone"] or "", {})
        bb = sm["hist_best"]
        log.info("Sentimen historis: terbaik %s | per 10 poin %s | sinyal BELI per zona %s", bb.get("best"),
                 [(r["lo"], r.get("up60"), r.get("n60"), r.get("ok")) for r in bb["buckets"]],
                 {z: (v.get("tp1"), v.get("up60"), v.get("n")) for z, v in bb.get("sig", {}).items()})
        log.info("Sentimen BEI: %s (%s) | komponen %s | zona ini: naik 20H %s 60H %s (paruh %s) vs dasar %s | %.1f dtk",
                 sm["now"]["score"], sm["now"]["zone"], {k: v["score"] for k, v in sm["comp"].items()}, pz.get("up20"), pz.get("up60"),
                 pz.get("h60"), sm["prob"]["base"].get("up60"), time.time() - t0)
    except Exception as e:  # noqa: BLE001
        log.warning("Sentimen BEI dilewati: %s", e)
    try:                          # skor ringkas QM per saham (untuk urutan di SIGNAL & screener)
        gate_open = bool((market.get("gate") or {}).get("open", True))
        nq = 0
        for s in stocks:
            ser = series.get(s["ticker"]) or {}
            if not ser.get("qm") and not ser.get("vol"):
                continue
            vv = qmodels.verdicts(s, ser.get("vol"), ser.get("qm"), gate_open, prob_meta, bt.get("kelly"), cfg)
            if vv:
                p_, m_ = sum(1 for _, r in vv if r > 0), sum(1 for _, r in vv if r < 0)
                s["qms"] = {"p": p_, "m": m_, "n": len(vv) - p_ - m_, "sc": p_ - m_, "v": {k: r for k, r in vv}}
                nq += 1
        top = sorted([s for s in stocks if s.get("qms") and s["signal"] != "AVOID"], key=lambda s: (-s["qms"]["sc"], -s["qms"]["p"]))[:5]
        log.info("Skor QM: %d saham | teratas %s", nq, [(s["ticker"], s["qms"]["sc"]) for s in top])
    except Exception as e:  # noqa: BLE001
        log.warning("Skor QM dilewati: %s", e)
    try:                          # pasar global: informasi saja, kegagalannya tidak boleh menggagalkan update
        market["global"] = globalmkt.build(cfg, ihsg, now, demo=args.demo)
    except Exception as e:  # noqa: BLE001
        log.warning("Pasar global dilewati: %s", e)
    inline = args.inline_series or args.demo
    trk = None
    try:                          # track record live: catatan sinyal harian + portofolio kertas
        if args.demo:
            trk = track.update(None, stocks, F, None, None, None, cfg, now, demo_rows=track.demo_rows(F, comp_live, cond_live, reg, cfg))
        elif args.cache:
            trk = track.update(Path(__file__).resolve().parents[1] / "track" / "idx.json", stocks, F, market["gate"]["open"],
                               float(reg["ihsg"].iloc[-1]), regime_label, cfg, now)
    except Exception as e:  # noqa: BLE001
        log.warning("Track record dilewati: %s", e)
    # profil & fundamental (tab DES/FA) — hanya informasi, tidak memengaruhi sinyal/backtest
    fcfg = cfg.get("fundamentals", {})
    if args.demo:
        fund = {s["ticker"]: fprev[s["ticker"]] for s in stocks if s["signal"] != "AVOID" and s["ticker"] in fprev} \
            or fundamentals.demo([s["ticker"] for s in stocks if s["signal"] != "AVOID"], {s["ticker"]: s["last"] for s in stocks})
    elif args.cache and fcfg.get("enabled", True):
        val = F["avg_val20"].iloc[-1].dropna().sort_values(ascending=False)
        order = [t for t in val.index if val[t] >= float(fcfg.get("min_value_bn", 1)) * 1e9]
        fpath = Path(args.cache).parent / "fundamentals.json"
        try:                      # data pelengkap: kegagalannya tidak boleh menggagalkan update sinyal
            light = "ringan" in refresh_mode and fpath.exists()
            fund = fundamentals.refresh(order, fpath, int(fcfg.get("max_age_days", 7)),
                                        float(fcfg.get("budget_light_s", 90) if light else fcfg.get("budget_s", 420)))
            fund = {t: fund[t] for t in order if t in fund and (fund[t].get("mcap") or fund[t].get("years"))}
        except Exception as e:  # noqa: BLE001
            log.warning("Fundamental dilewati: %s", e)
            fund = {}
    else:
        fund = {}
    for t in [x for x in ("BBCA", "TLKM", "ADRO", "ASII") if x in fund] or list(fund)[:3]:      # contoh di log supaya kewajaran datanya bisa dicek
        q = fund[t]
        log.info("Fundamental contoh %s: kap %.0f T | PER %s PBV %s ROE %s NPM %s DER %s | DPS %s | %s | tahun %s", t, (q.get("mcap") or 0) / 1e12,
                 q.get("pe"), q.get("pbv"), q.get("roe"), q.get("npm"), q.get("der"), q.get("dps"), q.get("cur"),
                 [(y["y"], round((y.get("rev") or 0) / 1e12, 1), round((y.get("ni") or 0) / 1e12, 1), round((y.get("fcf") or 0) / 1e12, 1),
                   round((y.get("ebitda") or 0) / 1e12, 1)) for y in q.get("years", [])])
        log.info("  %s FCF %s EBITDA %s utang %s kas %s (triliun)", t, *[None if q.get(k) is None else round(q[k] / 1e12, 1) for k in ("fcf", "ebitda", "debt", "cash")])
    nfs = sum(1 for q in fund.values() if (q.get("fs") or {}).get("a"))
    log.info("Laporan keuangan: %d saham punya data tahunan, %d punya data kuartalan", nfs, sum(1 for q in fund.values() if (q.get("fs") or {}).get("q")))
    for t in [x for x in ("BBCA", "TLKM") if x in fund]:
        fs = fund[t].get("fs") or {}
        for fr in ("a", "q"):
            b = fs.get(fr) or {}
            log.info("  %s %s periode %s | baris %s | pendapatan %s | laba %s", t, fr, b.get("p"), sorted(k for k in b if k not in ("p", "end")),
                     [None if v is None else round(v / 1e12, 2) for v in b.get("rev", [])], [None if v is None else round(v / 1e12, 2) for v in b.get("ni", [])])
        log.info("  %s dividen %s | split %s | kalender %s", t, fund[t].get("dvd", [])[-4:], fund[t].get("split"), fund[t].get("cal"))
        log.info("  %s konsensus: target %s (%s analis) EPS depan %s rekomendasi %s", t, fund[t].get("tgt"), fund[t].get("n_an"), fund[t].get("feps"), fund[t].get("rec_k"))
    fund_out = {"source": "SIMULASI" if args.demo else "Yahoo Finance", "n": len(fund), "items": fund}
    if inline:
        for s in stocks:
            s["series"] = series[s["ticker"]]

    out = {
        "meta": {
            "version": VERSION, "mode": "demo" if args.demo else "live",
            "generated_at": now.isoformat(timespec="seconds"),
            "data_asof": F["c"].index[-1].strftime("%Y-%m-%d"),
            "market_status": market_status(now),
            "sources": {
                "prices": "SIMULASI (bukan harga pasar)" if args.demo else "Yahoo Finance (.JK, delay ±10–15 menit)",
                "foreign_flow": "BEI (idx.co.id)" if foreign is not None else "tidak tersedia — estimasi CLV x nilai transaksi",
                "sentiment": sent.get("method", "leksikon"),
            },
            "foreign_available": foreign is not None,
            "warnings": warnings, "stale": False,
            "universe": {**uinfo, "total": len(stocks), "liquid": int(liq_now.sum()),
                         "nodata": len(nodata), "refresh": refresh_mode},
            "series": "inline" if inline else "files",
            "locked": bool(crypto.creds()) and not args.demo,
            "site_url": site_url,
        },
        "config": {"weights": cfg["weights"], "signal": cfg["signal"], "filters": cfg["filters"],
                   "regime_exposure": cfg["regime_exposure"], "portfolio": cfg["portfolio_defaults"],
                   "risk": {k: cfg["backtest"].get(k) for k in ("sizing", "risk_per_trade", "max_weight", "max_positions",
                                                                "realistic_fills", "dd_brake")}},
        "rules": rules_table(cfg),
        "market": market,
        "dates": dates,
        "stocks": stocks,
        "news": sent.get("news", [])[:300],
        "sentiment": {"method": sent.get("method"), "updated": sent.get("updated"), "market": sent.get("market")},
        "backtest": bt,
    }
    if inline:
        out["fund"] = fund_out
        if trk:
            out["track"] = trk
    c = None if args.demo else crypto.creds()

    def put(obj, path):
        if c:
            obj = crypto.encrypt(json.dumps(obj, cls=_Enc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), *c)
        _write(obj, path)

    if not inline:   # data chart per saham: satu file kecil per ticker, dimuat saat saham dibuka
        sdir = Path(args.out).parent / "s"
        if sdir.exists():
            for f in sdir.glob("*.json"):
                f.unlink()
        for t, v in series.items():
            put(v, sdir / f"{t}.json")
        if trk:
            put(trk, Path(args.out).parent / "track.json")
        fdir = Path(args.out).parent / "fs"          # laporan keuangan per saham (tab FS / EE), dimuat saat dibuka
        if fdir.exists():
            for f in fdir.glob("*.json"):
                f.unlink()
        slim = {}
        for t, q in fund.items():
            if q.get("fs"):
                put({"cur": q.get("cur"), **q["fs"]}, fdir / f"{t}.json")
            slim[t] = {k: v for k, v in q.items() if k != "fs"}
            for fr in ("a", "q"):                                 # periode laporan terakhir (untuk kalender EVTS)
                pp = ((q.get("fs") or {}).get(fr) or {}).get("p")
                if pp:
                    slim[t]["last" + fr] = pp[-1]
        put({**fund_out, "items": slim, "fs": sum(1 for q in fund.values() if q.get("fs"))}, Path(args.out).parent / "fund.json")
    put(out, args.out)
    if not args.demo:
        notify.send(prev, out, site_url)
    log.info("OK: %d saham (%d likuid, refresh %s), rezim %s, %s", len(stocks), int(liq_now.sum()), refresh_mode,
             regime_label, market["signal_count"])
    log.info("Gerbang beli: %s", market.get("gate"))
    log.info("Sinyal beli: %s", ", ".join(f"{s['ticker']}({s['signal'][0]}{s['scores']['composite']:.0f})"
                                           for s in stocks if s["signal"] in ("STRONG BUY", "BUY")) or "-")
    st, bs = bt["stats"], bt["bench"]
    log.info("Backtest %s..%s | strategi CAGR %.1f%% Sharpe %.2f MaxDD %.1f%% | IHSG CAGR %.1f%% MaxDD %.1f%% | trade %d win %.0f%% payoff %.2f PF %.2f | likuid %s",
             bt["start"], bt["end"], st["cagr"] * 100, st["sharpe"], st["max_dd"] * 100, bs["cagr"] * 100, bs["max_dd"] * 100,
             st["trades"], st["win_rate"] * 100, st["payoff"], st["profit_factor"], bt.get("universe"))
    log.info("Per tahun (strategi/IHSG): %s", " | ".join(f"{y['year']}{'*' if y['partial'] else ''} {y['ret']*100:+.1f}/{y['bench']*100:+.1f}"
                                                        for y in bt.get("yearly", [])))
    log.info("Total return strategi %.1f%% vs IHSG %.1f%% | vol %.1f%% | Kelly %.3f | modal Rp%s -> Rp%s | lot %s",
             st["total_return"] * 100, bs["total_return"] * 100, st["vol"] * 100, bt["kelly"]["full"],
             f"{bt['equity0']:,.0f}", f"{bt.get('final_equity', 0):,.0f}", bt.get("lot_skips"))
    log.info("Tanpa nama (hanya kode): %d | tanpa data/nonaktif: %d", sum(s["name"] == s["ticker"] for s in stocks), len(nodata))
    return 0


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        return str(o)


def _write(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, cls=_Enc, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    sys.exit(main())
