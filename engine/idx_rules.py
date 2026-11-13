"""Aturan perdagangan Bursa Efek Indonesia: fraksi harga, lot, ARA/ARB, jam bursa."""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone

WIB = timezone(timedelta(hours=7))

TICK_TABLE = [  # (batas atas eksklusif, fraksi)
    (200, 1),
    (500, 2),
    (2000, 5),
    (5000, 10),
    (float("inf"), 25),
]


def tick_size(price: float) -> int:
    for upper, tick in TICK_TABLE:
        if price < upper:
            return tick
    return 25


def round_tick(price: float, mode: str = "nearest") -> int:
    """Bulatkan harga ke fraksi BEI. mode: nearest | down | up."""
    if price is None or not math.isfinite(price) or price <= 0:
        return 0
    t = tick_size(price)
    q = price / t
    if mode == "down":
        v = math.floor(q + 1e-9) * t
    elif mode == "up":
        v = math.ceil(q - 1e-9) * t
    else:
        v = round(q) * t
    # fraksi bisa berubah setelah dibulatkan melewati batas; ulangi sekali
    t2 = tick_size(v)
    if t2 != t:
        q = price / t2
        v = (math.floor(q) if mode == "down" else math.ceil(q) if mode == "up" else round(q)) * t2
    return int(max(v, 1))


def ara_pct(price: float) -> float:
    if price <= 10:
        return 1 / max(price, 1)  # nominal Rp1
    if price <= 200:
        return 0.35
    if price <= 5000:
        return 0.25
    return 0.20


def arb_pct(price: float, cfg_arb: float | None = 0.07) -> float:
    if price <= 14:
        return 1 / max(price, 1)  # nominal Rp1 (Rp1–Rp14)
    if cfg_arb is None:  # simetris
        return ara_pct(price)
    return cfg_arb


def market_status(now: datetime | None = None) -> str:
    """Status sesi reguler BEI (WIB). Libur bursa tidak dicek."""
    now = (now or datetime.now(WIB)).astimezone(WIB)
    wd = now.weekday()
    if wd >= 5:
        return "CLOSED"
    t = now.time()
    friday = wd == 4
    s1_end = time(11, 30) if friday else time(12, 0)
    s2_start = time(14, 0) if friday else time(13, 30)
    if time(8, 45) <= t < time(9, 0):
        return "PRE-OPEN"
    if time(9, 0) <= t < s1_end:
        return "OPEN"
    if s1_end <= t < s2_start:
        return "BREAK"
    if s2_start <= t < time(15, 50):
        return "OPEN"
    if time(15, 50) <= t < time(16, 15):
        return "PRE-CLOSE"
    return "CLOSED"


def rules_table(cfg: dict) -> dict:
    r = cfg["idx_rules"]
    return {
        "lot_size": r["lot_size"],
        "fee_buy": r["fee_buy"],
        "fee_sell": r["fee_sell"],
        "tick_table": [
            {"range": "< Rp200", "tick": 1},
            {"range": "Rp200 – <Rp500", "tick": 2},
            {"range": "Rp500 – <Rp2.000", "tick": 5},
            {"range": "Rp2.000 – <Rp5.000", "tick": 10},
            {"range": ">= Rp5.000", "tick": 25},
        ],
        "auto_rejection": [
            {"range": "Rp1 – Rp10", "ara": "Rp1", "arb": "Rp1"},
            {"range": "Rp11 – Rp14", "ara": "35%", "arb": "Rp1"},
            {"range": "Rp15 – Rp200", "ara": "35%", "arb": f"{r['arb_pct']*100:.0f}%"},
            {"range": ">Rp200 – Rp5.000", "ara": "25%", "arb": f"{r['arb_pct']*100:.0f}%"},
            {"range": "> Rp5.000", "ara": "20%", "arb": f"{r['arb_pct']*100:.0f}%"},
        ],
        "arb_valid_until": r.get("arb_valid_until"),
        "sessions": "Sen–Kam 09:00–12:00 & 13:30–15:49 · Jum 09:00–11:30 & 14:00–15:49 · pre-close 15:50–16:00 WIB",
        "settlement": "T+2",
        "short_selling": "Long-only (short selling terbatas di BEI)",
    }
