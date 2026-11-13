# IDX Quant Terminal

Terminal kuantitatif saham BEI bergaya Bloomberg: **money flow, sinyal IN/EXIT, position sizing sesuai modal, rezim pasar, dan sentimen berita** — update otomatis tiap ±30 menit saat jam bursa, bisa dibuka online di laptop dan dipasang sebagai **app di HP** (PWA). Gratis: jalan di GitHub Actions + GitHub Pages, tanpa server.

**Live:** https://rifqitheintrovert.github.io/idx-quant-terminal/ · **Repo:** https://github.com/rifqitheintrovert/idx-quant-terminal

> ⚠️ Bukan rekomendasi investasi. Model bisa salah. Selalu cek ulang sebelum order.

---

## Kebutuhan → fitur

| Kebutuhan | Di terminal |
|---|---|
| Inflow / outflow saham | **F2 FLOW** — net flow Rp 1H/5H/20H (CLV × nilai transaksi), CMF-20, MFI-14, OBV, lonjakan volume, status AKUMULASI/DISTRIBUSI, rotasi sektor, + net beli asing BEI bila bisa diambil |
| Kapan IN & EXIT | **F3 SIGNAL** — STRONG BUY / BUY / HOLD / REDUCE / EXIT / AVOID + zona beli, stop loss, trailing stop, TP1/TP2, R:R, alasan |
| Kombinasi posisi sesuai ekuitas | **F4 PORT** — masukkan modal → jumlah lot per saham (risk-based sizing), batas bobot saham/sektor, eksposur sesuai rezim, total risiko |
| Sesuai pasar modal Indonesia | Fraksi harga BEI, lot 100, ARA/ARB terbaru, fee beli/jual, sesi bursa WIB, long-only, universe LQ45 |
| Pendukung sentimen | **F5 NEWS** — Google News & CNBC Indonesia, leksikon keuangan ID/EN (opsional dinilai Claude) |
| Dashboard ala Bloomberg | Command line `BBCA <GO>`, function key F1–F7, ticker tape, chart candle + level trade |
| Update otomatis | GitHub Actions: tiap 30 menit 09:00–15:30 WIB + final 16:20 WIB, Senin–Jumat |
| Akses online, web & app | GitHub Pages (URL publik) + PWA “Add to Home Screen” di Android/iOS |
| Validasi | **F6 BTEST** — backtest 4 tahun vs IHSG, Sharpe, max drawdown, win rate, Kelly |

## Cara kerja

```
GitHub Actions (cron)                      GitHub Pages (web + PWA)
┌───────────────────────────────┐          ┌─────────────────────────┐
│ Yahoo Finance (.JK, IHSG, FX) │          │ index.html + app.js     │
│ BEI foreign flow (opsional)   │──engine──▶ data/latest.json        │──▶ Browser / HP
│ Google News + CNBC RSS        │  (Python)│ cek data baru tiap 5 mnt│
└───────────────────────────────┘          └─────────────────────────┘
            └──▶ Telegram alert saat sinyal berubah (opsional)
```

## Deploy (±10 menit, sekali saja)

1. Buat akun di github.com → **New repository** → nama `idx-quant-terminal` → **Public** → Create.
2. Klik **uploading an existing file** → tarik **semua isi** folder ini (termasuk folder `.github`) → **Commit changes**.
   - Folder `.github` tersembunyi di Mac/Windows. Mac: tekan `Cmd+Shift+.` di Finder. Kalau tetap tidak bisa: **Add file → Create new file**, ketik nama `.github/workflows/update.yml`, tempel isi file tersebut, commit.
3. **Settings → Pages → Source: GitHub Actions**.
4. Tab **Actions** → aktifkan workflow bila diminta → pilih **Update IDX Quant Terminal** → **Run workflow**. Tunggu ±3–5 menit sampai hijau.
5. Buka `https://USERNAME.github.io/idx-quant-terminal/` 🎉

### Pasang sebagai app di HP
- **Android (Chrome):** buka URL → menu ⋮ → **Install app / Tambahkan ke layar utama**.
- **iPhone (Safari):** buka URL → tombol Share → **Add to Home Screen**.

### Opsional
Settings → Secrets and variables → Actions → **New repository secret**:

| Secret | Fungsi |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Notifikasi Telegram saat sinyal BUY/EXIT atau rezim berubah (buat bot via @BotFather, chat id via @userinfobot) |
| `ANTHROPIC_API_KEY` | Sentimen berita dinilai Claude (lebih akurat dari leksikon). Ada biaya API kecil |

## Kustomisasi — `config.yaml`
- `universe`: daftar saham (default LQ45 periode 2 Nov 2026 – 29 Jan 2027). Tambah saham: `KODE: {name: Nama, sector: Sektor}`.
- `weights`: bobot flow / momentum / trend / sentimen / timing.
- `signal`: ambang skor, RSI overbought, kelipatan ATR untuk stop & trailing, target R, `stop_mode`.
- `idx_rules`: fee broker, ARB (asimetris 7% s/d 31 Des 2026 — update kalau BEI mengubah).
- `regime_exposure`, `portfolio_defaults`, `filters` (likuiditas minimum).

Setiap commit perubahan `config.yaml` otomatis memicu update ulang.

## Jalankan di komputer sendiri
```bash
pip install -r requirements.txt
python -m engine.run            # data live → site/data/latest.json
python -m engine.run --demo     # data simulasi (uji tampilan tanpa internet)
python -m http.server -d site 8000   # buka http://localhost:8000
python tools/build_preview.py   # 1 file HTML mandiri → dist/preview.html
```

## Model singkat
- **Skor komposit 0–100** = 30% Flow + 25% Momentum + 20% Trend + 15% Sentimen + 10% Timing.
  - Flow: peringkat cross-sectional intensitas net flow 5H/20H (dinormalisasi likuiditas), CMF, OBV, MFI, (+ asing).
  - Momentum: 12-1 & 6-1 bulan (Jegadeesh-Titman; Asness-Moskowitz-Pedersen), return 3 bulan, kedekatan 52-week high (George-Hwang).
  - Trend: harga vs MA20/50/200, golden cross, kemiringan MA50. Timing: jarak dari MA20 (ATR) & RSI.
- **Rezim pasar** (IHSG vs MA200, MA50 vs MA200, breadth, volatilitas, rupiah) membatasi eksposur: 100% / 70% / 35%.
- **Position sizing**: lot = (modal × risiko%) ÷ (entry − stop) ÷ 100, dibatasi bobot saham, sektor, dan rezim.
- **Stop berbasis close** (eksekusi besok pagi) karena stop intraday di BEI sering kena “jarum”; bisa diubah ke `intraday`.

## Keterbatasan (penting)
- **Flow = estimasi dari OHLCV**, bukan broker summary/bandarmologi asli (data itu berbayar: Stockbit, RTI, IPOT). Foreign flow BEI dicoba otomatis, tapi situs BEI sering memblokir akses bot.
- Yahoo Finance delay ±10–15 menit, kadang ada bar yang bolong; bukan feed real-time.
- Backtest belum memasukkan sentimen, dividen, ARB/antrean, dan memakai universe saat ini (**survivorship bias** → cenderung optimistis).
- GitHub cron bisa telat 5–20 menit saat ramai. Repo publik = sinyal bisa dilihat orang lain yang tahu URL-nya.

## Struktur
```
engine/   idx_rules · data · indicators · features · regime · sentiment · signals · backtest · notify · run
site/     index.html · app.js · style.css · sw.js · manifest · vendor/ · data/latest.json
tools/    build_preview.py
.github/workflows/update.yml
```
Chart: TradingView Lightweight Charts™ (Apache-2.0).
