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
from . import universe as uni_mod
from .idx_rules import WIB, market_status, rules_table

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("run")
VERSION = "0.3.0"


def load_cfg(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fetch_prices(cfg, tickers, core, args, now, warnings):
    """Histori harga semua saham. Sekali sehari unduh penuh; run berikutnya di hari yang sama
    hanya menyegarkan saham aktif (hemat request Yahoo), sisanya dari cache."""
    period = cfg["history_period"]
    today = now.strftime("%Y-%m-%d")
    jk = lambda ts: [t + ".JK" for t in ts]            # noqa: E731
    strip = lambda d: {k[:-3]: v for k, v in d.items()}  # noqa: E731
    cache = data.load_cache(args.cache) if args.cache else None
    light = bool(cache) and cache.get("date") == today and not args.full
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
        old = (cache or {}).get("frames", {})
        kept = [t for t in tickers if t not in got and t in old]     # gagal diunduh kali ini -> pakai histori lama
        frames = {**{t: old[t] for t in kept}, **got}
        nodata = {t for t in tickers if t not in frames}
        if len(kept) > 25:
            warnings.append(f"{len(kept)} saham gagal diperbarui dari Yahoo — memakai data terakhir yang tersimpan")
        ok = len(got) >= 0.8 * len(tickers)
        today = today if ok else ""                       # unduhan tidak lengkap -> ulang penuh di run berikutnya
        mode = "penuh"
    if args.cache:
        try:
            data.save_cache(args.cache, {"date": today, "frames": frames, "nodata": sorted(nodata)})
        except Exception as e:  # noqa: BLE001
            log.warning("cache gagal disimpan: %s", e)
    frames = {t: f for t, f in frames.items() if t in set(tickers) and len(f)}
    return frames, sorted(nodata & set(tickers)), mode


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
        panels, macro = data.demo_data(universe, cfg["macro"], end=now.replace(tzinfo=None))
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
            got = data.fetch_yahoo(list(cfg["macro"].values()), cfg["history_period"])
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
    cond_live = features.conditions(F, comp_live, cfg)
    cond_hist = features.conditions(F, comp_hist, cfg)

    bt = backtest.run(F, comp_hist, cond_hist, reg, cfg)
    nb = cfg["chart_bars"]
    stocks, dates, series = signals.snapshot(F, comp_live, comp_hist, cond_live, sent, universe, cfg, regime_label, nb)
    market = signals.market_block(F, reg, macro, stocks, sent, cfg, nb)
    inline = args.inline_series or args.demo
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
                   "regime_exposure": cfg["regime_exposure"], "portfolio": cfg["portfolio_defaults"]},
        "rules": rules_table(cfg),
        "market": market,
        "dates": dates,
        "stocks": stocks,
        "news": sent.get("news", [])[:300],
        "sentiment": {"method": sent.get("method"), "updated": sent.get("updated"), "market": sent.get("market")},
        "backtest": bt,
    }
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
    put(out, args.out)
    if not args.demo:
        notify.send(prev, out, site_url)
    log.info("OK: %d saham (%d likuid, refresh %s), rezim %s, %s", len(stocks), int(liq_now.sum()), refresh_mode,
             regime_label, market["signal_count"])
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
