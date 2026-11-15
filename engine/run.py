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
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import backtest, crypto, data, features, notify, regime, sentiment, signals
from . import fundamentals
from . import universe as uni_mod
from .idx_rules import WIB, market_status, rules_table

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("run")
VERSION = "0.6.1"


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
    nb = cfg["chart_bars"]
    stocks, dates, series = signals.snapshot(F, comp_live, comp_hist, cond_live, sent, universe, cfg, regime_label, nb)
    market = signals.market_block(F, reg, macro, stocks, sent, cfg, nb)
    inline = args.inline_series or args.demo
    # profil & fundamental (tab DES/FA) — hanya informasi, tidak memengaruhi sinyal/backtest
    fcfg = cfg.get("fundamentals", {})
    if args.demo:
        fund = fundamentals.demo([s["ticker"] for s in stocks if s["signal"] != "AVOID"], {s["ticker"]: s["last"] for s in stocks})
    elif args.cache and fcfg.get("enabled", True):
        val = F["avg_val20"].iloc[-1].dropna().sort_values(ascending=False)
        order = [t for t in val.index if val[t] >= float(fcfg.get("min_value_bn", 1)) * 1e9]
        fpath = Path(args.cache).parent / "fundamentals.json"
        try:                      # data pelengkap: kegagalannya tidak boleh menggagalkan update sinyal
            fund = fundamentals.refresh(order, fpath, int(fcfg.get("max_age_days", 7)), float(fcfg.get("budget_s", 240)),
                                        fetch="ringan" not in refresh_mode or not fpath.exists())
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
        put(fund_out, Path(args.out).parent / "fund.json")
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
