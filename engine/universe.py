"""Universe saham: SEMUA saham tercatat di BEI (mode `all`) atau hanya daftar di config (mode `config`).

Daftar lengkap diambil dari Yahoo Finance screener (exchange JKT) dan disimpan di
engine/idx_universe.json supaya run berikutnya tidak tergantung screener. Saham yang
tidak likuid TIDAK dibuang: tetap tampil, tapi model memberi label AVOID."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("universe")
CACHE = Path(__file__).with_name("idx_universe.json")
SEED = Path(__file__).with_name("idx_seed.txt")
SEED_SEC = {"F": "Financials", "E": "Energy", "CC": "Consumer Cyclicals", "CN": "Consumer Non-Cyclicals",
            "BM": "Basic Materials", "IF": "Infrastructures", "PR": "Properties", "IN": "Industrials",
            "T": "Technology", "H": "Healthcare", "TL": "Transportation"}
SYM = re.compile(r"^[A-Z]{4}\.JK$")
OTHER = "Lainnya"
CACHE_V = 2   # naikkan bila cara mengambil daftar berubah -> cache lama dianggap usang
# sektor Yahoo -> padanan terdekat IDX-IC
YH2IDX = {
    "Financial Services": "Financials",
    "Basic Materials": "Basic Materials",
    "Energy": "Energy",
    "Consumer Cyclical": "Consumer Cyclicals",
    "Consumer Defensive": "Consumer Non-Cyclicals",
    "Healthcare": "Healthcare",
    "Industrials": "Industrials",
    "Real Estate": "Properties",
    "Technology": "Technology",
    "Communication Services": "Infrastructures",
    "Utilities": "Infrastructures",
}


def _clean(name: str | None, fallback: str) -> str:
    n = (name or "").strip()
    n = re.sub(r"^(PT\.?|P\.T\.)\s+", "", n, flags=re.I)
    n = re.sub(r",?\s*\(?Persero\)?", "", n, flags=re.I)
    n = re.sub(r",?\s+Tbk\.?$", "", n, flags=re.I).strip(" ,.")
    return n or fallback


def fetch_screener(max_pages: int = 12) -> dict[str, dict]:
    """Semua saham exchange JKT dari Yahoo screener, lengkap dengan sektor."""
    import time

    import yfinance as yf
    from yfinance import EquityQuery

    base = [EquityQuery("eq", ["region", "id"]), EquityQuery("eq", ["exchange", "JKT"])]
    out: dict[str, dict] = {}

    def pages(query, sort="ticker", asc=True):
        off = 0
        for _ in range(max_pages):
            r = yf.screen(query, offset=off, size=250, sortField=sort, sortAsc=asc) or {}
            quotes = r.get("quotes") or []
            yield from quotes
            off += len(quotes)
            if not quotes or off >= int(r.get("total") or 0):
                break
            time.sleep(0.4)

    def add(q, sector):
        sym = q.get("symbol") or ""
        if not SYM.match(sym):
            return
        t = sym[:-3]
        if t not in out:
            out[t] = {"name": _clean(q.get("longName") or q.get("shortName"), t), "sector": sector}

    for ysec, isec in YH2IDX.items():
        try:
            for q in pages(EquityQuery("and", base + [EquityQuery("eq", ["sector", ysec])])):
                add(q, isec)
        except Exception as e:  # noqa: BLE001
            log.warning("screener sektor %s gagal: %s", ysec, e)
    n_sec = len(out)
    # sisanya (tanpa sektor di Yahoo). Dua urutan sort: urut kapitalisasi bisa membuang saham tanpa market cap.
    for sort, asc in (("ticker", True), ("intradaymarketcap", False)):
        try:
            for q in pages(EquityQuery("and", base), sort, asc):
                add(q, OTHER)
        except Exception as e:  # noqa: BLE001
            log.warning("screener (%s) gagal: %s", sort, e)
    log.info("screener: %d saham bersektor + %d tanpa sektor", n_sec, len(out) - n_sec)
    return out


def read_seed() -> dict[str, str]:
    """Kode -> sektor IDX-IC dari daftar benih (melengkapi saham yang dilewatkan Yahoo screener)."""
    out = {}
    try:
        for line in SEED.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                continue
            for tok in line.split():
                code, _, sec = tok.partition(":")
                if re.fullmatch(r"[A-Z]{4}", code) and sec in SEED_SEC:
                    out[code] = SEED_SEC[sec]
    except Exception as e:  # noqa: BLE001
        log.warning("seed tidak terbaca: %s", e)
    return out


def _read_cache() -> dict | None:
    try:
        js = json.loads(CACHE.read_text(encoding="utf-8"))
        return js if js.get("tickers") else None
    except Exception:  # noqa: BLE001
        return None


def _write_cache(tickers: dict[str, dict]):
    body = {"v": CACHE_V, "updated": date.today().isoformat(), "source": "Yahoo Finance screener (exchange JKT)",
            "count": len(tickers), "tickers": {t: [v["name"], v["sector"]] for t, v in sorted(tickers.items())}}
    CACHE.write_text(json.dumps(body, ensure_ascii=False, indent=0), encoding="utf-8")


def load(cfg: dict, refresh: bool = True) -> tuple[dict, dict, list[str]]:
    """-> (universe {ticker: {name, sector}}, info, warnings)"""
    core = cfg["universe"]
    overrides = {**(cfg.get("universe_extra") or {}), **core}      # nama & sektor IDX-IC yang sudah dikurasi
    warns: list[str] = []
    if cfg.get("universe_mode", "all") != "all":
        return dict(overrides), {"mode": "config", "source": "config.yaml"}, warns

    cached = _read_cache()
    age = 10**6
    if cached:
        try:
            age = (date.today() - datetime.strptime(cached["updated"], "%Y-%m-%d").date()).days
        except Exception:  # noqa: BLE001
            pass
    listed = {t: {"name": v[0], "sector": v[1]} for t, v in cached["tickers"].items()} if cached else None
    if cached and int(cached.get("v", 1)) < CACHE_V:
        age = 10**6
    if refresh and age >= int(cfg.get("universe_refresh_days", 7)):
        try:
            fresh = fetch_screener()
            if len(fresh) >= 500:
                # sektor yang hilang di Yahoo: pertahankan sektor dari cache lama
                for t, v in fresh.items():
                    if v["sector"] == OTHER and listed and listed.get(t, {}).get("sector", OTHER) != OTHER:
                        v["sector"] = listed[t]["sector"]
                for t, v in (listed or {}).items():      # screener kadang melewatkan saham -> jangan dibuang
                    fresh.setdefault(t, v)
                _write_cache(fresh)
                listed, age = fresh, 0
                log.info("universe: %d saham dari Yahoo screener", len(fresh))
            else:
                log.warning("universe: screener hanya mengembalikan %d saham — diabaikan", len(fresh))
        except Exception as e:  # noqa: BLE001
            log.warning("universe: screener gagal: %s", e)
    seed = read_seed()
    if not listed and not seed:
        warns.append("Daftar lengkap saham BEI belum bisa diambil — sementara memakai daftar di config.yaml")
        return dict(overrides), {"mode": "config (fallback)", "source": "config.yaml"}, warns
    uni = {t: dict(v) for t, v in (listed or {}).items()}
    for t, sec in seed.items():                      # sektor IDX-IC dari seed lebih akurat daripada pemetaan Yahoo
        uni[t] = {"name": uni.get(t, {}).get("name", t), "sector": sec}
    for t, v in overrides.items():
        uni[t] = dict(v)
    info = {"mode": "all", "source": "Yahoo Finance screener + daftar BEI (seed)", "listed_yahoo": len(listed or {}),
            "listed_seed": len(seed)}
    return uni, info, warns
