"""Alert Telegram saat sinyal berubah (opsional: secret TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID)."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("notify")
WATCH = {"STRONG BUY", "BUY", "EXIT"}


def _fmt(x):
    return f"{x:,.0f}".replace(",", ".") if x is not None else "-"


def changes(prev: dict | None, new: dict) -> list[str]:
    old = {s["ticker"]: s["signal"] for s in (prev or {}).get("stocks", [])}
    if not old:
        return []
    msgs = []
    for s in new["stocks"]:
        before, now = old.get(s["ticker"]), s["signal"]
        if now != before and (now in WATCH or before in WATCH):
            lv = s["levels"]
            line = f"<b>{s['ticker']}</b> {before or '-'} → <b>{now}</b> @ {_fmt(s['last'])} | skor {s['scores']['composite']:.0f}"
            if now in ("BUY", "STRONG BUY"):
                line += f"\n  zona {_fmt(lv['entry_low'])}–{_fmt(lv['entry_high'])} · SL {_fmt(lv['sl'])} · TP {_fmt(lv['tp1'])}/{_fmt(lv['tp2'])}"
            msgs.append(line)
    return msgs


def send(prev: dict | None, new: dict, site_url: str | None):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    msgs = changes(prev, new)
    if prev and (prev.get("market", {}).get("regime", {}).get("label") != new["market"]["regime"]["label"]):
        msgs.insert(0, f"⚠️ Rezim pasar: {prev['market']['regime']['label']} → <b>{new['market']['regime']['label']}</b>")
    if not msgs:
        return
    text = "📊 <b>IDX Quant Terminal</b>\n" + "\n".join(msgs[:25])
    if site_url:
        text += f"\n\n{site_url}"
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram gagal: %s", e)
