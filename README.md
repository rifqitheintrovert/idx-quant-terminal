# IDX Quant Terminal

Terminal kuantitatif saham BEI bergaya Bloomberg: **money flow, sinyal IN/EXIT, position sizing sesuai modal, rezim pasar, dan sentimen berita** — update otomatis tiap ±30 menit saat jam bursa, bisa dibuka online di laptop dan dipasang sebagai **app di HP** (PWA). Gratis: jalan di GitHub Actions + GitHub Pages, tanpa server.

**Live:** https://rifqitheintrovert.github.io/idx-quant-terminal/ · **Repo:** https://github.com/rifqitheintrovert/idx-quant-terminal

> ⚠️ Bukan rekomendasi investasi. Model bisa salah. Selalu cek ulang sebelum order.

---

## Kebutuhan → fitur

| Kebutuhan | Di terminal |
|---|---|
| Inflow / outflow saham | **F2 FLOW** — net flow Rp 1H/5H/20H (CLV × nilai transaksi), CMF-20, MFI-14, OBV, lonjakan volume, status AKUMULASI/DISTRIBUSI, rotasi sektor, + net beli asing BEI bila bisa diambil |
| Kapan IN & EXIT | **F3 SIGNAL** — STRONG BUY / BUY / HOLD / REDUCE / EXIT / AVOID + zona beli, stop loss, trailing stop, TP1/TP2, R:R, alasan. Kolom **Syarat** menunjukkan berapa syarat beli yang sudah lolos (semua lolos = BUY, sama dengan aturan backtest); filter **KANDIDAT** = saham yang lolos syarat inti momentum + inflow akumulasi |
| Kombinasi posisi sesuai ekuitas | **F4 PORT** — masukkan modal → jumlah lot per saham (risk-based sizing), batas bobot saham/sektor, eksposur sesuai rezim, total risiko |
| Sesuai pasar modal Indonesia | Fraksi harga BEI, lot 100, ARA/ARB terbaru, fee beli/jual, sesi bursa WIB, long-only, **semua saham BEI** (filter likuiditas otomatis) |
| Pendukung sentimen | **F5 NEWS** — Google News & CNBC Indonesia, leksikon keuangan ID/EN (opsional dinilai Claude) |
| Dashboard ala Bloomberg | Command line `BBCA <GO>`, function key F1–F7, ticker tape, chart candle + level trade |
| Update otomatis | GitHub Actions: tiap 30 menit 09:00–15:30 WIB + final 16:20 WIB, Senin–Jumat |
| Akses online, web & app | GitHub Pages (URL publik) + PWA “Add to Home Screen” di Android/iOS |
| Validasi | **F6 BTEST** — backtest 10 tahun vs IHSG, return per tahun, Sharpe, max drawdown, win rate, Kelly |

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

### Login (opsional — default: tanpa login)
Dashboard terbuka tanpa username/password. Kalau suatu saat mau dikunci: buat secret `APP_USERNAME` dan `APP_PASSWORD` (Settings → Secrets and variables → Actions), lalu Run workflow — data otomatis dienkripsi AES-256 dan layar login muncul.

### Opsional
Settings → Secrets and variables → Actions → **New repository secret**:

| Secret | Fungsi |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Notifikasi Telegram saat sinyal BUY/EXIT atau rezim berubah (buat bot via @BotFather, chat id via @userinfobot) |
| `ANTHROPIC_API_KEY` | Sentimen berita dinilai Claude (lebih akurat dari leksikon). Ada biaya API kecil |

## Kustomisasi — `config.yaml`
- `universe_mode: all` → **semua saham BEI**: gabungan Yahoo screener (dicek ulang tiap 7 hari, menangkap IPO baru) + daftar 941 kode BEI di `engine/idx_seed.txt` (sektor IDX-IC). Saham tanpa bar harga > 370 hari (delisting / suspensi panjang) otomatis tidak ditampilkan. Saham tidak likuid (nilai transaksi 20 hari < `filters.min_avg_value_bn`, harga < Rp50, atau histori < 60 hari) tetap tampil tapi berlabel **AVOID** dan tidak pernah dapat sinyal beli. `universe_mode: config` → hanya saham di `universe` + `universe_extra`.
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
Fokus model: **momentum + akumulasi inflow** (sejak Nov 2026).
- **Skor komposit 0–100** = 35% Flow + 35% Momentum + 15% Trend + 15% Sentimen.
  - Flow (akumulasi): peringkat di antara saham likuid dari net flow 20H & 60H (dinormalisasi likuiditas), CMF 20H & 60H, OBV 60H, nilai transaksi hari naik ÷ hari turun (50H), porsi hari dengan net inflow (60H), (+ asing).
  - Momentum: 12-1 & 6-1 bulan (Jegadeesh-Titman; Asness-Moskowitz-Pedersen), return 3 bulan, kedekatan 52-week high (George-Hwang).
  - Trend: harga vs MA20/50/200, golden cross, kemiringan MA50.
- **Syarat inti beli**: skor momentum ≥ 70 (top 30%) **dan** skor flow ≥ 60, selain uptrend (close > MA50, MA20 > MA50), CMF > 0 atau flow 5H > 0, RSI < 75.
- **Rezim pasar** (IHSG vs MA200, MA50 vs MA200, breadth, volatilitas, rupiah) membatasi eksposur: 100% / 70% / 35%.
- **Position sizing**: lot = (modal × risiko%) ÷ (entry − stop) ÷ 100, dibatasi bobot saham, sektor, dan rezim.
- **Stop berbasis close** (eksekusi besok pagi) karena stop intraday di BEI sering kena “jarum”; bisa diubah ke `intraday`.

## Pengaman drawdown (aturan baku sejak Nov 2026)
Dipilih lewat `engine/diagnose.py` (36 varian diuji di data 10 tahun, dibelah dua periode; hanya aturan yang menolong di **kedua** paruh yang dipakai):

| Aturan | Di mana | Kenapa |
|---|---|---|
| Ukuran posisi berbasis risiko 1% modal ÷ jarak stop, maks 20%/saham | `backtest.sizing`, tab PORT | Posisi bobot-sama di saham liar bisa makan 4–5% modal per trade |
| Beli baru hanya saat IHSG > MA200 ("gerbang beli") | `signal.market_filter` | Sebagian besar rugi terjadi saat pasar turun; filter rezim lama terlambat |
| Tolak saham ATR > 7%/hari | `signal.max_atr_pct` | Jarak stop terlalu lebar, sering gap melewati stop |
| Rem drawdown: turun > 15% dari puncak → slot separuh | `backtest.dd_brake`, tab PORT | Mencegah rugi beruntun membesar |
| Eksekusi realistis (tidak beli di ARA, jual ditunda saat ARB) | `backtest.realistic_fills` | Backtest lama menganggap order selalu terisi |

Yang diuji tapi **tidak** dipakai karena tidak menolong/merusak: stop intraday, merapatkan trailing stop, ambil untung sebagian, pangkas bobot, 12 posisi, batas sektor, likuiditas lebih ketat. Jalankan ulang ujinya: tab Actions → **Diagnosa Backtest** → Run workflow.

## Riset strategi frekuensi rendah (Nov 2026)
`engine/research.py` (tab Actions → **Riset Strategi**) menguji momentum bulanan, saham tenang (low-vol), gabungan, dan alokasi saham + emas di data 10 tahun yang sama. Ringkasnya: tidak ada strategi saham-saja berfrekuensi rendah yang rasionya mengalahkan strategi harian secara konsisten; perbaikan rasio terbesar datang dari menambah emas (50% strategi + 50% emas: Sharpe 0,86 vs 0,66; drawdown −20% vs −25%).

## Fokus momentum + akumulasi inflow (Nov 2026)
`engine/flowmom.py` (tab Actions → **Riset Momentum + Inflow**) menguji ±600 varian skor, bobot, syarat beli, dan aturan keluar dengan mesin backtest yang sama, 10 tahun, modal Rp10 juta. Pilihan dibuat dari paruh pertama (latih) dan dicek di paruh kedua (uji).

| | Model lama | **Model sekarang** |
|---|---|---|
| CAGR | 15,9% | **22,3%** |
| Max drawdown | −24,7% | **−22,4%** |
| Sharpe | 0,66 | **1,00** |
| Paruh latih / uji (CAGR) | 18% / 14% | 21% / 23% |

Temuan:
- **Momentum adalah mesinnya.** Mensyaratkan skor momentum ≥ 70 menaikkan CAGR ke kisaran 21–27% di hampir semua kombinasi; ambang 70–80 sama-sama bagus (dataran, bukan puncak kebetulan).
- **Inflow berperan sebagai konfirmasi, bukan mesin.** Memeringkat saham dari flow saja gagal (CAGR 4,6%). Sebagai syarat tambahan, skor akumulasi ≥ 60 menjaga drawdown di sekitar −22% dan tahun terburuk −7%.
- Skor flow lama (5–20 hari) dengan syarat yang sama memberi CAGR lebih tinggi (27,9%) tapi drawdown −24,2% dan tahun terburuk −17%; ganti `signal.flow_score: cepat` kalau mau versi itu.
- Yang diuji tapi tidak menolong: syarat status akumulasi, syarat dekat high 52 minggu, keluar saat distribusi, momentum disesuaikan risiko.
- Varian tetangga (ubah satu hal) tetap di kisaran CAGR 19–28% dengan drawdown −21% s/d −28%, jadi angka di atas bukan hasil satu setelan yang kebetulan.

Strategi Minervini dan optimasi multi-strategi (termasuk emas) yang sempat diuji sudah dihapus dari repo; model ini hanya saham Indonesia.

## Keterbatasan (penting)
- **Flow = estimasi dari OHLCV**, bukan broker summary/bandarmologi asli (data itu berbayar: Stockbit, RTI, IPOT). Foreign flow BEI dicoba otomatis, tapi situs BEI sering memblokir akses bot.
- Dengan ±920 saham (yang punya data harga di Yahoo; beberapa saham suspensi lama tidak tercakup, dan ±140 saham kecil tampil dengan kode saja tanpa nama): harga semua saham diunduh penuh sekali sehari (run pertama & 16:20 WIB); update 30-menitan hanya menyegarkan saham aktif (nilai transaksi ≥ Rp1 M/hari). Sektor saham di luar daftar kurasi memakai klasifikasi Yahoo (dipetakan ke IDX-IC, tidak selalu persis). Saham di Papan Pemantauan Khusus (FCA) tidak dibedakan — cek sendiri sebelum order.
- Yahoo Finance delay ±10–15 menit, kadang ada bar yang bolong; bukan feed real-time.
- Backtest belum memasukkan sentimen, dividen, ARB/antrean, dan memakai universe saat ini (**survivorship bias** → cenderung optimistis).
- GitHub cron bisa telat 5–20 menit saat ramai. Repo publik = sinyal bisa dilihat orang lain yang tahu URL-nya.

## Struktur
```
engine/   idx_rules · universe · data · indicators · features · regime · sentiment · signals · backtest · notify · run
          diagnose · research · flowmom   (riset, tidak mengubah dashboard)
site/     index.html · app.js · style.css · sw.js · manifest · vendor/ · data/latest.json
tools/    build_preview.py
.github/workflows/update.yml
```
Chart: TradingView Lightweight Charts™ (Apache-2.0).
