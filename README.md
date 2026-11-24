# IDX Quant Terminal

Terminal kuantitatif saham BEI bergaya Bloomberg: **money flow, sinyal IN/EXIT, position sizing sesuai modal, rezim pasar, dan sentimen berita** — update otomatis tiap ±30 menit saat jam bursa, bisa dibuka online di laptop dan dipasang sebagai **app di HP** (PWA). Gratis: jalan di GitHub Actions + GitHub Pages, tanpa server.

**Live:** https://rifqitheintrovert.github.io/idx-quant-terminal/ · **Repo:** https://github.com/rifqitheintrovert/idx-quant-terminal

**Crypto Flow Terminal:** https://rifqitheintrovert.github.io/idx-quant-terminal/crypto/ — halaman terpisah (`site/crypto/index.html`): arus modal (stablecoin, chain, exchange, net taker per koin), memecoin (Binance + radar pool trending DEX), on-chain BTC/ETH, sinyal & backtest. Data live diambil langsung di browser dari API publik tanpa API key.

Mesin harian `engine/crypto_daily.py` (workflow **Mesin Harian Crypto**, tiap 07:05 WIB) mencatat sinyal ke `site/crypto/data/track.json` sebagai track record maju yang tidak pernah ditulis ulang, plus taker harian OKX/Bitget (`deriv.json`), potret arus exchange DefiLlama (`snap.json`), dan daftar token saham Binance (`meta.json`). Riset strategi crypto: `tools/crypto_research.py` (workflow **Riset Strategi Crypto**, jalankan manual).

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
| Dashboard ala Bloomberg | Command line `BBCA <GO>`, function key F1–F10, ticker tape, chart candle + level trade |
| Fungsi per saham | `BBCA DES` profil · `BBCA FA` fundamental, laba rugi tahunan, valuasi relatif vs sektor · `BBCA DCF` perkiraan harga wajar (DCF arus kas bebas, EV/EBITDA sektor, PER sektor, PBV sektor, PBV wajar dari ROE; asumsi WACC/pertumbuhan bisa diubah, ada tabel sensitivitas) · `BBCA CN` berita · `BBCA GP` chart (gaya `BBCA <Equity> DES <GO>` juga diterima) |
| Heatmap pasar | **F8 MAP** — treemap per sektor; ukuran = nilai transaksi atau kapitalisasi; warna = perubahan hari ini / 1 minggu / 1 bulan / 3 bulan / flow 5H / skor model |
| Watchlist & alert | **F9 WATCH** — bintangi saham (`W ADD BBCA`), alert harga / skor / perubahan sinyal. Disimpan di browser; dicek saat halaman terbuka |
| Screener bebas | **F10 EQS** — susun aturan sendiri dari ±34 kolom (skor model, harga, flow, fundamental, selisih ke harga wajar), 7 preset bawaan, simpan preset sendiri, unduh CSV |
| Layar multi-panel | **LP** — 2 sampai 4 panel yang bisa diatur (chart, rencana trade, harga wajar, berita, daftar sinyal, top flow, top movers, watchlist, hasil screener, ringkasan pasar); klik saham di satu panel mengganti saham di semua panel |
| Laporan keuangan & proyeksi | `BBCA FS` — laba rugi, neraca, arus kas (tahunan 4–5 thn & kuartalan), ringkasan otomatis, tren rasio · `BBCA EE` — proyeksi pendapatan, laba, EPS 3 tahun (skenario pesimis/dasar/optimis, asumsi bisa diubah) + konsensus analis |
| Pasar global | **WEI** — indeks dunia, komoditas (emas, minyak, batu bara, dll.), kurs rupiah, yield AS, kripto; perubahan 1H–1T, YTD, korelasi dengan IHSG |
| Bandingkan saham | **COMP BBCA BBRI TLKM** — return relatif vs IHSG, volatilitas, beta, korelasi, matriks korelasi |
| Jurnal trading | **JRNL** — catat posisi riil, untung/rugi berjalan (setelah fee), jarak ke stop, peringatan stop/EXIT, statistik trade selesai, cadangan .json untuk pindah perangkat |
| Track record live | **TRK** — sinyal harian dicatat otomatis ke `track/idx.json` (tidak pernah ditulis ulang), portofolio kertas Rp10 jt mengikuti aturan backtest, return 5 & 20 hari sinyal BUY dan saham yang DITAHAN gerbang pasar |
| Kalender event | **EVTS** — ex-dividen mendatang, perkiraan rilis laporan keuangan, dividen 90 hari terakhir, stock split, status laporan kuartalan, batas waktu POJK 14/2022 · `BBCA DVD` riwayat dividen per saham |
| Sentimen & peluang | Layar **F5 SENT**: Indeks Sentimen BEI 0–100 (momentum IHSG, lebar pasar, puncak vs dasar 52 minggu, volatilitas, akumulasi CMF, rupiah; persentil 1 thn) + riwayat 2 thn vs IHSG, peluang IHSG naik 5/20/60 hari per zona sentimen & gerbang pasar (cek konsistensi dua paruh), rezim IHSG (HMM), sentimen berita, peluang per sinyal, news feed; **angka historis terbaik**: peluang per rentang 10 poin indeks (★ rentang terbaik yang konsisten di dua paruh), heatmap level komponen, sinyal BELI per zona sentimen |
| Riwayat update | Tab **UPD** di ujung menu (`UPD` / `CHANGELOG`): semua versi, tanggal & perubahan, filter fitur / model / riset / perbaikan — isi dari `site/changelog.json` (tambahkan entri baru di atas setiap rilis) |
| Quantitative modeling | Tab **QM** (`BBCA QM`), 8 sub-tab: ringkasan · Monte Carlo GJR-GARCH (filtered historical simulation, ARA/ARB) · volatilitas (realisasi, Parkinson, Garman-Klass, EWMA, struktur waktu) · model faktor BEI (MKT, SMB, WML, LIQ) + CAPM, beta sisi turun, beta bergulir · rezim Hidden Markov Model · variance ratio Lo-MacKinlay, Hurst, waktu paruh OU · VaR 99% (normal, Cornish-Fisher, historis, EVT-GPD), lompatan (bipower), hari ARA · likuiditas (Amihud, Corwin-Schultz, Roll) & biaya eksekusi posisi (hukum akar kuadrat) · Kelly criterion (rencana trade 3 hasil, Kelly model + bootstrap, log-optimal, Kelly portofolio, kurva pertumbuhan) |
| Peluang historis | Tab GP & bawah SIGNAL: % kejadian sinyal serupa yang naik 5/20/60 hari dan kena TP1/TP2 sebelum stop, dibanding rata-rata semua saham |
| Inflow lanjutan | `BBCA INF` — modal rata-rata pemegang & distribusinya (% pemegang untung, zona tumpukan modal), return siang vs semalam (Lou-Polk-Skouras), rotasi free float sejak low 120 hari, hari serapan Wyckoff (effort vs result); kolom **vs Modal** & **Serapan** di FLOW dan screener |
| Valuasi lanjutan | Di tab DCF: **residual income** (EBO, cocok untuk bank), **reverse DCF** (pertumbuhan yang sudah dihargai pasar), **EPV** (nilai tanpa pertumbuhan, Greenwald). Di tab FS: **Beneish M-score** (saringan manipulasi laporan) — juga dihitung di engine (titik-waktu): ⚠ di tabel sinyal, lencana di header saham, kolom & preset screener |
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

## Riset gerbang pasar & Parabolic SAR (Nov 2026)
`engine/gateres.py` (tab Actions → **Riset Gerbang Pasar + SAR**) menguji solusi kelemahan MA dan SAR dengan model yang sama, 10 tahun, modal Rp10 jt. Model sekarang (IHSG > MA200 + chandelier): CAGR 24,4%, drawdown −22,0%, Sharpe 1,10.
- **Tidak ada dari 50 kombinasi yang lebih baik di kedua paruh data**, jadi aturan sekarang dipertahankan.
- MA lebih pendek (MA150, MA100, EMA200), konfirmasi 3 hari, gerbang bertahap, dan pemicu breadth semuanya lebih buruk. Tanpa gerbang: drawdown −28,7%.
- Penyangga ±2% di sekitar MA200 terlihat terbaik di 10 tahun penuh (26,3% / −20,6%), tapi hanya karena paruh pertama; di paruh kedua lebih buruk dari model sekarang, jadi tidak dipakai.
- Parabolic SAR sebagai trailing stop menurunkan CAGR ke 15–20% di semua versi: SAR makin merapat dan mengeluarkan saham pemenang terlalu cepat.

## Riset inflow lanjutan (Nov 2026)
`engine/flowxres.py` (tab Actions → **Riset Inflow Lanjutan**) menguji 17 cara memakai modal pemegang, siang vs semalam, rotasi free float, dan serapan Wyckoff sebagai syarat beli atau bagian skor flow (10 tahun, modal Rp10 jt; model sekarang 23,3% / −22,4%).
- Syarat "tanpa serapan jual bersih 20 hari" terlihat terbaik (28,7% / −21,8%), tapi **uji kepekaan gagal**: dari 27 variasi ambang (volume, rentang, jendela) hanya 4 yang lebih baik di kedua paruh, median semua variasi sama dengan model sekarang. Kemungkinan kebetulan → **tidak dipakai**.
- "Harga di atas modal rata-rata pemegang" sedikit menurunkan drawdown (−20,8%) tapi juga CAGR (22,9%) → tidak dipakai.
- Siang vs semalam dan rotasi float sebagai syarat memperburuk hasil.
- Keempatnya tetap tampil di tab INF sebagai informasi.

## Riset Beneish M-score (Nov 2026)
`python -m engine.benres` (workflow **Riset Beneish M-score**). Skor titik-waktu: skor tahun buku T baru dipakai 95 hari setelah tutup buku. Laporan Yahoo hanya ±4 tahun, jadi jendela uji cuma **Apr 2024 – Nov 2026 (2,6 tahun)**, cakupan ±85% saham likuid non-keuangan.

| Uji (jendela 2,6 thn) | CAGR | MaxDD | Sharpe |
|---|---|---|---|
| Model sekarang | 34,9% | −20,8% | 1,42 |
| Blokir M > −1,78 (berisiko) | 31,4% | −27,6% | 1,20 |
| Blokir M > −2,22 (abu-abu+berisiko) | 23,1% | −27,0% | 0,91 |

- Sinyal BELI pada saham "berisiko" justru rata-rata **+18,5% dalam 60 hari** vs +4,2% untuk yang "aman" — M-score naik kalau penjualan & piutang tumbuh cepat, dan itu sering bersamaan dengan momentum.
- Keputusan: **tidak dijadikan syarat beli**. Tetap tampil sebagai peringatan (⚠) supaya dicek manual di tab FS. Bisa dinyalakan lewat `signal.beneish_max` di config.
- Catatan data: Yahoo sering tidak memberi baris arus kas operasi untuk saham BEI → dihitung dari arus kas bebas − capex.

## Probabilitas arah harga (Nov 2026)
`python -m engine.prob` (workflow **Riset Probabilitas Arah**). Dua pendekatan diuji walk-forward pada semua saham likuid BEI 2014–2026:

1. **Model per saham** (regresi logistik: momentum, inflow, tren, RSI, ATR, jarak MA50, return 5/20 hari, volume): daya prediksi out-of-sample hampir nol — AUC 0,51–0,53, Brier skill ≤ 0, dan setelah dikalibrasi ke tahun berikutnya tidak lebih baik dari rata-rata. **Tidak dipasang**: angka per saham hanya akan terlihat presisi padahal tidak.
2. **Frekuensi historis per kondisi sinyal** — dipasang di tab GP dan di bawah SIGNAL:

| Kondisi (sejak 2014) | Kejadian | Naik 20H | Naik 60H | TP1 sebelum stop | TP2 sebelum stop |
|---|---|---|---|---|---|
| STRONG BUY | 6.857 | 48,1% | 48,4% | 41,9% | 25,3% |
| BUY | 5.405 | 48,9% | 49,7% | 43,3% | 26,8% |
| Tanpa sinyal | 126.258 | 43,3% | 40,8% | 38,2% | 20,8% |
| EXIT | 158.429 | 42,3% | 40,3% | 35,4% | 17,9% |
| Semua saham likuid | 296.949 | 43,0% | 40,9% | 36,9% | 19,4% |

- Sinyal beli unggul ±6–9 poin dan lebih baik dari rata-rata di 7–9 dari 11 tahun. Peluang naik tetap < 50%: di BEI kebanyakan saham turun pelan; keuntungan model datang dari ukuran menang > ukuran kalah (trailing stop), bukan dari sering benar.
- STRONG BUY tidak lebih baik dari BUY pada ukuran ini.
- Dihitung dari harga penutupan hari sinyal (eksekusi nyata di hari berikutnya); target & stop = rencana trade (stop 2×ATR, TP1 1,5R, TP2 3R, 60 hari bursa); target & stop di hari yang sama dihitung kena stop.

## Quantitative modeling (tab QM)
Semua model **deskriptif** (menggambarkan risiko & perilaku saham), belum diuji sebagai aturan beli — model sinyal tidak berubah.
- **Ringkasan & skor QM**: 13 model dinilai Positif / Netral / Negatif (`qmodels.verdicts`, sama persis dengan tampilan tab QM). Skor QM = jumlah positif − jumlah negatif; kolom **QM** di SIGNAL (tombol "Urut QM" bagus → jelek), field screener & preset "Kandidat + QM positif". Skor di tabel memakai modal default config; ringkasan di tab QM memakai pengaturan PORT kamu (baris likuiditas & Kelly bisa beda bila modal diubah).
- `engine/volmc.py` — **GJR-GARCH(1,1)**: Gauss-QMLE + variance targeting, grid lalu dipersempit, serentak untuk semua saham, ±1.500 hari. γ = efek leverage (hari turun menaikkan volatilitas lebih tinggi). Monte Carlo di browser: σ GARCH × guncangan acak dari residual saham itu sendiri; return melewati ARA/ARB dipotong dan sisanya dibawa ke hari berikutnya; drift default nol; stop & target dicek di harga penutupan.
- `engine/qmodels.py`:
  - **Faktor BEI** dari universe sendiri, rebalance bulanan, 30% teratas vs terbawah, bobot sama: MKT (IHSG), SMB (kapitalisasi = harga × lembar sekarang), WML (momentum 12-1), LIQ (Amihud 60 hari). Regresi 250 hari → beta, t, R², alfa, volatilitas spesifik; CAPM 1/3 thn, beta saat IHSG turun/naik, beta bergulir 60 hari.
  - **Hidden Markov Model** Gauss 2 keadaan, Baum-Welch serentak untuk semua saham, 3 tahun. Diuji di data sintetis: volatilitas tiap rezim & porsi waktu tertangkap, akurasi keadaan 98%. Bila dua rezim beda < 1,3× volatilitas, dashboard menandai rezim tidak terpisah.
  - **Perilaku harga**: variance ratio Lo-MacKinlay 2/5/10/20 hari (z* tahan heteroskedastisitas), Hurst dari VR, autokorelasi, waktu paruh kembali ke MA50 (AR(1)/OU).
  - **Ekor & lompatan**: VaR/ES 99% normal, Cornish-Fisher, historis, EVT (Generalized Pareto, peaks-over-threshold persentil 95, PWM — diuji: data normal ξ≈−0,09, Student-t4 ξ≈+0,16); drawdown; porsi varians dari lompatan (bipower variation); hari kena ARA, naik ≥10%, turun ≥6,5% (1 thn).
  - **Kelly criterion** (sub-tab "Kelly & ukuran posisi"): (1) rencana trade saham — 3 hasil (kena target / kena stop / tidak dua-duanya dalam 60 hari), f = (p_menang·b − p_kalah)/(b·(p_menang+p_kalah)), b sudah dikurangi fee; peluang dari frekuensi historis sinyal sejenis dan dari Monte Carlo drift nol; ukuran ½ Kelly dalam lot vs ukuran model (risiko 1%). (2) Kelly model dari trade backtest: rumus biner W − (1−W)/payoff dengan interval bootstrap 90% & peluang edge ≤ 0, posisi log-optimal dari sebaran trade asli (maks rata-rata ln(1+f·r)), dibagi jumlah posisi bersamaan. (3) Kelly portofolio = (μ − rf)/σ² dari return harian equity model. (4) Kurva pertumbuhan: ½ Kelly, Kelly, 2× Kelly.
  - **Likuiditas**: Amihud ILLIQ + persentil, spread Corwin-Schultz & Roll, hari tanpa transaksi; di dashboard: porsi volume harian posisi kamu (dari PORT), hari masuk/keluar di 10–20% volume, dampak harga hukum akar kuadrat (σ·√(Q/ADV)), biaya bolak-balik termasuk fee.

## Sentimen v2 — pasar & per saham (Nov 2026)
`python -m engine.sentres` (workflow **Riset Sentimen**); live: `engine/sentlive.py` (metrik uji dihitung ulang sekali per hari bursa, disimpan di `.cache/sent_metrics.json`).
- **Proxy pasar**: lonjakan ekstrem (naik ≥10% − turun ≥6,9%), nilai transaksi vs normal, big caps vs saham kecil, porsi transaksi saham < Rp200, naik vs turun, puncak vs dasar 52 minggu, saham di atas MA50, momentum IHSG, volatilitas, CMF, rupiah, semalam − siang, EIDO, VIX, DXY, EEM.
- **Model** (walk-forward, bobot dihitung ulang tiap bulan dari data masa lalu): PCA ala Baker–Wurgler, PLS 1 komponen (aligned sentiment, target return IHSG 20 hari yang sudah diketahui), Kalman local-level (q maksimum likelihood).
- **Uji pasar**: IC Spearman 20/60 hari + per paruh, selisih kuintil, t Newey-West, R² out-of-sample Campbell–Thompson, Granger dua arah. Hasil Nov 2026: **tidak ada indeks gabungan yang prediktif** (R² OOS < 0); Granger menunjukkan IHSG → sentimen. Proxy global (EIDO, VIX, EEM, DXY) mendahului IHSG harian (efek zona waktu). Dua proxy lolos di 60 hari dan kontrarian (big caps vs kecil, CMF) — dari 32 uji, ±2 bisa lolos kebetulan.
- **Per saham** (±109 saham likuid/hari): proxy transaksi vs normal, lonjakan ekstrem 20 hari, kuat vs sektor, kuat vs IHSG, semalam − siang, lonjakan volatilitas; skor rata-rata / PCA gabungan / PLS (bobot IC masa lalu). Uji: IC lintas saham harian 5/20/60 hari, t Fama-MacBeth (Newey-West), selisih kuintil. Hasil: skor gabungan **tidak prediktif**; lonjakan ekstrem lolos dengan arah negatif (pola gorengan tertinggal 60 hari); kuintil terdingin tertinggal ±1%/20 hari.
- **Model per saham tambahan (v0.23)**: proxy MAX, IVOL, skew, perhatian, reversal 5 hari; skor **lotre** (MAX+IVOL+skew+lonjakan) dan **ridge** walk-forward (λ=2000, bobot dihitung ulang tiap 21 hari dari 500 hari terakhir). Uji 60 hari: IVOL IC −0,11 (t −4,1), lotre −0,10, ridge +0,10 (t 4,5; Q5−Q1 +5,4%), konsisten dua paruh.
- **Histori per saham**: grafik skor ±500 hari + tabel kejadian (return lebih dari IHSG 20/60 hari setelah panas/dingin/⚡/lotre/ridge ekstrem) di sub-tab QM "Sentimen saham".
- **Backtest aturan** (`python -m engine.sentbt`, workflow **Backtest Sentimen**; opsi `--robust` = sapuan k + placebo acak): filter blok semuanya tidak lolos. Prioritas slot −IVOL/−lotre lebih baik di kedua paruh pada banyak k (Calmar 0,99 → 1,04–1,15) tetapi masih di dalam sebaran placebo (skor acak: Calmar 0,66–1,21, persentil-90 1,07) → **aturan model tidak diubah**.
- Tampil: kolom **Sent** di SIGNAL (⚡ = sering melonjak ekstrem), sub-tab QM "Sentimen saham", panel "Sentimen v2 · Model & Uji" di F5, baris "Sentimen saham" di ringkasan QM (Positif bila ridge ≥ 80 dan ridge lolos uji; Negatif bila panas/dingin ekstrem atau ridge ≤ 20).
- **Rambu good way / bad way** (v0.23.1): panel di F5 (pasar) dan QM "Sentimen saham" (per saham) yang merangkum tanda bagus/buruk yang lolos uji, status hari ini, dan bukti historisnya. Tanda yang belum lolos di data terbaru diredupkan otomatis. Dipakai untuk menentukan seberapa agresif & memilih di antara kandidat BUY, bukan sinyal sendiri.
- Data beli/jual asing dari situs IDX **tidak** dipakai karena situs tersebut memblokir akses otomatis; minat asing diwakili EIDO.

## Sentimen sektor BEI (v0.25.1, Nov 2026)
`engine/sectsent.py`, panel di **F5 SENT**. Indeks sektor = rata-rata return saham likuid sektor itu (bobot sama). Skor 0–100 = persentil 3 tahun (sektor itu sendiri) dari 8 komponen: harga vs MA125, RSI 14, jarak ke puncak 52 minggu, volatilitas 20 hari (dibalik), return 20 hari, % saham > MA50, % saham CMF 20 > 0, % di puncak − % di dasar 52 minggu. Ditambah rata-rata ridge, jumlah saham lotre & ⚡, 3 saham ridge tertinggi per sektor. Bukti: return sektor 20/60 hari ke depan dikurangi pasar per zona, cek dua paruh (Nov 2026: bentuk U — takut ekstrem +0,7% & serakah ekstrem +1,2% per 60 hari vs pasar, zona tengah negatif; kecil, petunjuk saja).

Catatan: modul global (MAKRO, HOME dunia, ECO, sentimen dunia, WEI) sempat dibuat di v0.24–v0.25 lalu dihapus di v0.25.2 — fokus kembali ke BEI.

## Backtest tiap model QM (v0.26, Nov 2026)
`python -m engine.qmbt --cache .cache/panels.pkl` (workflow **Backtest Model QM**; opsi `--ddsweep`). Hasil di `site/data/qmbt.json`, tampil di F6 BTEST → "Backtest per Model QM".
- Modal **Rp10 jt**, 2014-11 – 2026-11, model sinyal sekarang (CAGR 21,7%, DD −22,7%, Calmar 0,95; paruh 0,92 / 1,01), 12.262 sinyal beli.
- Tiap model dihitung **titik-waktu** di setiap sinyal (hanya data sampai hari itu): GJR-GARCH & HMM di-fit ulang tiap bulan lalu difilter harian; beta, sisi turun, alfa 4 faktor (1 th); variance ratio/OU; VaR99 EVT; lompatan & ARA; drawdown 3 th; likuiditas (modal Rp10 jt); peluang historis & Kelly rencana dari frekuensi sinyal yang hasilnya sudah diketahui; sentimen (aturan lolos uji); skor QM total.
- Diuji 3 cara: blokir saat Negatif, beli hanya saat Positif, prioritas slot. LOLOS = Calmar lebih baik di kedua paruh **dan** di atas persentil-90 placebo acak dengan porsi sinyal sama (verifikasi 40 seed).
- **Hasil: tidak ada model QM yang lolos.** Placebo acak sendiri menghasilkan Calmar 0,5–1,4, jadi selisih ±0,2 masih kebetulan. Drawdown (blokir DD < −30%) lolos tipis tapi sapuan ambang −20…−50% gagal 0/6.
- Tingkat sinyal (return 60 hari): label Negatif risiko (vol, VaR, sisi turun, sentimen) justru diikuti return lebih tinggi → QM = informasi risiko, bukan arah. Beta > 1,2 diikuti +0,7% vs +7,6%. Alfa & tren Positif diikuti +14% / +13% vs ±+5% tetapi tidak menaikkan hasil portofolio (tumpang tindih dengan momentum).
- Kelly model (risiko/trade): 1,25% → CAGR 29,9%, DD −25,7%; 1,5% → 32,2%, −25,6% (keduanya lebih baik di dua paruh); 1,75%+ → DD −36…−39%. Belum diubah.

## Backtest per saham (v0.27–v0.29, Nov 2026)
`python -m engine.stkbt --cache .cache/panels.pkl` (workflow **Backtest per Saham**, tiap Sabtu; hasil di-commit ke `site/data/sbt/KODE.json` + `_summary.json`, lalu memicu deploy). Modal **Rp10 jt** per saham, satu saham, posisi beli saja, eksekusi di harga pembukaan hari berikutnya, lot 100, fee beli/jual, sisa = kas, tanpa stop loss. Mesin mengirim harga harian & vonis harian 14 model QM (sejak 2017); simulasi dihitung di browser.
- **QM** (tab GP, aturan v0.27): beli saat skor QM > 0, jual saat skor < 0. **Batas minimum per model** (v0.29): tiap model QM + Valuasi DCF (Positif = harga < wajar −margin, Netral = < wajar, Negatif = ≥ wajar) bisa diberi batas "min. Netral" atau "harus Positif"; beli hanya bila semua batas terpenuhi, jual bila batas gugur. Bar riwayat vonis mingguan per model. Disimpan di browser, berlaku untuk semua saham.
- **DCF** (tab DCF, v0.28): beli saat harga < harga wajar × (1 − margin), jual tepat di harga wajar. Harga wajar per tahun buku (DCF; bank/FCF negatif → PBV wajar dari ROE), dipakai 95 hari setelah tutup buku, asumsi tab DCF + margin of safety.
- Skor QM harian = jumlah vonis 14 model ringkasan QM, titik-waktu (`stkbt.qm_panel`: GARCH & HMM tiap kuartal, perilaku harga & VaR tiap bulan, alfa tiap minggu, sisanya harian).
- Hasil (asumsi bawaan, tanpa batas): QM median CAGR −3,3% vs tahan terus +4,7% (108 saham, ±2017–2026); DCF median 0% (banyak saham tidak pernah di bawah harga wajar, ±2022–2026).

## Uji sinyal QM sebagai pengganti SIGNAL (v0.29, Nov 2026)
`python -m engine.qmsig --cache .cache/panels.pkl` (workflow **Uji Sinyal QM**; hasil `site/data/qmsig.json`, panel F6 BTEST). Portofolio Rp10 jt, 2014–2026, 325 saham yang pernah likuid (tanpa bias saham bertahan). Sinyal QM: masuk saat skor QM ≥ ambang (> 0, ≥ 2, ≥ 3, ≥ 4; dengan/tanpa gerbang MA200; dengan/tanpa "tidak ada model Negatif"), keluar saat skor < 0; sizing, slot & stop trailing sama.

| Sinyal | CAGR | Max DD | Calmar |
|---|---|---|---|
| Sekarang (momentum + akumulasi) | **+22,2%** | −22,5% | 0,99 |
| QM > 0 | −3,8% | −54,3% | −0,07 |
| QM > 0 + gerbang MA200 | −1,4% | −46,8% | −0,03 |
| QM ≥ 4 + gerbang | −3,3% | −51,4% | −0,06 |
| QM > 0 + gerbang + tanpa model Negatif | −1,3% | −15,0% | −0,09 |

Keputusan: **SIGNAL tetap** memakai model momentum + akumulasi. QM tetap sebagai informasi risiko.

## Keterbatasan (penting)
- **Fundamental (DES/FA)** diambil dari Yahoo Finance seminggu sekali untuk saham dengan nilai transaksi ≥ Rp1 M/hari; sebagian saham tidak punya datanya, dan angkanya tidak dipakai untuk sinyal. Emiten yang melapor dalam USD ditampilkan dalam mata uang laporannya.
- **Harga wajar (tab DCF)** adalah hitungan otomatis dengan asumsi seragam (WACC 11%, terminal 4%, biaya ekuitas 13%), bukan riset emiten: sangat peka terhadap asumsi, DCF tidak dihitung untuk bank/keuangan dan emiten dengan arus kas bebas negatif, dan tidak dipakai untuk sinyal.
- **Proyeksi (tab EE)** adalah ekstrapolasi sederhana: pertumbuhan pendapatan historis memudar ke 6% dalam 3 tahun, margin = rata-rata 3 tahun terakhir. Bukan perkiraan analis; tidak menangkap siklus komoditas atau aksi korporasi. Laporan keuangan diambil dari Yahoo bertahap (± seminggu sekali per saham).
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
