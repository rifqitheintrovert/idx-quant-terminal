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

from . import backtest, data, features, notify, regime, sentiment, signals
from .idx_rules import WIB, market_status, rules_table

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("run")
VERSION = "0.1.0"


def load_cfg(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out", default=str(ROOT / "site" / "data" / "latest.json"))
    ap.add_argument("--no-news", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = load_cfg(Path(args.config))
    universe = cfg["universe"]
    tickers = list(universe)
    site_url = os.environ.get("SITE_URL")
    warnings: list[str] = []
    now = datetime.now(WIB)
    prev = None if args.demo else data.fetch_previous(site_url)

    # ---------------- harga ----------------
    if args.demo:
        panels, macro = data.demo_data(universe, cfg["macro"], end=now.replace(tzinfo=None))
        foreign = None
    else:
        try:
            frames = data.fetch_yahoo([t + ".JK" for t in tickers], cfg["history_period"])
            frames = {k.replace(".JK", ""): v for k, v in frames.items()}
        except Exception as e:  # noqa: BLE001
            log.error("Gagal ambil harga: %s", e)
            if prev:
                prev["meta"]["warnings"] = [f"Update gagal ({e}); menampilkan data sebelumnya"] + prev["meta"].get("warnings", [])
                prev["meta"]["stale"] = True
                _write(prev, args.out)
                return 0
            raise
        missing = [t for t in tickers if t not in frames]
        if missing:
            warnings.append("Data tidak tersedia: " + ", ".join(missing))
        tickers = [t for t in tickers if t in frames]
        universe = {t: universe[t] for t in tickers}
        panels = data.build_panels(frames, tickers)
        mframes = {}
        try:
            got = data.fetch_yahoo(list(cfg["macro"].values()), "2y")
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

    # ---------------- sentimen ----------------
    if args.demo:
        sent = sentiment.demo_sentiment(universe)
    elif args.no_news:
        sent = sentiment.aggregate([], universe, cfg)
    else:
        sent = None
        ps = (prev or {}).get("sentiment")
        if ps and ps.get("updated"):
            age = datetime.now(WIB) - datetime.fromisoformat(ps["updated"]).astimezone(WIB)
            if age < timedelta(minutes=110):
                sent = ps
                sent["per_ticker"] = {s["ticker"]: s.get("sent", {}) for s in prev["stocks"]}
                sent["market"] = prev["market"]["sentiment"]
        if sent is None:
            try:
                news = sentiment.fetch_news(universe, cfg)
                llm = sentiment.llm_scores(news, cfg["sentiment"]["llm_model"])
                sent = sentiment.aggregate(news, universe, cfg, llm)
                if not news:
                    warnings.append("Tidak ada berita terambil — sentimen netral")
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Sentimen gagal: {e}")
                sent = sentiment.aggregate([], universe, cfg)

    sent_panel = pd.DataFrame(50.0, index=F["c"].index, columns=F["c"].columns)
    for t in F["c"].columns:
        sent_panel.iloc[-1, sent_panel.columns.get_loc(t)] = sent["per_ticker"].get(t, {}).get("score", 50.0)
    comp_live = features.composite(F, cfg["weights"], sent_panel)
    comp_hist = features.composite(F, cfg["weights"], None)
    cond_live = features.conditions(F, comp_live, cfg)
    cond_hist = features.conditions(F, comp_hist, cfg)

    bt = backtest.run(F, comp_hist, cond_hist, reg, cfg)
    nb = cfg["chart_bars"]
    stocks, dates = signals.snapshot(F, comp_live, comp_hist, cond_live, sent, universe, cfg, regime_label, nb)
    market = signals.market_block(F, reg, macro, stocks, sent, cfg, nb)

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
            "site_url": site_url,
        },
        "config": {"weights": cfg["weights"], "signal": cfg["signal"], "filters": cfg["filters"],
                   "regime_exposure": cfg["regime_exposure"], "portfolio": cfg["portfolio_defaults"]},
        "rules": rules_table(cfg),
        "market": market,
        "dates": dates,
        "stocks": stocks,
        "news": sent.get("news", [])[:200],
        "sentiment": {"method": sent.get("method"), "updated": sent.get("updated"), "market": sent.get("market")},
        "backtest": bt,
    }
    _write(out, args.out)
    if not args.demo:
        notify.send(prev, out, site_url)
    log.info("OK: %d saham, rezim %s, %s", len(stocks), regime_label, market["signal_count"])
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
