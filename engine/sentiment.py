"""Sentimen berita: RSS (Google News, CNBC Indonesia) + leksikon keuangan ID/EN.
Opsional: skor LLM (Claude) bila env ANTHROPIC_API_KEY diisi."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time as _time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("sentiment")
UA = {"User-Agent": "Mozilla/5.0 (compatible; IDXQuantTerminal/1.0)"}

# ------------------------------------------------------------------ leksikon
PHRASES = {
    # positif
    "laba bersih naik": 2.0, "laba naik": 2.0, "laba melonjak": 2.5, "laba tumbuh": 2.0, "laba meroket": 2.5,
    "laba melejit": 2.5, "rugi menyempit": 1.5, "pendapatan naik": 1.5, "pendapatan tumbuh": 1.5,
    "kinerja positif": 1.5, "kinerja moncer": 2.0, "net buy": 2.0, "net beli": 2.0, "asing borong": 2.0,
    "diborong asing": 2.0, "borong saham": 1.5, "kontrak baru": 1.5, "target harga naik": 1.5,
    "dividen jumbo": 2.0, "dividen interim": 1.2, "stock split": 0.5, "masuk lq45": 1.0, "masuk indeks": 1.0,
    "sentuh ara": 1.5, "auto reject atas": 1.5, "rekomendasi beli": 1.5, "beats estimates": 1.5,
    "profit rises": 2.0, "record high": 1.5, "all time high": 1.5,
    # negatif
    "laba turun": -2.0, "laba anjlok": -2.5, "laba merosot": -2.0, "laba tergerus": -2.0, "rugi membengkak": -2.5,
    "pendapatan turun": -1.5, "net sell": -2.0, "net jual": -2.0, "asing lepas": -2.0, "dilepas asing": -2.0,
    "asing kabur": -2.0, "jual bersih": -2.0, "gagal bayar": -3.0, "sentuh arb": -2.0, "auto reject bawah": -2.0,
    "papan pemantauan khusus": -1.5, "keluar dari indeks": -1.0, "ott kpk": -2.5, "target harga turun": -1.5,
    "misses estimates": -1.5, "profit falls": -2.0,
}
WORDS = {
    # positif
    "melonjak": 1.5, "melesat": 1.5, "meroket": 1.5, "melejit": 1.5, "menguat": 1.0, "naik": 0.5, "rebound": 1.0,
    "bullish": 1.5, "cuan": 1.0, "positif": 1.0, "optimis": 1.0, "optimistis": 1.0, "tumbuh": 1.0, "rekor": 1.0,
    "dividen": 1.0, "buyback": 1.5, "akumulasi": 1.5, "ekspansi": 1.0, "akuisisi": 0.5, "upgrade": 1.5,
    "outperform": 1.5, "overweight": 1.0, "ara": 1.5, "hijau": 0.7, "laba": 0.3, "surplus": 0.5,
    "surge": 1.5, "jump": 1.0, "rally": 1.2, "gain": 0.8, "beats": 1.5, "record": 1.0, "upbeat": 1.0,
    # negatif
    "anjlok": -2.0, "ambruk": -2.0, "longsor": -1.5, "merosot": -1.5, "melemah": -1.0, "turun": -0.5,
    "terkoreksi": -1.0, "koreksi": -0.7, "arb": -2.0, "distribusi": -1.0, "bearish": -1.5, "gugatan": -1.5,
    "digugat": -1.5, "pkpu": -2.5, "pailit": -3.0, "suspensi": -2.5, "disuspensi": -2.5, "default": -2.5,
    "denda": -1.0, "sanksi": -1.5, "fraud": -3.0, "korupsi": -2.0, "tersangka": -2.0, "downgrade": -1.5,
    "underperform": -1.5, "underweight": -1.0, "negatif": -1.0, "tertekan": -1.0, "pesimis": -1.0,
    "terdepak": -1.0, "delisting": -3.0, "phk": -1.0, "boncos": -1.5, "jeblok": -2.0, "nyungsep": -2.0,
    "merah": -0.7, "rugi": -1.5, "plunge": -2.0, "slump": -1.5, "falls": -0.7, "drop": -0.8, "loss": -1.0,
    "lawsuit": -1.5, "bankruptcy": -3.0, "misses": -1.5, "selloff": -1.5,
}
NEGATORS = {"tidak", "tak", "belum", "bukan", "batal", "gagal", "not", "no"}
BANK_ALIASES = {"BBCA": ["BCA"], "BBRI": ["BRI"], "BBNI": ["BNI"], "BBTN": ["BTN"], "BMRI": ["Mandiri"],
                "TLKM": ["Telkom"], "ASII": ["Astra"], "UNVR": ["Unilever"], "ANTM": ["Antam"],
                "GOTO": ["GoTo"], "ISAT": ["Indosat"], "EXCL": ["XLSmart", "XL Axiata"]}
STOP_ALIAS = {"Bank", "Indo", "Sumber", "Solusi", "Perusahaan", "Darma", "Elang", "Mitra", "Semen", "United",
              "Indah", "Merdeka", "Aneka", "Bukit", "Barito", "Trimegah", "Vale", "Hartadinata"}


SUBJ_POS = {"laba", "pendapatan", "penjualan", "kinerja", "profit", "revenue", "earnings", "dividen", "marketing"}
SUBJ_NEG = {"rugi", "beban", "utang", "loss"}
DIR_UP = {"naik", "membengkak", "tumbuh", "melonjak", "melesat", "meroket", "melejit", "meningkat", "bertambah", "rises", "jumps", "up"}
DIR_DN = {"turun", "anjlok", "merosot", "menyusut", "tergerus", "melemah", "falls", "drops", "down", "menyempit"}
_PH = sorted(((tuple(k.split()), v) for k, v in PHRASES.items()), key=lambda x: -len(x[0]))


def score_text(text: str) -> float:
    """Skor -1..+1 sebuah headline: frasa > kata, negasi 3 token, aturan 'subjek + arah' (mis. 'laba ... naik')."""
    toks = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    total, i, used = 0.0, 0, set()
    while i < len(toks):
        hit = None
        for ph, w in _PH:
            if tuple(toks[i:i + len(ph)]) == ph:
                hit = (len(ph), w)
                break
        n, w = hit if hit else (1, WORDS.get(toks[i]))
        if w is not None:
            if any(x in NEGATORS for x in toks[max(0, i - 3):i]):
                w = -0.8 * w
            total += w
            used.update(range(i, i + n))
        i += n
    # subjek + arah dalam jendela 4 token (menangkap "Laba Bersih BBCA Naik", "Rugi INCO Menyempit")
    for j, tok in enumerate(toks):
        if tok in SUBJ_POS or tok in SUBJ_NEG:
            win = toks[j + 1:j + 5]
            up = any(x in DIR_UP for x in win)
            dn = any(x in DIR_DN for x in win)
            if up == dn:
                continue
            good = up if tok in SUBJ_POS else dn
            total += 1.5 if good else -1.5
            if tok in SUBJ_NEG and good:      # "rugi menyempit": batalkan penalti kata "rugi"
                total += -WORDS.get(tok, 0)
    return math.tanh(total / 2.5)


def aliases_for(ticker: str, name: str) -> list[str]:
    al = [ticker] + BANK_ALIASES.get(ticker, [])
    first = name.split()[0]
    if len(first) >= 5 and first not in STOP_ALIAS:
        al.append(first)
    return al


def _match(title: str, aliases: list[str]) -> bool:
    for a in aliases:
        if a.isupper():
            if re.search(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])", title):
                return True
        elif re.search(rf"\b{re.escape(a)}\b", title, flags=re.I):
            return True
    return False


# ------------------------------------------------------------------ fetch
def _parse_feed(url: str) -> list[dict]:
    import feedparser
    try:
        r = requests.get(url, headers=UA, timeout=15)
        if r.status_code != 200:
            return []
        fp = feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001
        log.warning("feed gagal %s: %s", url[:60], e)
        return []
    items = []
    for e in fp.entries:
        title = (e.get("title") or "").strip()
        src = ""
        if " - " in title:
            title, src = title.rsplit(" - ", 1)
        src = src or (e.get("source", {}) or {}).get("title", "") or re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        ts = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                ts = datetime(*e[k][:6], tzinfo=timezone.utc)
                break
        items.append({"title": title, "source": src, "link": e.get("link", ""), "ts": ts})
    return items


_CODE = re.compile(r"(?<![A-Za-z])[A-Z]{4}(?![A-Za-z])")


def make_matcher(universe: dict, named: set[str] | None = None):
    """Pencocok headline -> ticker yang efisien untuk ratusan saham.
    Semua saham dicocokkan lewat kode 4 huruf kapital; nama perusahaan hanya untuk `named`."""
    codes = set(universe)
    named = set(universe) if named is None else named
    pats = []
    for t in named:
        if t not in universe:
            continue
        for a in aliases_for(t, universe[t]["name"])[1:]:
            pats.append((t, re.compile(rf"(?<![A-Za-z]){re.escape(a)}(?![A-Za-z])" if a.isupper()
                                       else rf"\b{re.escape(a)}\b", 0 if a.isupper() else re.I)))

    def match(title: str) -> list[str]:
        letters = [ch for ch in title if ch.isalpha()]
        shouting = letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.6   # judul KAPITAL semua
        hit = set() if shouting else (set(_CODE.findall(title)) & codes)
        hit.update(t for t, p in pats if p.search(title))
        return sorted(hit)

    return match


def fetch_news(universe: dict, cfg: dict, focus: list[str] | None = None) -> list[dict]:
    """`focus` = saham yang dicarikan beritanya satu per satu (mis. yang paling likuid).
    Saham lain tetap ikut terdeteksi bila kodenya muncul di headline mana pun."""
    sc = cfg["sentiment"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=sc["lookback_days"])
    focus = list(universe) if focus is None else [t for t in focus if t in universe]
    match = make_matcher(universe, set(focus))
    news: dict[str, dict] = {}

    def add(it, tickers):
        if not it["title"] or (it["ts"] and it["ts"] < cutoff):
            return
        key = hashlib.md5(it["title"].lower().encode()).hexdigest()[:10]
        if key in news:
            news[key]["tickers"] = sorted(set(news[key]["tickers"]) | set(tickers))
            return
        news[key] = {"id": key, "title": it["title"], "source": it["source"], "link": it["link"],
                     "ts": (it["ts"] or datetime.now(timezone.utc)).isoformat(), "tickers": sorted(tickers)}

    for url in sc["market_feeds"]:
        for it in _parse_feed(url):
            add(it, match(it["title"]))
    for t in focus:
        kept = 0
        for it in _parse_feed(sc["ticker_feed"].format(ticker=t)):
            hit = match(it["title"])
            if t in hit:
                add(it, hit)
                kept += 1
                if kept >= sc["max_items_per_ticker"]:
                    break
        _time.sleep(0.4)
    return list(news.values())


# ------------------------------------------------------------------ LLM opsional
def llm_scores(news: list[dict], model: str) -> dict[str, float]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not news:
        return {}
    out = {}
    for i in range(0, len(news), 60):
        batch = news[i:i + 60]
        lines = "\n".join(f'{n["id"]}|{",".join(n["tickers"]) or "MARKET"}|{n["title"]}' for n in batch)
        prompt = ("Kamu analis saham Indonesia. Untuk tiap headline (format id|ticker|judul), beri skor dampak "
                  "jangka pendek terhadap harga saham terkait, -1 (sangat negatif) s/d +1 (sangat positif), 0 netral. "
                  "Balas HANYA JSON object {\"id\": skor}.\n\n" + lines)
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 2500, "messages": [{"role": "user", "content": prompt}]})
            txt = r.json()["content"][0]["text"]
            js = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
            out.update({k: max(-1.0, min(1.0, float(v))) for k, v in js.items()})
        except Exception as e:  # noqa: BLE001
            log.warning("LLM sentiment gagal: %s", e)
    return out


# ------------------------------------------------------------------ agregasi
def aggregate(news: list[dict], universe: dict, cfg: dict, llm: dict | None = None) -> dict:
    hl = cfg["sentiment"]["half_life_days"]
    now = datetime.now(timezone.utc)
    llm = llm or {}
    for n in news:
        lex = score_text(n["title"])
        n["score_lex"] = round(lex, 3)
        n["score"] = round(0.7 * llm[n["id"]] + 0.3 * lex, 3) if n["id"] in llm else round(lex, 3)
        n["method"] = "llm+lex" if n["id"] in llm else "lexicon"
    per, by_t = {}, {}
    for n in news:
        for t in n["tickers"]:
            by_t.setdefault(t, []).append(n)
    for t in universe:
        items = by_t.get(t, [])
        if not items:
            per[t] = {"score": 50.0, "raw": 0.0, "n": 0, "n7": 0, "pos": 0, "neg": 0}
            continue
        ws, tot = 0.0, 0.0
        n7 = 0
        for n in items:
            age = max(0.0, (now - datetime.fromisoformat(n["ts"])).total_seconds() / 86400)
            w = 0.5 ** (age / hl)
            ws += w
            tot += w * n["score"]
            n7 += age <= 7
        raw = tot / ws if ws else 0.0
        conf = len(items) / (len(items) + 3)          # shrinkage: sedikit berita -> mendekati netral
        per[t] = {"score": round(50 + 50 * raw * conf, 1), "raw": round(raw, 3), "n": len(items), "n7": n7,
                  "pos": sum(n["score"] > 0.15 for n in items), "neg": sum(n["score"] < -0.15 for n in items)}
    allsc = [n["score"] for n in news]
    mkt = sum(allsc) / len(allsc) if allsc else 0.0
    news.sort(key=lambda n: n["ts"], reverse=True)
    return {
        "per_ticker": per,
        "market": {"score": round(50 + 50 * mkt, 1), "raw": round(mkt, 3), "n": len(news),
                   "pos": sum(s > 0.15 for s in allsc), "neg": sum(s < -0.15 for s in allsc)},
        "news": news[:300],
        "method": "Claude + leksikon" if llm else "leksikon ID/EN",
        "updated": now.isoformat(),
    }


def demo_sentiment(universe: dict, seed: int = 11) -> dict:
    import numpy as np
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc)
    news = []
    tones = [(0.6, "positif"), (0.3, "cenderung positif"), (0.0, "netral"), (-0.35, "cenderung negatif"),
             (-0.65, "negatif")]
    for t in universe:
        for j in range(int(rng.integers(0, 5))):
            s, lab = tones[int(rng.integers(0, len(tones)))]
            s = float(np.clip(s + rng.normal(0, 0.12), -1, 1))
            ts = now - timedelta(hours=float(rng.uniform(1, 24 * 12)))
            hid = hashlib.md5(f"{t}{j}".encode()).hexdigest()[:10]
            news.append({"id": hid, "title": f"[SIMULASI] Contoh headline {lab} terkait {t}",
                         "source": "demo", "link": "", "ts": ts.isoformat(), "tickers": [t]})
            news[-1]["_s"] = s
    llm = {n["id"]: n.pop("_s") for n in news}
    cfg = {"sentiment": {"half_life_days": 3}}
    agg = aggregate(news, universe, cfg, llm)
    for n in agg["news"]:
        n["method"] = "simulasi"
    agg["method"] = "SIMULASI"
    return agg
