/* IDX QUANT TERMINAL — frontend (vanilla JS + lightweight-charts) */
(() => {
"use strict";
const LWC = window.LightweightCharts;
const S = {
  d: null, view: "mkt", ticker: null, charts: [], dcharts: [],
  sort: { flow: ["nf5", -1], signal: ["rank", 1], watch: ["ticker", 1] },
  fsig: "ALL", fsec: "ALL", fnews: "", ai: null, liq: true, q: "", cap: 200,
  dtab: "gp", fund: null, mapColor: "chg", mapSize: "val",
};
const VIEWS = [
  ["mkt", "F1", "MKT", "Pasar"], ["flow", "F2", "FLOW", "Money Flow"], ["signal", "F3", "SIGNAL", "Sinyal"],
  ["porto", "F4", "PORT", "Portofolio"], ["news", "F5", "NEWS", "Sentimen"], ["btest", "F6", "BTEST", "Backtest"],
  ["help", "F7", "HELP", "Metode"], ["map", "F8", "MAP", "Heatmap"], ["watch", "F9", "WATCH", "Watchlist & Alert"],
  ["scr", "F10", "EQS", "Screener"], ["pad", "LP", "PANEL", "Layar multi-panel"],
  ["glob", "WEI", "GLOBAL", "Pasar global"], ["comp", "COMP", "BANDING", "Bandingkan saham"], ["jrnl", "JRNL", "JURNAL", "Jurnal trading"],
];
const DTABS = [["gp", "GP", "Chart & rencana trade"], ["des", "DES", "Profil"], ["fa", "FA", "Fundamental"], ["fs", "FS", "Laporan keuangan"], ["ee", "EE", "Proyeksi"], ["val", "DCF", "Harga wajar"], ["cn", "CN", "Berita"]];
const COL = { up: "#2ebd6b", down: "#f0474f", s1: "#cf7d0e", s2: "#2e8fd0", s3: "#d0559a", grid: "#141414", text: "#8c8c8c", line: "#222" };
const SIGCLS = { "STRONG BUY": "SB", BUY: "BUY", HOLD: "HOLD", REDUCE: "REDUCE", EXIT: "EXIT", AVOID: "AVOID" };
const SIGRANK = { "STRONG BUY": 0, BUY: 1, HOLD: 2, REDUCE: 3, EXIT: 4, AVOID: 5 };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const store = {
  get(k, d) { try { const v = localStorage.getItem("idxq." + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("idxq." + k, JSON.stringify(v)); } catch { /* storage tidak tersedia */ } },
};

/* ---------------- format ---------------- */
const NF = (d) => new Intl.NumberFormat("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d });
const nf0 = NF(0), nf1 = NF(1), nf2 = NF(2);
const useTiming = () => !S.d || !S.d.config || (S.d.config.weights.timing || 0) > 0;
const num = (x, d = 0) => (x == null || isNaN(x) ? "–" : (d === 0 ? nf0 : d === 1 ? nf1 : NF(d)).format(x));
const pct = (x, d = 1) => (x == null || isNaN(x) ? "–" : (x > 0 ? "+" : "") + NF(d).format(x * 100) + "%");
const cls = (x) => (x == null || isNaN(x) || Math.abs(x) < 1e-9 ? "neu" : x > 0 ? "up" : "down");
const rp = (bn, sign = true) => {
  if (bn == null || isNaN(bn)) return "–";
  const s = sign && bn > 0 ? "+" : bn < 0 ? "-" : "";
  const a = Math.abs(bn);
  return s + (a >= 1000 ? nf2.format(a / 1000) + " T" : a >= 10 ? nf0.format(a) + " M" : nf1.format(a) + " M");
};
const rupiah = (x) => "Rp" + nf0.format(Math.round(x || 0));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ago = (iso) => {
  const m = (Date.now() - new Date(iso).getTime()) / 60000;
  if (m < 60) return Math.max(1, Math.round(m)) + " mnt";
  if (m < 1440) return Math.round(m / 60) + " jam";
  return Math.round(m / 1440) + " hr";
};
const sig = (s) => `<span class="sig ${SIGCLS[s]}">${s}</span>`;
const scoreColor = (v) => (v >= 60 ? COL.up : v <= 40 ? COL.down : "#777");
const scoreBar = (v) => `<div class="scorecell"><span class="n">${num(v)}</span><div class="bar"><span style="width:${Math.max(2, v || 0)}%;background:${scoreColor(v)}"></span></div></div>`;
const divBar = (x, max) => {
  const w = Math.min(50, (Math.abs(x || 0) / (max || 1)) * 50);
  return `<div class="bar div"><span style="left:${x >= 0 ? 50 : 50 - w}%;width:${w}%;background:${x >= 0 ? COL.up : COL.down}"></span></div>`;
};
const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2200); };
const stock = (t) => S.d.stocks.find((s) => s.ticker === t);

/* ---------------- data ---------------- */
async function load(first) {
  let d = window.__DATA__;
  if (!d) {
    try {
      const r = await fetch("data/latest.json?ts=" + Date.now(), { cache: "no-store" });
      d = await r.json();
    } catch (e) {
      if (first) $("#view").innerHTML = `<div class="callout red">Gagal memuat data: ${esc(e.message)}. Jalankan <code>python -m engine.run</code> terlebih dahulu.</div>`;
      return;
    }
    if (d && d.enc) {
      S.locked = true;
      const env = d;
      d = await tryStoredKey(env);
      if (!d) { showLogin(env); return; }
    }
  }
  applyData(d, first);
}
function applyData(d, first) {
  const changed = !S.d || S.d.meta.generated_at !== d.meta.generated_at;
  S.d = d;
  if (d.fund) S.fund = normFund(d.fund);
  if (changed) {
    evalAlerts(); jrAlerts();
    renderChrome();
    route();
    if (!first) toast("Data diperbarui " + d.meta.generated_at.slice(11, 16) + " WIB");
  }
}

/* ---------------- login: data dienkripsi AES-GCM, kunci = PBKDF2(username:password) ---------------- */
const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const b64e = (u) => btoa(String.fromCharCode(...new Uint8Array(u)));
async function deriveKey(user, pass, env) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(user.trim().toLowerCase() + ":" + pass), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: b64d(env.salt), iterations: env.iter, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
}
async function decryptEnv(env, key) {
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64d(env.iv) }, key, b64d(env.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
function savedKey() {
  try { return sessionStorage.getItem("idxq.key") || localStorage.getItem("idxq.key"); } catch { return null; }
}
async function tryStoredKey(env) {
  try {
    if (!S.key) { const raw = savedKey(); if (!raw) return null; S.key = await crypto.subtle.importKey("raw", b64d(raw), "AES-GCM", true, ["decrypt"]); }
    return await decryptEnv(env, S.key);
  } catch { S.key = null; return null; }
}
function showLogin(env) {
  const el = $("#login");
  if (!el.hidden) return;
  el.hidden = false;
  const msg = $("#lg-msg"), form = $("#lg-form");
  if (!window.crypto || !crypto.subtle) { msg.textContent = "Browser ini tidak mendukung enkripsi (butuh HTTPS)."; return; }
  $("#lg-user").focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    msg.textContent = "Memeriksa…";
    try {
      const key = await deriveKey($("#lg-user").value, $("#lg-pass").value, env);
      const d = await decryptEnv(env, key);
      S.key = key;
      try {
        const raw = b64e(await crypto.subtle.exportKey("raw", key));
        ($("#lg-keep").checked ? localStorage : sessionStorage).setItem("idxq.key", raw);
      } catch { /* storage tidak tersedia */ }
      $("#lg-pass").value = ""; msg.textContent = ""; el.hidden = true;
      applyData(d, true);
    } catch { msg.textContent = "Username atau password salah."; }
  };
}
function logout() {
  try { localStorage.removeItem("idxq.key"); sessionStorage.removeItem("idxq.key"); } catch { /* abaikan */ }
  location.hash = ""; location.reload();
}

/* ---------------- chrome: header / tape / nav ---------------- */
function renderChrome() {
  const m = S.d.meta;
  $("#tickers").innerHTML = S.d.stocks.map((s) => `<option value="${s.ticker}">${esc(s.name)}</option>`).join("");
  const banner = [];
  if (m.mode === "demo") banner.push(`<div class="demo-bar"><b>MODE DEMO — DATA SIMULASI, BUKAN HARGA PASAR.</b> Semua angka, sinyal & berita di pratinjau ini dibangkitkan acak untuk menguji tampilan. Deploy ke GitHub (lihat README) untuk data live otomatis.</div>`);
  (m.warnings || []).forEach((w) => banner.push(`<div class="warn-bar">⚠ ${esc(w)}</div>`));
  $("#banner").innerHTML = banner.join("");
  const items = S.d.stocks.filter((s) => s.signal !== "AVOID").sort((a, b) => (b.flow.value || 0) - (a.flow.value || 0)).slice(0, 40)
    .map((s) => `<span data-t="${s.ticker}"><b>${s.ticker}</b>${num(s.last)} <i class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</i></span>`).join("");
  const ih = S.d.market.ihsg;
  $("#tape").innerHTML = `<span><b>IHSG</b>${num(ih.last, 2)} <i class="${cls(ih.chg_pct)}">${pct(ih.chg_pct, 2)}</i></span>` + items + items;
  $("#nav").innerHTML = VIEWS.map(([id, k, code, lab]) =>
    `<button data-view="${id}" class="${S.view === id ? "on" : ""}" title="${lab} (${k})"><span class="k">${k}</span>${code}${id === "watch" && unseen() ? `<span class="badge">${unseen()}</span>` : ""}</button>`).join("");
  tick();
}

function tick() {
  if (!S.d) return;
  const m = S.d.meta;
  const now = new Date();
  const wib = new Date(now.getTime() + (now.getTimezoneOffset() + 420) * 60000);
  const hh = wib.toTimeString().slice(0, 8);
  const ageMin = (now - new Date(m.generated_at)) / 60000;
  const open = m.market_status === "OPEN";
  let fresh = m.mode === "demo" ? `<span class="pill demo">DEMO</span>`
    : m.stale || (ageMin > 75 && liveSession(wib)) ? `<span class="pill stale">STALE ${Math.round(ageMin)}m</span>`
    : `<span class="pill live"><span class="dot"></span>LIVE</span>`;
  $("#status").innerHTML = `${fresh}<span class="pill ${open ? "open" : "closed"}">BEI ${esc(sessionLabel(wib))}</span>
    <span class="mut hide-m">Data ${esc(m.data_asof)} · upd ${esc(m.generated_at.slice(11, 16))}</span><span class="amb b">${hh} WIB</span>${S.locked ? `<button class="pill" data-logout style="cursor:pointer;background:none">KELUAR</button>` : ""}`;
}
function liveSession(w) {
  const d = w.getDay(), t = w.getHours() * 60 + w.getMinutes();
  return d >= 1 && d <= 5 && t >= 540 && t <= 970;
}
function sessionLabel(w) {
  const d = w.getDay(), t = w.getHours() * 60 + w.getMinutes(), fri = d === 5;
  if (d === 0 || d === 6) return "TUTUP";
  if (t >= 525 && t < 540) return "PRE-OPEN";
  if (t >= 540 && t < (fri ? 690 : 720)) return "SESI 1";
  if (t < (fri ? 840 : 810) && t >= (fri ? 690 : 720)) return "ISTIRAHAT";
  if (t >= (fri ? 840 : 810) && t < 950) return "SESI 2";
  if (t >= 950 && t < 975) return "PRE-CLOSE";
  return "TUTUP";
}

/* ---------------- routing ---------------- */
function route() {
  const h = location.hash.replace("#", "");
  if (h.startsWith("t-")) {
    const [t, tab] = h.slice(2).toUpperCase().split(".");
    if (stock(t)) { if (S.view === "mkt" && !$("#view").innerHTML) renderView(); openDetail(t, false, DTABS.some((x) => x[0] === (tab || "").toLowerCase()) ? tab.toLowerCase() : "gp"); return; }
  }
  closeDetail(false);
  S.view = VIEWS.some((v) => v[0] === h) ? h : S.view || "mkt";
  renderView();
}
function go(view) { location.hash = view; }
function renderView(keep) {
  const y = window.scrollY;
  disposeCharts(S.charts);
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === S.view));
  const v = { mkt: vMkt, flow: vFlow, signal: vSignal, porto: vPorto, news: vNews, btest: vBtest, help: vHelp, map: vMap, watch: vWatch, scr: vScr, pad: vPad, glob: vGlob, comp: vComp, jrnl: vJrnl }[S.view];
  $("#view").innerHTML = "";
  v($("#view"));
  window.scrollTo(0, keep ? y : 0);
  if (S.refocus) { S.refocus = false; const q = $("#q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }
}
/* saham yang ditampilkan di tabel: default hanya yang likuid; pencarian menjangkau semua saham */
function pool(all) {
  const q = S.q.trim().toUpperCase();
  if (q) return S.d.stocks.filter((s) => s.ticker.includes(q) || s.name.toUpperCase().includes(q));
  return S.liq && !all ? S.d.stocks.filter((s) => s.signal !== "AVOID") : S.d.stocks;
}
function scopeBar() {
  const liq = S.d.stocks.filter((s) => s.signal !== "AVOID").length;
  return `<button data-liq="1" class="${S.liq ? "on" : ""}">Likuid saja ${liq}</button><button data-liq="0" class="${!S.liq ? "on" : ""}">Semua saham ${S.d.stocks.length}</button>
    <input id="q" placeholder="Cari kode / nama" value="${esc(S.q)}" autocomplete="off" spellcheck="false">`;
}
const moreBar = (n) => (n > S.cap ? `<div class="filters" style="margin-top:8px"><button data-more>Tampilkan ${Math.min(300, n - S.cap)} lagi · ${n - S.cap} tersisa</button></div>` : "");
function disposeCharts(arr) { while (arr.length) { try { arr.pop().remove(); } catch { /* sudah dihapus */ } } }

/* ---------------- chart helpers ---------------- */
function mkChart(el, arr, opts = {}) {
  const c = LWC.createChart(el, Object.assign({
    autoSize: true,
    layout: { background: { type: "solid", color: "#070707" }, textColor: COL.text, fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: COL.grid }, horzLines: { color: COL.grid } },
    rightPriceScale: { borderColor: COL.line },
    timeScale: { borderColor: COL.line, rightOffset: 3 },
    crosshair: { mode: 0 },
    localization: { priceFormatter: (p) => num(p, Math.abs(p) < 100 ? 2 : 0) },
  }, opts));
  c.applyOptions({ layout: { attributionLogo: false } });
  arr.push(c);
  return c;
}
const ser = (dates, vals) => dates.map((t, i) => (vals[i] == null ? { time: t } : { time: t, value: vals[i] }));

/* ================= F1 MKT ================= */
function vMkt(root) {
  const d = S.d, m = d.market, ih = m.ihsg, rg = m.regime;
  const by = Object.fromEntries(d.stocks.map((s) => [s.ticker, s]));
  const maxSec = Math.max(...m.sectors.map((s) => Math.abs(s.nf5 || 0)), 1);
  const sc = m.signal_count;
  root.innerHTML = `
  <div class="grid g3">
    <div class="stack">
      <div class="panel"><h3>IHSG · Komposit <span class="fn">^JKSE</span></h3><div class="pb">
        <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
          <span class="big">${num(ih.last, 2)}</span>
          <span class="mid ${cls(ih.chg)}">${ih.chg > 0 ? "+" : ""}${num(ih.chg, 2)} (${pct(ih.chg_pct, 2)})</span>
          <span class="mut">1B ${pct(ih.ret21)}</span></div>
        <div class="chart" id="c-ihsg"><div class="legend" id="lg-ihsg"></div></div>
        <div class="note">Strip bawah: skor rezim harian (hijau = risk-on, merah = risk-off).</div>
      </div></div>
      <div class="panel"><h3>Rezim Pasar <span class="fn">eksposur maks ${Math.round(rg.exposure * 100)}%</span></h3><div class="pb">
        <div class="regime"><span class="lab ${rg.label}">${rg.label}</span><span class="mut">skor ${rg.score > 0 ? "+" : ""}${rg.score} dari 6 faktor</span></div>
        ${rg.components.map((c) => `<div class="comp-row"><span class="${c.s > 0 ? "up" : c.s < 0 ? "down" : "neu"}">${c.s > 0 ? "▲" : c.s < 0 ? "▼" : "•"}</span><span class="mut">${esc(c.k)}</span><span>${esc(c.v)}</span></div>`).join("")}
        <div class="tiles" style="margin-top:8px">
          <div class="tile"><div class="l">Naik / Turun</div><div class="v"><span class="up">${m.breadth.adv}</span> / <span class="down">${m.breadth.dec}</span></div></div>
          <div class="tile"><div class="l">% &gt; MA200</div><div class="v">${pct(m.breadth.above_ma200, 0).replace("+", "")}</div></div>
          <div class="tile"><div class="l">Saham dipantau</div><div class="v">${d.stocks.length}<span class="mut small"> · ${d.stocks.filter((x) => x.signal !== "AVOID").length} likuid</span></div></div>
        </div>
      </div></div>
    </div>
    <div class="stack">
      <div class="panel"><h3>Rotasi Sektor · Net Flow 5H <span class="fn">estimasi Rp</span></h3><div class="pb">
        <div class="heat">${m.sectors.map((s) => {
          const a = Math.min(1, Math.abs(s.nf5) / maxSec);
          const bg = s.nf5 >= 0 ? `rgba(30,150,80,${0.15 + a * 0.6})` : `rgba(210,50,60,${0.15 + a * 0.6})`;
          return `<div class="cell" style="background:${bg}" data-fsec="${esc(s.sector)}" title="Klik: filter tabel flow">
            <div class="s">${esc(s.sector)}</div><div class="v">${rp(s.nf5)}</div>
            <div class="m">20H ${rp(s.nf20)} · 5H ${pct(s.ret5)} · Akum ${s.acc}/${s.n}</div></div>`;
        }).join("")}</div></div></div>
      <div class="grid g2">
        <div class="panel"><h3>Top Inflow 5H</h3><div class="pb list">${m.top_inflow.map((t) => { const s = by[t]; return `<span class="tk" data-t="${t}">${t}</span><span class="up">${rp(s.flow.nf5)}</span><span class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</span>`; }).join("")}</div></div>
        <div class="panel"><h3>Top Outflow 5H</h3><div class="pb list">${m.top_outflow.map((t) => { const s = by[t]; return `<span class="tk" data-t="${t}">${t}</span><span class="down">${rp(s.flow.nf5)}</span><span class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</span>`; }).join("")}</div></div>
        <div class="panel"><h3>Top Gainers</h3><div class="pb list">${m.gainers.slice(0, 6).map((t) => { const s = by[t]; return `<span class="tk" data-t="${t}">${t}</span><span>${num(s.last)}</span><span class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</span>`; }).join("")}</div></div>
        <div class="panel"><h3>Top Losers</h3><div class="pb list">${m.losers.slice(0, 6).map((t) => { const s = by[t]; return `<span class="tk" data-t="${t}">${t}</span><span>${num(s.last)}</span><span class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</span>`; }).join("")}</div></div>
      </div>
    </div>
    <div class="stack">
      <div class="panel"><h3>Sinyal Hari Ini <span class="fn" data-view="signal" style="cursor:pointer">F3 ▸</span></h3><div class="pb">
        ${gateBox()}
        <div class="tiles" style="grid-template-columns:repeat(3,1fr);margin-bottom:8px">
          <div class="tile"><div class="l">Strong Buy</div><div class="v up">${sc["STRONG BUY"]}</div></div>
          <div class="tile"><div class="l">Buy</div><div class="v up">${sc.BUY}</div></div>
          <div class="tile"><div class="l">Exit</div><div class="v down">${sc.EXIT}</div></div></div>
        <table><tbody>${d.stocks.filter((s) => s.signal === "STRONG BUY" || s.signal === "BUY").slice(0, 7).map((s) =>
          `<tr data-t="${s.ticker}"><td class="tk">${s.ticker}</td><td>${sig(s.signal)}</td><td class="r">${num(s.last)}</td><td style="width:90px">${scoreBar(s.scores.composite)}</td></tr>`).join("") || `<tr><td class="mut">Tidak ada sinyal beli.</td></tr>`}</tbody></table>
      </div></div>
      <div class="panel"><h3>Makro & Global</h3><div class="pb macro">${m.macro.map((x) =>
        `<span class="amb">${esc(x.name)}</span><span class="r">${num(x.last, x.last < 100 ? 2 : 0)}</span>${spark(x.spark)}<span class="${cls(x.chg_pct)} r">${pct(x.chg_pct, 2)}</span>`).join("")}</div></div>
      <div class="panel"><h3>Sentimen Pasar <span class="fn">${esc(S.d.sentiment.method || "")}</span></h3><div class="pb">
        ${gauge(m.sentiment.score)}
        <div class="mut small">${m.sentiment.n} berita · <span class="up">${m.sentiment.pos} positif</span> · <span class="down">${m.sentiment.neg} negatif</span></div>
        ${d.news.slice(0, 4).map(newsItem).join("")}
      </div></div>
    </div>
  </div>`;
  // IHSG chart
  const n = ih.series.length, dates = d.dates.slice(-n);
  const el = $("#c-ihsg");
  const c = mkChart(el, S.charts);
  const a = c.addAreaSeries({ lineColor: "#e6e6e6", topColor: "rgba(230,230,230,.12)", bottomColor: "rgba(230,230,230,0)", lineWidth: 2, priceLineVisible: false });
  a.setData(ser(dates, ih.series));
  const l50 = c.addLineSeries({ color: COL.s2, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  l50.setData(ser(dates, ih.ma50));
  const l200 = c.addLineSeries({ color: COL.s3, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  l200.setData(ser(dates, ih.ma200));
  const rs = c.addHistogramSeries({ priceScaleId: "rg", priceLineVisible: false, lastValueVisible: false });
  c.priceScale("rg").applyOptions({ scaleMargins: { top: 0.93, bottom: 0 }, visible: false });
  rs.setData(dates.map((t, i) => ({ time: t, value: 1, color: ih.regime[i] >= 2 ? COL.up : ih.regime[i] >= 0 ? "#444" : COL.down })));
  c.timeScale().fitContent();
  const lg = $("#lg-ihsg");
  const setLg = (i) => { lg.innerHTML = `<span class="mut">${dates[i]}</span> IHSG <b>${num(ih.series[i], 2)}</b><i style="background:${COL.s2}"></i>MA50 ${num(ih.ma50[i])}<i class="dash" style="color:${COL.s3}"></i>MA200 ${num(ih.ma200[i])}`; };
  setLg(n - 1);
  c.subscribeCrosshairMove((p) => { const i = p && p.time ? dates.indexOf(p.time) : -1; setLg(i >= 0 ? i : n - 1); });
}
function spark(vals) {
  const v = (vals || []).filter((x) => x != null);
  if (v.length < 2) return "<span></span>";
  const mn = Math.min(...v), mx = Math.max(...v), w = 90, h = 26;
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * w},${h - 2 - ((x - mn) / (mx - mn || 1)) * (h - 4)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline fill="none" stroke="#9a9a9a" stroke-width="1.5" points="${pts}"/><circle cx="${w}" cy="${pts.split(" ").pop().split(",")[1]}" r="2" fill="${v[v.length - 1] >= v[0] ? COL.up : COL.down}"/></svg>`;
}
function gauge(score) {
  const lab = score >= 60 ? "POSITIF" : score <= 40 ? "NEGATIF" : "NETRAL";
  return `<div style="display:flex;justify-content:space-between"><span class="mid">${num(score)}<span class="mut small"> /100</span></span><span class="b ${score >= 60 ? "up" : score <= 40 ? "down" : "neu"}">${lab}</span></div>
  <div class="gauge"><b style="left:calc(${score}% - 1px)"></b></div><div class="mut small" style="display:flex;justify-content:space-between"><span>negatif</span><span>netral</span><span>positif</span></div>`;
}
function newsItem(n) {
  const col = n.score > 0.15 ? COL.up : n.score < -0.15 ? COL.down : "#777";
  const title = n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : esc(n.title);
  return `<div class="news-item"><span class="d" style="background:${col}" title="skor ${num(n.score, 2)}"></span><div>${title}
    <div class="meta">${esc(n.source)} · ${ago(n.ts)} lalu · skor <span class="${cls(n.score)}">${n.score > 0 ? "+" : ""}${num(n.score, 2)}</span> ${n.tickers.map((t) => `<span class="chip" data-t="${t}" style="cursor:pointer">${t}</span>`).join("")}</div></div></div>`;
}

/* ================= F2 FLOW ================= */
function vFlow(root) {
  const d = S.d, fa = d.meta.foreign_available;
  const secs = ["ALL", ...new Set(d.stocks.map((s) => s.sector))];
  const cols = [
    ["ticker", "Ticker"], ["sector", "Sektor"], ["last", "Harga", 1], ["chg_pct", "%Hari", 1], ["value", "Nilai Rp", 1],
    ["nf1", "Flow 1H", 1], ["nf5", "Flow 5H", 1], ["nf20", "Flow 20H", 1], ["nf60", "Flow 60H", 1], ["accdays", "Hari Inflow", 1],
    ...(fa ? [["fnet5", "Asing 5H", 1]] : []),
    ["cmf", "CMF", 1], ["mfi", "MFI", 1], ["volratio", "Vol x", 1], ["status", "Status"], ["flowscore", "Skor Flow"],
  ];
  const val = (s, k) => ({ ticker: s.ticker, sector: s.sector, last: s.last, chg_pct: s.chg_pct, value: s.flow.value, nf1: s.flow.nf1, nf5: s.flow.nf5,
    nf20: s.flow.nf20, nf60: s.flow.nf60, accdays: s.flow.accdays, fnet5: s.flow.fnet5, cmf: s.flow.cmf, mfi: s.flow.mfi, volratio: s.flow.volratio, status: s.flow.status, flowscore: s.scores.flow }[k]);
  const [sk, sd] = S.sort.flow;
  let rows = pool().filter((s) => S.fsec === "ALL" || s.sector === S.fsec);
  rows.sort((a, b) => { const x = val(a, sk), y = val(b, sk); return (typeof x === "string" ? x.localeCompare(y) : (x ?? -1e18) - (y ?? -1e18)) * sd; });
  const total = rows.length; rows = rows.slice(0, S.cap);
  const mx = Math.max(...d.stocks.map((s) => Math.abs(s.flow.nf20 || 0)), 1);
  const secMax = Math.max(...d.market.sectors.map((s) => Math.abs(s.nf20 || 0)), 1);
  root.innerHTML = `
  <div class="grid g21">
    <div class="panel"><h3>Money Flow Monitor <span class="fn">${fa ? "flow OHLCV + foreign BEI" : "estimasi flow = CLV × nilai transaksi"}</span></h3><div class="pb">
      <div class="filters">${scopeBar()}</div>
      <div class="filters">${secs.map((s) => `<button data-fsec="${esc(s)}" class="${S.fsec === s ? "on" : ""}">${s === "ALL" ? "Semua sektor" : esc(s)}</button>`).join("")}</div>
      <div class="tw"><table><thead><tr>${cols.map(([k, l, r]) => `<th data-sort="flow:${k}" class="${r ? "r" : ""} ${sk === k ? "sorted" + (sd > 0 ? " asc" : "") : ""}">${l}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((s) => `<tr data-t="${s.ticker}"><td class="tk">${s.ticker}</td><td class="mut">${esc(s.sector)}</td>
        <td class="r">${num(s.last)}</td><td class="r ${cls(s.chg_pct)}">${pct(s.chg_pct)}</td><td class="r">${rp(s.flow.value, false)}</td>
        <td class="r ${cls(s.flow.nf1)}">${rp(s.flow.nf1)}</td><td class="r ${cls(s.flow.nf5)}">${rp(s.flow.nf5)}</td>
        <td class="r ${cls(s.flow.nf20)}"><div style="display:flex;gap:6px;align-items:center;justify-content:flex-end">${rp(s.flow.nf20)}<div style="width:60px">${divBar(s.flow.nf20, mx)}</div></div></td>
        <td class="r ${cls(s.flow.nf60)}">${rp(s.flow.nf60)}</td><td class="r ${s.flow.accdays >= 0.58 ? "up" : s.flow.accdays <= 0.42 ? "down" : ""}">${s.flow.accdays == null ? "–" : num(s.flow.accdays * 100) + "%"}</td>
        ${fa ? `<td class="r ${cls(s.flow.fnet5)}">${rp(s.flow.fnet5)}</td>` : ""}
        <td class="r ${cls(s.flow.cmf)}">${num(s.flow.cmf, 2)}</td><td class="r">${num(s.flow.mfi)}</td><td class="r ${s.flow.volratio >= 1.5 ? "amb" : ""}">${num(s.flow.volratio, 1)}x</td>
        <td class="${s.flow.status === "AKUMULASI" ? "up" : s.flow.status === "DISTRIBUSI" ? "down" : "mut"}">${s.flow.status}</td>
        <td style="width:110px">${scoreBar(s.scores.flow)}</td></tr>`).join("") || `<tr><td colspan="16" class="mut">Tidak ada saham yang cocok.</td></tr>`}</tbody></table></div>${moreBar(total)}
      <div class="note">Skor Flow = peringkat <b>akumulasi</b> di antara saham likuid: net flow 20H & 60H, CMF 20H & 60H, OBV 60H, nilai transaksi hari naik ÷ hari turun (50H), dan porsi hari dengan net inflow (60H). Hari Inflow = persentase hari dalam 60 hari bursa terakhir yang ditutup dengan net inflow.</div>
    </div></div>
    <div class="stack">
      <div class="panel"><h3>Net Flow Sektor 20H</h3><div class="pb">
        ${d.market.sectors.slice().sort((a, b) => b.nf20 - a.nf20).map((s) => `<div style="display:grid;grid-template-columns:150px 1fr 80px;gap:6px;align-items:center;padding:2px 0;cursor:pointer" data-fsec="${esc(s.sector)}">
          <span class="mut">${esc(s.sector)}</span>${divBar(s.nf20, secMax)}<span class="r ${cls(s.nf20)}">${rp(s.nf20)}</span></div>`).join("")}
      </div></div>
      <div class="panel"><h3>Cara Membaca</h3><div class="pb small">
        <p><b class="amb">Flow (Rp)</b> = Σ CLV × harga × volume. CLV +1 bila close di high (pembeli agresif), −1 bila di low. Ini <i>estimasi</i> arah uang dari OHLCV, bukan data broker summary.</p>
        <p><b class="amb">CMF</b> &gt; +0,05 = tekanan beli dominan 20 hari; &lt; −0,05 = tekanan jual. <b class="amb">MFI</b> = RSI berbobot volume (&gt;80 jenuh beli).</p>
        <p><b class="amb">AKUMULASI</b> = CMF &gt; 0,05 + flow 20H positif + OBV naik. <b class="amb">DISTRIBUSI</b> kebalikannya.</p>
        <p><b class="amb">Vol x</b> = nilai transaksi 5H ÷ rata-rata 60H. &gt;1,5x = ada perhatian/aksi besar.</p>
        ${fa ? "" : `<p class="mut">Data foreign flow BEI tidak tersedia pada run ini (situs BEI memblokir akses otomatis). Kolom asing muncul otomatis bila berhasil diambil.</p>`}
      </div></div>
    </div>
  </div>`;
}

/* ================= F3 SIGNAL ================= */
function vSignal(root) {
  const d = S.d, cf = d.config.signal;
  const opts = ["ALL", "STRONG BUY", "BUY", "HOLD", "REDUCE", "EXIT", "AVOID"];
  let rows = pool(S.fsig === "AVOID").filter((s) => S.fsig === "ALL" || (S.fsig === "HELD" ? isHeld(s) : S.fsig === "CAND" ? isCand(s) : s.signal === S.fsig));
  const nCand = d.stocks.filter(isCand).length;
  const [sk, sd] = S.sort.signal;
  const key = (s) => ({ rank: SIGRANK[s.signal] * 1000 - (s.scores.composite || 0), pass: (s.checks || []).filter((c) => c.ok).length, ticker: s.ticker, comp: s.scores.composite, flow: s.scores.flow,
    mom: s.scores.momentum, trend: s.scores.trend, sent: s.scores.sentiment, time: s.scores.timing, last: s.last, rsi: s.ind.rsi, rr: s.levels.rr2 }[sk]);
  rows.sort((a, b) => { const x = key(a), y = key(b); return (typeof x === "string" ? x.localeCompare(y) : (x ?? -1e9) - (y ?? -1e9)) * sd; });
  const total = rows.length; rows = rows.slice(0, S.cap);
  const th = (k, l, r) => `<th data-sort="signal:${k}" class="${r ? "r" : ""} ${sk === k ? "sorted" + (sd > 0 ? " asc" : "") : ""}">${l}</th>`;
  root.innerHTML = `
  <div class="panel"><h3>Signal Board · kapan IN & EXIT <span class="fn">rezim ${d.market.regime.label} · klik baris untuk chart & rencana trade</span></h3><div class="pb">
    ${gateBox()}
    <div class="filters">${scopeBar()}</div>
    <div class="filters">${d.market.gate && d.market.gate.held ? `<button data-fsig="HELD" class="${S.fsig === "HELD" ? "on" : ""}">DITAHAN ${d.market.gate.held}</button>` : ""}${d.stocks.some((x) => x.checks && x.checks.length) ? `<button data-fsig="CAND" class="${S.fsig === "CAND" ? "on" : ""}" title="Lolos syarat inti: skor momentum & inflow akumulasi">KANDIDAT ${nCand}</button>` : ""}${opts.map((o) => `<button data-fsig="${o}" class="${S.fsig === o ? "on" : ""}">${o === "ALL" ? "Semua sinyal" : o}${o === "ALL" ? "" : " " + (d.market.signal_count[o] || 0)}</button>`).join("")}</div>
    <div class="tw"><table><thead><tr>${th("ticker", "Ticker")}${th("rank", "Sinyal")}${th("pass", "Syarat", 1)}${th("comp", "Komposit")}${th("flow", "Flow", 1)}${th("mom", "Mom", 1)}${th("trend", "Trend", 1)}${th("sent", "Sent", 1)}${useTiming() ? th("time", "Timing", 1) : ""}
      ${th("last", "Harga", 1)}<th class="r">Zona Beli</th><th class="r">Stop (close)</th><th class="r">TP1 / TP2</th>${th("rr", "R:R", 1)}${th("rsi", "RSI", 1)}<th>Belum lolos / alasan</th></tr></thead>
    <tbody>${rows.map((s) => { const L = s.levels, buy = s.signal === "BUY" || s.signal === "STRONG BUY"; return `<tr data-t="${s.ticker}">
      <td class="tk">${s.ticker}</td><td>${sig(s.signal)}</td>${passCell(s)}<td style="width:110px">${scoreBar(s.scores.composite)}</td>
      ${["flow", "momentum", "trend", "sentiment", "timing"].filter((k) => k !== "timing" || useTiming()).map((k) => `<td class="r" style="color:${scoreColor(s.scores[k])}">${num(s.scores[k])}${(k === "flow" && cf.min_flow_score && s.scores.flow >= cf.min_flow_score) || (k === "momentum" && cf.min_mom_score && s.scores.momentum >= cf.min_mom_score) ? ' <span class="up">✓</span>' : ""}</td>`).join("")}
      <td class="r b">${num(s.last)} <span class="${cls(s.chg_pct)} small">${pct(s.chg_pct)}</span></td>
      <td class="r ${buy ? "" : "dim"}">${num(L.entry_low)}–${num(L.entry_high)}</td>
      <td class="r ${buy ? "down" : "dim"}">${num(L.sl)} <span class="small">${pct(L.sl_pct)}</span></td>
      <td class="r ${buy ? "up" : "dim"}">${num(L.tp1)} / ${num(L.tp2)}</td><td class="r">${num(L.rr2, 1)}</td><td class="r ${s.ind.rsi >= cf.rsi_overbought ? "down" : ""}">${num(s.ind.rsi)}</td>
      <td>${buy ? "" : failed(s).slice(0, 2).map(failChip).join("")}${s.reasons.slice(0, buy || !failed(s).length ? 2 : 1).map(chip).join("")}${s.signal === "EXIT" || s.signal === "REDUCE" ? s.reasons.filter((r) => r.s < 0).slice(0, 1).map(chip).join("") : ""}</td></tr>`; }).join("") || `<tr><td colspan="16" class="mut">Tidak ada saham yang cocok.</td></tr>`}</tbody></table></div>${moreBar(total)}
    <div class="note">${cf.market_filter ? `Beli baru hanya saat IHSG di atas ${String(cf.market_filter).toUpperCase()}` : ""}${cf.max_atr_pct ? ` dan ATR saham ≤ ${num(cf.max_atr_pct * 100)}%/hari. ` : ". "}${cf.min_mom_score || cf.min_flow_score ? `<b>Syarat inti:</b> skor momentum ≥ ${cf.min_mom_score || 0} dan skor flow (akumulasi) ≥ ${cf.min_flow_score || 0} — tanda ✓ = lolos. Kolom <b>Syarat</b> = berapa syarat beli yang sudah lolos (semua lolos = BUY); filter <b>KANDIDAT</b> = saham yang sudah lolos dua syarat inti itu. ` : ""}STRONG BUY = komposit ≥ ${cf.strong_buy} + uptrend + flow positif ganda · BUY = komposit ≥ ${cf.buy} + uptrend + flow positif · EXIT = close &lt; trailing stop, atau tembus MA50 dengan CMF negatif, atau komposit &lt; ${cf.exit}.
    Stop dicek di harga <b>penutupan</b> (eksekusi besok pagi) karena stop intraday rawan kena “jarum”. Zona beli = harga − 0,75×ATR s/d harga (atau MA20).</div>
  </div></div>`;
}
function gateBox() {
  const g = S.d.market.gate;
  if (!g) return "";
  return g.open
    ? `<div class="callout" style="margin-bottom:8px;border-color:var(--up);color:#bfe8cf;background:#06120b">Gerbang beli <b>TERBUKA</b> — ${esc(g.rule)} (IHSG ${num(g.ihsg, 0)} vs ${num(g.ma, 0)}, ${pct(g.gap)}).</div>`
    : `<div class="callout red" style="margin-bottom:8px">Gerbang beli <b>TERTUTUP</b> — IHSG ${num(g.ihsg, 0)} di bawah ${esc(g.rule.split("> ")[1])} ${num(g.ma, 0)} (${pct(g.gap)}). Model tidak membuka posisi baru sampai pasar pulih${g.held ? `; <b>${g.held} saham</b> lolos kriteria dan masuk daftar pantau (filter “DITAHAN”)` : ""}. Posisi lama tetap dijaga dengan stop.</div>`;
}
const isHeld = (s) => s.notes.some((n) => n.includes("DITAHAN"));
const chk = (s, k) => (s.checks || []).find((c) => c.k === k);
const isCand = (s) => { const m = chk(s, "mom"), f = chk(s, "flow"); return !!(m && f && m.ok && f.ok); };      // lolos syarat inti momentum + inflow
const failed = (s) => (s.checks || []).filter((c) => !c.ok);
const passCell = (s) => { const c = s.checks || []; if (!c.length) return `<td class="r dim">–</td>`; const n = c.filter((x) => x.ok).length;
  return `<td class="r ${n === c.length ? "up b" : n >= c.length - 2 ? "amb" : "mut"}" title="${esc(failed(s).map((x) => "✗ " + x.t).join("\n") || "Semua syarat lolos")}">${n}/${c.length}</td>`; };
const failChip = (c) => `<span class="chip n">✗ ${esc(c.t.replace(/ \(.*\)$/, ""))}${c.v ? " · " + esc(c.v) : ""}</span>`;
const chip = (r) => `<span class="chip ${r.s > 0 ? "p" : r.s < 0 ? "n" : "z"}">${esc(r.t)}</span>`;

/* ================= F4 PORTO ================= */
function portDefaults() {
  const p = S.d.config.portfolio;
  return { equity: p.equity, risk: p.risk_per_trade * 100, maxpos: p.max_positions, maxw: p.max_weight * 100, maxsec: p.max_sector * 100,
    feeb: S.d.rules.fee_buy * 100, regime: true, entry: "last", buyFactor: 75, dd: 0 };
}
function buildPort(p) {
  const d = S.d, lot = d.rules.lot_size, fee = p.feeb / 100;
  const cap = p.regime ? d.market.regime.exposure : 1;
  const maxInvest = p.equity * cap;
  const cands = d.stocks.filter((s) => s.signal === "STRONG BUY" || s.signal === "BUY")
    .sort((a, b) => (SIGRANK[a.signal] - SIGRANK[b.signal]) || (b.scores.composite - a.scores.composite));
  let invested = 0; const secUsed = {}; const rows = []; const skipped = [];
  const brake = d.config.risk && d.config.risk.dd_brake ? d.config.risk.dd_brake * 100 : null;
  const braked = brake != null && (p.dd || 0) >= brake;
  const maxpos = braked ? Math.max(1, Math.floor(p.maxpos / 2)) : p.maxpos;      // rem drawdown: slot separuh
  for (const s of cands) {
    if (rows.length >= maxpos) { skipped.push([s.ticker, braked ? "slot dipangkas (rem drawdown)" : "slot penuh"]); continue; }
    const entry = p.entry === "low" ? s.levels.entry_low : s.levels.entry_high;
    const sl = s.levels.sl, rps = entry - sl;
    if (!(rps > 0)) { skipped.push([s.ticker, "entry ≤ SL"]); continue; }
    const riskBudget = p.equity * (p.risk / 100) * (s.signal === "BUY" ? p.buyFactor / 100 : 1);
    let sh = riskBudget / rps;
    sh = Math.min(sh, (p.equity * p.maxw / 100) / entry);
    sh = Math.min(sh, Math.max(0, p.equity * p.maxsec / 100 - (secUsed[s.sector] || 0)) / entry);
    sh = Math.min(sh, Math.max(0, maxInvest - invested) / (entry * (1 + fee)));
    const lots = Math.floor(sh / lot);
    if (lots < 1) { skipped.push([s.ticker, entry * lot * (1 + fee) > maxInvest - invested ? "modal/eksposur habis" : "batas risiko/sektor < 1 lot"]); continue; }
    const shares = lots * lot, value = shares * entry, cost = value * (1 + fee);
    invested += cost; secUsed[s.sector] = (secUsed[s.sector] || 0) + value;
    rows.push({ s, entry, sl, lots, shares, value, cost, w: value / p.equity, risk: shares * rps,
      gain1: shares * (s.levels.tp1 - entry), gain2: shares * (s.levels.tp2 - entry) });
  }
  const risk = rows.reduce((a, r) => a + r.risk, 0);
  return { rows, skipped, invested, cash: p.equity - invested, risk, heat: risk / p.equity, cap, maxInvest, secUsed, braked, maxpos, brake };
}
function vPorto(root) {
  const p = Object.assign(portDefaults(), store.get("port", {}));
  const bt = S.d.backtest;
  root.innerHTML = `
  <div class="grid g12">
    <div class="stack">
      <div class="panel"><h3>Parameter Modal & Risiko</h3><div class="pb">
        <div class="form" id="pform">
          <label>Modal / ekuitas (Rp)<input id="p-equity" inputmode="numeric" value="${nf0.format(p.equity)}"></label>
          <label>Risiko per posisi (% modal)<input id="p-risk" type="number" step="0.25" min="0.1" value="${p.risk}"></label>
          <label>Maks jumlah posisi<input id="p-maxpos" type="number" min="1" max="20" value="${p.maxpos}"></label>
          <label>Maks bobot per saham (%)<input id="p-maxw" type="number" min="5" max="100" value="${p.maxw}"></label>
          <label>Maks bobot per sektor (%)<input id="p-maxsec" type="number" min="10" max="100" value="${p.maxsec}"></label>
          <label>Fee beli (%)<input id="p-feeb" type="number" step="0.01" value="${p.feeb}"></label>
          <label>Ukuran sinyal BUY vs STRONG (%)<input id="p-buyFactor" type="number" min="25" max="100" step="5" value="${p.buyFactor}"></label>
          <label>Harga entry<select id="p-entry"><option value="last" ${p.entry === "last" ? "selected" : ""}>Harga terakhir</option><option value="low" ${p.entry === "low" ? "selected" : ""}>Bawah zona (antri limit)</option></select></label>
          <label>Drawdown portofoliomu saat ini (%)<input id="p-dd" type="number" min="0" max="100" step="1" value="${p.dd || 0}"></label>
          <label>Ikuti batas eksposur rezim<select id="p-regime"><option value="1" ${p.regime ? "selected" : ""}>Ya (${S.d.market.regime.label} → ${Math.round(S.d.market.regime.exposure * 100)}%)</option><option value="0" ${!p.regime ? "selected" : ""}>Tidak</option></select></label>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px"><button class="btn" id="p-copy">Salin rencana</button><button class="btn" id="p-reset">Reset</button></div>
      </div></div>
      <div class="panel"><h3>Referensi Kelly (dari backtest)</h3><div class="pb small">
        <dl class="kv"><dt>Win rate</dt><dd>${pct(bt.stats.win_rate, 0).replace("+", "")}</dd><dt>Payoff (avg win / avg loss)</dt><dd>${num(bt.stats.payoff, 2)}</dd>
        <dt>Kelly penuh</dt><dd class="${cls(bt.kelly.full)}">${pct(bt.kelly.full, 1)}</dd><dt>Half-Kelly</dt><dd>${pct(bt.kelly.half, 1).replace("+", "")}</dd></dl>
        <div class="callout" style="margin-top:8px">${esc(bt.kelly.note)} ${bt.kelly.full <= 0 ? "Kelly ≤ 0 berarti backtest belum menunjukkan edge — pakai risiko kecil (≤0,5%) atau tunggu data live." : ""}</div>
      </div></div>
    </div>
    <div class="stack" id="p-out"></div>
  </div>`;
  const read = () => {
    const g = (id) => $("#p-" + id).value;
    const q = { equity: Math.max(0, parseFloat(String(g("equity")).replace(/\./g, "").replace(/,/g, ".")) || 0), risk: +g("risk"), maxpos: +g("maxpos"), maxw: +g("maxw"),
      maxsec: +g("maxsec"), feeb: +g("feeb"), buyFactor: +g("buyFactor"), entry: g("entry"), regime: g("regime") === "1", dd: +g("dd") || 0 };
    store.set("port", q);
    return q;
  };
  const draw = () => drawPort(read());
  $("#pform").addEventListener("input", draw);
  $("#p-equity").addEventListener("blur", (e) => { const v = read().equity; e.target.value = nf0.format(v); });
  $("#p-reset").onclick = () => { store.set("port", {}); vPorto(root); };
  $("#p-copy").onclick = async () => {
    const r = buildPort(read());
    const txt = [`RENCANA PORTOFOLIO IDXQ — ${S.d.meta.data_asof} (${S.d.market.regime.label})`, ...r.rows.map((x) =>
      `${x.s.ticker} ${x.s.signal}: ${x.lots} lot @${num(x.entry)} (${rupiah(x.cost)}) SL ${num(x.sl)} TP ${num(x.s.levels.tp1)}/${num(x.s.levels.tp2)}`),
      `Total ${rupiah(r.invested)} · Kas ${rupiah(r.cash)} · Risiko ${pct(r.heat, 1)}`].join("\n");
    try { await navigator.clipboard.writeText(txt); toast("Rencana disalin"); } catch { toast("Clipboard tidak diizinkan"); }
  };
  drawPort(p);
}
function drawPort(p) {
  const r = buildPort(p), out = $("#p-out");
  const secs = Object.entries(r.secUsed).sort((a, b) => b[1] - a[1]);
  out.innerHTML = `
    <div class="panel"><h3>Ringkasan Alokasi</h3><div class="pb"><div class="tiles">
      <div class="tile"><div class="l">Modal</div><div class="v">${rupiah(p.equity)}</div></div>
      <div class="tile"><div class="l">Diinvestasikan</div><div class="v">${rupiah(r.invested)}</div><div class="mut small">${pct(r.invested / (p.equity || 1), 1).replace("+", "")} · batas ${Math.round(r.cap * 100)}%</div></div>
      <div class="tile"><div class="l">Kas</div><div class="v">${rupiah(r.cash)}</div></div>
      <div class="tile"><div class="l">Total risiko (heat)</div><div class="v ${r.heat > 0.08 ? "down" : ""}">${pct(r.heat, 2).replace("+", "")}</div><div class="mut small">${rupiah(r.risk)} jika semua kena SL</div></div>
      <div class="tile"><div class="l">Posisi</div><div class="v">${r.rows.length}</div></div>
    </div></div></div>
    <div class="panel"><h3>Kombinasi Posisi <span class="fn">lot 100 lembar · harga sudah dibulatkan ke fraksi BEI</span></h3><div class="pb">${gateBox()}
      ${r.braked ? `<div class="callout" style="margin-bottom:8px">Rem drawdown aktif: portofoliomu turun ≥ ${num(r.brake)}% dari puncak, jadi slot dipangkas dari ${p.maxpos} menjadi ${r.maxpos} posisi.</div>` : ""}<div class="tw"><table>
      <thead><tr><th>Ticker</th><th>Sinyal</th><th class="r">Lot</th><th class="r">Entry</th><th class="r">Nilai (incl. fee)</th><th class="r">Bobot</th><th class="r">Stop</th><th class="r">Risiko Rp</th><th class="r">TP1 / TP2</th><th class="r">Potensi @TP1</th></tr></thead>
      <tbody>${r.rows.map((x) => `<tr data-t="${x.s.ticker}"><td class="tk">${x.s.ticker}</td><td>${sig(x.s.signal)}</td><td class="r b">${num(x.lots)}</td><td class="r">${num(x.entry)}</td>
        <td class="r">${rupiah(x.cost)}</td><td class="r">${pct(x.w, 1).replace("+", "")}</td><td class="r down">${num(x.sl)}</td><td class="r down">${rupiah(x.risk)}</td>
        <td class="r up">${num(x.s.levels.tp1)} / ${num(x.s.levels.tp2)}</td><td class="r up">+${rupiah(x.gain1)}</td></tr>`).join("") ||
        `<tr><td colspan="10" class="mut">Tidak ada posisi: belum ada sinyal BUY, atau modal terlalu kecil untuk 1 lot.</td></tr>`}</tbody></table></div>
      ${r.skipped.length ? `<div class="note">Dilewati: ${r.skipped.slice(0, 10).map(([t, w]) => `${t} (${w})`).join(" · ")}${r.skipped.length > 10 ? ` · +${r.skipped.length - 10} lainnya` : ""}</div>` : ""}
      <div class="note">Ukuran posisi = (modal × risiko%) ÷ (entry − stop), lalu dibatasi bobot saham, bobot sektor, dan eksposur rezim. Saham volatil otomatis dapat lot lebih sedikit.${r.brake != null ? ` Isi “drawdown portofoliomu” supaya rem ${num(r.brake)}% ikut dihitung.` : ""}</div>
    </div></div>
    <div class="panel"><h3>Alokasi Sektor</h3><div class="pb">${secs.map(([k, v]) => `<div style="display:grid;grid-template-columns:150px 1fr 60px;gap:6px;align-items:center;padding:2px 0">
      <span class="mut">${esc(k)}</span><div class="bar"><span style="width:${(v / p.equity) * 100}%;background:${COL.s1}"></span></div><span class="r">${pct(v / p.equity, 1).replace("+", "")}</span></div>`).join("") || `<span class="mut">–</span>`}
      <div style="display:grid;grid-template-columns:150px 1fr 60px;gap:6px;align-items:center;padding:2px 0"><span class="mut">Kas</span><div class="bar"><span style="width:${Math.max(0, r.cash / (p.equity || 1)) * 100}%;background:#555"></span></div><span class="r">${pct(r.cash / (p.equity || 1), 1).replace("+", "")}</span></div>
    </div></div>`;
}

/* ================= F5 NEWS ================= */
function vNews(root) {
  const d = S.d;
  let list = d.stocks.filter((s) => s.sent && s.sent.n > 0).sort((a, b) => b.sent.score - a.sent.score);
  if (list.length > 50) list = [...list.slice(0, 25), ...list.slice(-25)];
  const q = S.fnews.toUpperCase();
  const news = d.news.filter((n) => !q || n.tickers.includes(q) || n.title.toUpperCase().includes(q));
  root.innerHTML = `
  <div class="grid g12">
    <div class="stack">
      <div class="panel"><h3>Sentimen Pasar <span class="fn">${esc(d.sentiment.method || "")}</span></h3><div class="pb">${gauge(d.market.sentiment.score)}
        <div class="mut small" style="margin-top:6px">${d.market.sentiment.n} berita 14 hari · update ${d.sentiment.updated ? ago(d.sentiment.updated) + " lalu" : "–"}</div></div></div>
      <div class="panel"><h3>Skor Sentimen per Saham</h3><div class="pb">
        ${list.map((s) => `<div style="display:grid;grid-template-columns:52px 1fr 36px 40px;gap:6px;align-items:center;padding:2px 0;cursor:pointer" data-t="${s.ticker}">
          <span class="amb b">${s.ticker}</span>${divBar(s.sent.score - 50, 50)}<span class="r">${num(s.sent.score)}</span><span class="mut r small">${s.sent.n} br</span></div>`).join("") || `<span class="mut">Belum ada berita.</span>`}
        <div class="note">Maks 25 paling positif + 25 paling negatif. Skor 50 = netral. Berita dibobot waktu (half-life 3 hari) & di-shrink bila beritanya sedikit.</div></div></div>
    </div>
    <div class="panel"><h3>News Feed <span class="fn">${news.length} item</span></h3><div class="pb">
      <div class="filters"><input id="nq" placeholder="Filter ticker / kata" value="${esc(S.fnews)}"></div>
      ${news.slice(0, 120).map(newsItem).join("") || `<span class="mut">Tidak ada berita.</span>`}
    </div></div>
  </div>`;
  const nq = $("#nq");
  nq.addEventListener("change", () => { S.fnews = nq.value.trim(); renderView(); });
}

/* ================= F6 BTEST ================= */
function vBtest(root) {
  const b = S.d.backtest, st = b.stats, bs = b.bench;
  const row = (l, a, x, fmt, good = 1) => `<tr><td class="mut">${l}</td><td class="r b ${a == null ? "" : (good * (a - (x ?? a))) > 0 ? "up" : (good * (a - (x ?? a))) < 0 ? "down" : ""}">${fmt(a)}</td><td class="r">${x == null ? "" : fmt(x)}</td></tr>`;
  const p = (x) => pct(x, 1), n2 = (x) => num(x, 2);
  root.innerHTML = `
  <div class="grid g21">
    <div class="stack">
      <div class="panel"><h3>Equity Curve · Strategi vs IHSG <span class="fn">${b.start} → ${b.end} · modal awal ${rupiah(b.equity0)}</span></h3><div class="pb">
        <div class="chart lg" id="c-eq"><div class="legend" id="lg-eq"></div></div></div></div>
      <div class="panel"><h3>Drawdown Strategi</h3><div class="pb"><div class="chart sm" id="c-dd"></div></div></div>
      <div class="panel"><h3>Trade Terakhir</h3><div class="pb"><div class="tw" style="max-height:340px"><table>
        <thead><tr><th>Ticker</th><th>Masuk</th><th>Keluar</th><th class="r">Harga masuk</th><th class="r">Harga keluar</th><th class="r">Return</th><th class="r">Hari</th><th>Alasan</th></tr></thead>
        <tbody>${b.trades.map((t) => `<tr data-t="${t.ticker}"><td class="tk">${t.ticker}</td><td>${t.entry_date}</td><td>${t.exit_date}</td><td class="r">${num(t.entry)}</td><td class="r">${num(t.exit)}</td>
          <td class="r ${cls(t.ret)}">${pct(t.ret, 1)}</td><td class="r">${t.days}</td><td class="mut">${esc(t.reason)}</td></tr>`).join("")}</tbody></table></div></div></div>
    </div>
    <div class="stack">
      <div class="panel"><h3>Statistik</h3><div class="pb"><table><thead><tr><th></th><th class="r">Strategi</th><th class="r">IHSG</th></tr></thead><tbody>
        ${row("Total return", st.total_return, bs.total_return, p)}${row("CAGR", st.cagr, bs.cagr, p)}${row("Volatilitas", st.vol, bs.vol, (x) => pct(x, 1).replace("+", ""), -1)}
        ${row("Sharpe", st.sharpe, bs.sharpe, n2)}${row("Sortino", st.sortino, bs.sortino, n2)}${row("Max drawdown", st.max_dd, bs.max_dd, p)}${row("Calmar", st.calmar, bs.calmar, n2)}
      </tbody></table>
      <div class="tiles" style="margin-top:8px">
        <div class="tile"><div class="l">Jumlah trade</div><div class="v">${st.trades}</div></div>
        <div class="tile"><div class="l">Win rate</div><div class="v">${pct(st.win_rate, 0).replace("+", "")}</div></div>
        <div class="tile"><div class="l">Payoff</div><div class="v">${num(st.payoff, 2)}</div></div>
        <div class="tile"><div class="l">Profit factor</div><div class="v ${st.profit_factor >= 1 ? "up" : "down"}">${num(st.profit_factor, 2)}</div></div>
        <div class="tile"><div class="l">Expectancy/trade</div><div class="v ${cls(st.expectancy)}">${pct(st.expectancy, 2)}</div></div>
        <div class="tile"><div class="l">Rata-rata hold</div><div class="v">${num(st.avg_days, 1)} hr</div></div>
        <div class="tile"><div class="l">Modal awal</div><div class="v">${rupiah(b.equity0)}</div></div>
        <div class="tile"><div class="l">Nilai akhir</div><div class="v ${cls((b.final_equity || b.equity[b.equity.length - 1]) - b.equity0)}">${rupiah(b.final_equity || b.equity[b.equity.length - 1])}</div></div>
        ${b.lot_skips && b.lot_skips.skipped ? `<div class="tile"><div class="l">Sinyal tak terbeli (lot)</div><div class="v">${b.lot_skips.skipped}<span class="mut small"> / ${b.lot_skips.signals}</span></div></div>` : ""}
        ${b.lot_skips && b.lot_skips.nofill ? `<div class="tile"><div class="l">Batal: terkunci ARA</div><div class="v">${b.lot_skips.nofill}</div></div>` : ""}
      </div></div></div>
      ${b.yearly && b.yearly.length ? `<div class="panel"><h3>Return per Tahun <span class="fn">* = tahun parsial</span></h3><div class="pb"><table>
        <thead><tr><th>Tahun</th><th class="r">Strategi</th><th class="r">IHSG</th><th class="r">Selisih</th><th class="r">Max DD</th><th class="r">Trade</th></tr></thead>
        <tbody>${b.yearly.map((y) => `<tr><td>${y.year}${y.partial ? "*" : ""}</td><td class="r b ${cls(y.ret)}">${pct(y.ret, 1)}</td><td class="r ${cls(y.bench)}">${pct(y.bench, 1)}</td>
          <td class="r ${cls(y.ret - y.bench)}">${pct(y.ret - y.bench, 1)}</td><td class="r">${pct(y.max_dd, 1)}</td><td class="r">${y.trades}</td></tr>`).join("")}</tbody></table>
        <div class="note">Menang vs IHSG di ${b.yearly.filter((y) => y.ret > y.bench).length} dari ${b.yearly.length} tahun · tahun positif ${b.yearly.filter((y) => y.ret > 0).length} dari ${b.yearly.length}.${b.universe ? ` Saham likuid yang dinilai: ±${b.universe.liquid_start} di awal periode → ±${b.universe.liquid_end} sekarang.` : ""}</div></div></div>` : ""}
      <div class="panel"><h3>Asumsi & Keterbatasan</h3><div class="pb small"><ul style="margin:0;padding-left:16px">${b.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>
        ${S.d.meta.mode === "demo" ? `<div class="callout red" style="margin-top:8px">Hasil di mode demo berasal dari data acak — tidak bermakna untuk menilai strategi.</div>` : ""}</div></div>
    </div>
  </div>`;
  const c = mkChart($("#c-eq"), S.charts);
  const s1 = c.addLineSeries({ color: COL.s1, lineWidth: 2, priceLineVisible: false });
  const s2 = c.addLineSeries({ color: COL.s2, lineWidth: 2, priceLineVisible: false });
  s1.setData(ser(b.dates, b.equity)); s2.setData(ser(b.dates, b.bench_equity)); c.timeScale().fitContent();
  const lg = $("#lg-eq");
  const setLg = (i) => { lg.innerHTML = `<span class="mut">${b.dates[i]}</span><i style="background:${COL.s1}"></i>Strategi ${rupiah(b.equity[i])}<i style="background:${COL.s2}"></i>IHSG ${rupiah(b.bench_equity[i])}`; };
  setLg(b.dates.length - 1);
  c.subscribeCrosshairMove((q) => { const i = q && q.time ? b.dates.indexOf(q.time) : -1; setLg(i >= 0 ? i : b.dates.length - 1); });
  const c2 = mkChart($("#c-dd"), S.charts, { localization: { priceFormatter: (x) => pct(x, 0) } });
  const dd = c2.addAreaSeries({ lineColor: COL.down, topColor: "rgba(240,71,79,.05)", bottomColor: "rgba(240,71,79,.35)", lineWidth: 1, priceLineVisible: false });
  dd.setData(ser(b.dates, b.drawdown)); c2.timeScale().fitContent();
}

/* ================= F7 HELP ================= */
function vHelp(root) {
  const d = S.d, w = d.config.weights, r = d.rules;
  root.innerHTML = `<div class="grid g2 help">
  <div class="panel"><h3>Metodologi Model</h3><div class="pb">
    <h4>1 · Skor komposit (0–100)</h4>
    <table><tbody>${[["Flow", w.flow, (d.config.signal.flow_score || "akumulasi") === "akumulasi" ? "Akumulasi inflow, peringkat di antara saham likuid: intensitas net flow 20H & 60H (dinormalisasi likuiditas), CMF 20H & 60H, momentum OBV 60H, nilai transaksi hari naik ÷ hari turun (50H), porsi hari dengan net inflow (60H)" + (d.meta.foreign_available ? ", net beli asing 5H" : "") : "Peringkat cross-sectional: intensitas net flow 20H & 5H (dinormalisasi likuiditas), CMF-20, momentum OBV, MFI-14" + (d.meta.foreign_available ? ", net beli asing 5H" : "")],
      ["Momentum", w.momentum, "Momentum 12-1 bulan (Jegadeesh-Titman / Asness-Moskowitz-Pedersen), 6-1 bulan, return 3 bulan, kedekatan ke 52-week high (George-Hwang)"],
      ["Trend", w.trend, "Absolut: posisi harga vs MA20/50/200, golden cross MA50>MA200, kemiringan MA50"],
      ["Sentimen", w.sentiment, "Berita 14 hari (Google News, CNBC Indonesia), leksikon keuangan ID/EN; opsional dinilai Claude"],
      ["Timing", w.timing, "Hindari mengejar: jarak dari MA20 dalam satuan ATR & RSI-14 (penalti overbought)"]]
      .filter(([, v]) => v > 0).map(([k, v, t]) => `<tr><td class="amb b">${k}</td><td class="r">${Math.round(v * 100)}%</td><td style="white-space:normal">${t}</td></tr>`).join("")}</tbody></table>
    <h4>2 · Aturan IN & EXIT (long-only)</h4>
    <ul><li><b>STRONG BUY</b>: komposit ≥ ${d.config.signal.strong_buy}, close &gt; MA50 &amp; MA20 &gt; MA50, CMF &gt; 0 <i>dan</i> flow 5H &gt; 0, RSI &lt; ${d.config.signal.rsi_overbought - 3}, rezim bukan RISK-OFF.</li>
      <li><b>BUY</b>: komposit ≥ ${d.config.signal.buy}, uptrend yang sama, CMF &gt; 0 <i>atau</i> flow 5H &gt; 0, RSI &lt; ${d.config.signal.rsi_overbought}.</li>
      ${d.config.signal.min_mom_score || d.config.signal.min_flow_score ? `<li><b>Syarat inti (momentum + akumulasi)</b>: BUY/STRONG BUY hanya untuk saham dengan skor momentum ≥ ${d.config.signal.min_mom_score || 0} (papan atas momentum) <i>dan</i> skor flow ≥ ${d.config.signal.min_flow_score || 0} (inflow akumulasi lebih kuat dari kebanyakan saham). Di uji 10 tahun, syarat momentum inilah penyumbang perbaikan terbesar; syarat inflow menekan drawdown (lihat engine/flowmom.py).</li>` : ""}
      ${d.config.signal.market_filter ? `<li><b>Gerbang beli</b>: sinyal beli hanya muncul saat IHSG di atas ${String(d.config.signal.market_filter).toUpperCase()}. Di bawah itu, saham yang lolos kriteria diberi catatan “DITAHAN” (daftar pantau).</li>` : ""}
      ${d.config.signal.max_atr_pct ? `<li><b>Batas keliaran</b>: saham dengan ATR &gt; ${num(d.config.signal.max_atr_pct * 100)}%/hari tidak dibeli — jarak stop terlalu lebar dan sering gap.</li>` : ""}
      <li><b>EXIT</b>: close &lt; chandelier stop (high 22H − ${d.config.signal.trail_atr_mult}×ATR), atau close &lt; MA50 dengan CMF &lt; 0, atau komposit &lt; ${d.config.signal.exit}.</li>
      <li><b>REDUCE</b>: komposit &lt; ${d.config.signal.reduce}, RSI &gt; 80, atau status DISTRIBUSI — ambil sebagian profit / perketat stop.</li>
      <li><b>Level</b>: Stop = harga − ${d.config.signal.atr_stop_mult}×ATR (dicek di close), TP1 = ${d.config.signal.tp1_r}R, TP2 = ${d.config.signal.tp2_r}R, semua dibulatkan ke fraksi BEI.</li></ul>
    <h4>3 · Rezim pasar</h4>
    <p>6 faktor: IHSG vs MA200, MA50 vs MA200, breadth (&gt;50% / &lt;30% saham di atas MA50), volatilitas IHSG (persentil &gt;80 = negatif), pelemahan rupiah 20H &gt; 1,5%. Skor ≥ 2 RISK-ON (eksposur ${Math.round(d.config.regime_exposure["RISK-ON"] * 100)}%), 0–1 NEUTRAL (${Math.round(d.config.regime_exposure.NEUTRAL * 100)}%), &lt; 0 RISK-OFF (${Math.round(d.config.regime_exposure["RISK-OFF"] * 100)}%).</p>
    <h4>4 · Position sizing</h4>
    <p>Fixed-fractional risk: lot = (modal × risiko%) ÷ (entry − stop) ÷ 100, dibatasi bobot maks per saham, per sektor, dan eksposur rezim. Half-Kelly dari backtest hanya sebagai batas atas referensi.</p>
    ${d.config.risk ? `<p><b>Pengaman drawdown</b> (dipakai backtest & tab PORT): risiko ${num(d.config.risk.risk_per_trade * 100, 2)}% modal per posisi, maks ${num(d.config.risk.max_weight * 100)}% per saham${d.config.risk.dd_brake ? `, dan <b>rem drawdown</b>: bila portofolio turun &gt; ${num(d.config.risk.dd_brake * 100)}% dari puncak, jumlah slot dipangkas separuh sampai pulih` : ""}. Dipilih dari uji 36 varian di data 10 tahun (lihat engine/diagnose.py).</p>` : ""}
  </div></div>
  <div class="stack">
    <div class="panel"><h3>Aturan BEI yang Dipakai</h3><div class="pb">
      <table><thead><tr><th>Rentang harga</th><th class="r">Fraksi</th></tr></thead><tbody>${r.tick_table.map((x) => `<tr><td>${x.range}</td><td class="r">Rp${x.tick}</td></tr>`).join("")}</tbody></table>
      <table style="margin-top:8px"><thead><tr><th>Rentang harga</th><th class="r">ARA</th><th class="r">ARB</th></tr></thead><tbody>${r.auto_rejection.map((x) => `<tr><td>${x.range}</td><td class="r">${x.ara}</td><td class="r">${x.arb}</td></tr>`).join("")}</tbody></table>
      <p class="note">ARB asimetris berlaku s/d ${esc(r.arb_valid_until)} (update di config.yaml bila BEI mengubah). Lot ${r.lot_size} lembar · fee beli ${num(r.fee_buy * 100, 2)}% / jual ${num(r.fee_sell * 100, 2)}% · ${esc(r.settlement)} · ${esc(r.short_selling)}.</p>
      <p class="note">${esc(r.sessions)}</p></div></div>
    <div class="panel"><h3>Sumber Data & Update</h3><div class="pb"><dl class="kv">${Object.entries(d.meta.sources).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}
      ${d.meta.universe ? `<dt>Universe</dt><dd>${d.meta.universe.total} saham BEI · ${d.meta.universe.liquid} likuid (dinilai model)</dd><dt>Refresh harga</dt><dd>${esc(d.meta.universe.refresh || "")}</dd>` : ""}<dt>Dibuat</dt><dd>${esc(d.meta.generated_at)}</dd><dt>Versi</dt><dd>${esc(d.meta.version)}</dd><dt>Chart</dt><dd><a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts™</a></dd></dl>
      <p class="note">Update otomatis via GitHub Actions tiap ±30 menit saat jam bursa + final setelah penutupan. Halaman mengecek data baru tiap 5 menit.</p></div></div>
    <div class="panel"><h3>Shortcut</h3><div class="pb small"><dl class="kv"><dt>F1–F10 / 1–9, 0</dt><dd>pindah fungsi</dd><dt>/</dt><dd>fokus command line</dd><dt>BBCA &lt;Enter&gt;</dt><dd>buka saham (chart & rencana trade)</dd>
      <dt>BBCA DES</dt><dd>profil perusahaan</dd><dt>BBCA FA</dt><dd>fundamental & valuasi vs sektor</dd><dt>BBCA FS</dt><dd>ringkasan laporan keuangan (tahunan & kuartalan)</dd><dt>BBCA EE</dt><dd>proyeksi pendapatan, laba, EPS 3 tahun</dd><dt>BBCA DCF</dt><dd>perkiraan harga wajar (DCF, EV/EBITDA, PER, PBV)</dd><dt>BBCA CN</dt><dd>berita saham</dd><dt>BBCA GP</dt><dd>chart harga</dd>
      <dt>MAP</dt><dd>heatmap pasar</dd><dt>EQS</dt><dd>screener bebas (F10)</dd><dt>LP</dt><dd>layar multi-panel</dd><dt>WEI</dt><dd>pasar global: indeks, komoditas, kurs</dd>
      <dt>COMP BBCA BBRI TLKM</dt><dd>bandingkan saham: return, beta, korelasi</dd><dt>JRNL · BBCA JRNL</dt><dd>jurnal trading / catat beli BBCA</dd><dt>W</dt><dd>watchlist & alert</dd><dt>W ADD BBCA / W DEL BBCA</dt><dd>tambah / hapus watchlist</dd>
      <dt>PORT 50000000</dt><dd>set modal</dd><dt>FLOW · SIGNAL · NEWS · BTEST</dt><dd>buka fungsi</dd><dt>Esc</dt><dd>tutup detail</dd></dl>
      <p class="note">Gaya Bloomberg juga diterima: <b>BBCA &lt;Equity&gt; DES &lt;GO&gt;</b>. Watchlist & alert disimpan di browser ini saja; alert dicek saat halaman terbuka dan data baru masuk.</p></div></div>
    <div class="callout red">Bukan rekomendasi investasi. Model kuantitatif bisa salah, terutama saat rezim berubah, saham digoreng, atau ada aksi korporasi. Selalu cek ulang sebelum order dan pakai manajemen risiko.</div>
  </div></div>`;
}

/* ================= WATCHLIST & ALERT (disimpan di browser ini) ================= */
const watch = () => store.get("watch", []);
const isWatched = (t) => watch().includes(t);
function setWatch(t, on) { const w = watch().filter((x) => x !== t); if (on) w.push(t); store.set("watch", w); }
const alerts = () => store.get("alerts", []);
const ATYPE = { px_ge: "Harga ≥", px_le: "Harga ≤", sc_ge: "Skor komposit ≥", sc_le: "Skor komposit ≤", sig: "Sinyal berubah", ok: "Lolos semua syarat beli" };
const unseen = () => { const seen = store.get("aseen", 0); return store.get("alog", []).filter((x) => x.ts > seen).length; };
function evalAlerts() {
  const rules = alerts(); if (!rules.length || !S.d) return;
  const fired = [];
  rules.forEach((r) => {
    const s = stock(r.t); if (!s) return;
    let msg = null;
    if (r.type === "sig") { if (r.last && r.last !== s.signal) msg = `${r.t}: sinyal ${r.last} → ${s.signal}`; r.last = s.signal; }
    else {
      const c = r.type === "px_ge" ? s.last >= r.v : r.type === "px_le" ? s.last <= r.v : r.type === "sc_ge" ? s.scores.composite >= r.v
        : r.type === "sc_le" ? s.scores.composite <= r.v : (s.checks || []).length > 0 && failed(s).length === 0;
      if (c && r.state !== true) msg = `${r.t}: ${ATYPE[r.type]}${r.type === "ok" ? "" : " " + num(r.v)} — sekarang ${r.type.startsWith("px") ? num(s.last) : r.type === "ok" ? s.signal : "skor " + num(s.scores.composite)}`;
      r.state = c;
    }
    if (msg) fired.push(msg);
  });
  store.set("alerts", rules);
  if (!fired.length) return;
  const ts = Date.now();
  store.set("alog", fired.map((m) => ({ ts, m, at: S.d.meta.generated_at })).concat(store.get("alog", [])).slice(0, 60));
  toast("ALERT · " + fired[0] + (fired.length > 1 ? ` (+${fired.length - 1} lagi)` : ""));
  if ("Notification" in window && Notification.permission === "granted") { try { new Notification("IDX Quant Terminal", { body: fired.join("\n") }); } catch { /* tidak didukung */ } }
}
function addAlert() {
  const t = ($("#a-t").value || "").trim().toUpperCase(), type = $("#a-type").value, v = parseFloat(String($("#a-v").value).replace(/\./g, "").replace(",", "."));
  const s = stock(t);
  if (!s) { toast("Ticker tidak ditemukan: " + t); return; }
  const needV = type !== "sig" && type !== "ok";
  if (needV && !(v > 0)) { toast("Isi angka batasnya dulu"); return; }
  store.set("alerts", alerts().concat({ id: Date.now(), t, type, v: needV ? v : null, state: null, last: s.signal }));
  if (!isWatched(t)) setWatch(t, true);
  evalAlerts(); renderView(true);
}
function vWatch(root) {
  store.set("aseen", Date.now());
  $$("#nav .badge").forEach((b) => b.remove());
  const [sk, sd] = S.sort.watch;
  const key = (s) => ({ ticker: s.ticker, rank: SIGRANK[s.signal], chg: s.chg_pct, comp: s.scores.composite, flow: s.scores.flow, mom: s.scores.momentum, nf5: s.flow.nf5, pass: (s.checks || []).filter((c) => c.ok).length }[sk]);
  const rows = watch().map(stock).filter(Boolean).sort((a, b) => { const x = key(a), y = key(b); return (x > y ? 1 : x < y ? -1 : 0) * sd; });
  const th = (k, lab, r) => `<th class="${r ? "r" : ""}" data-sort="watch:${k}" style="cursor:pointer">${lab}${sk === k ? (sd > 0 ? " ▴" : " ▾") : ""}</th>`;
  const rules = alerts(), log = store.get("alog", []);
  const perm = "Notification" in window ? Notification.permission : "unsupported";
  root.innerHTML = `<div class="grid g21">
  <div class="panel"><h3>Watchlist <span class="fn">${rows.length} saham · tersimpan di browser ini · perintah: W ADD BBCA</span></h3><div class="pb">
    <div class="filters"><input id="w-add" list="tickers" placeholder="Kode saham" autocomplete="off" spellcheck="false" style="text-transform:uppercase"><button id="w-addbtn">+ Tambah</button></div>
    <div class="tw"><table><thead><tr><th></th>${th("ticker", "Ticker")}<th>Nama</th>${th("rank", "Sinyal")}${th("pass", "Syarat", 1)}<th class="r">Harga</th>${th("chg", "%", 1)}${th("comp", "Komposit")}${th("flow", "Flow", 1)}${th("mom", "Mom", 1)}${th("nf5", "Flow 5H", 1)}<th>Status flow</th><th class="r">Stop</th><th class="r">Alert</th></tr></thead>
    <tbody>${rows.map((s) => `<tr data-t="${s.ticker}"><td><button class="star on" data-star="${s.ticker}" title="Hapus dari watchlist">★</button></td><td class="tk">${s.ticker}</td><td class="mut">${esc(s.name.slice(0, 20))}</td><td>${sig(s.signal)}</td>${passCell(s)}
      <td class="r b">${num(s.last)}</td><td class="r ${cls(s.chg_pct)}">${pct(s.chg_pct)}</td><td style="width:110px">${scoreBar(s.scores.composite)}</td>
      <td class="r" style="color:${scoreColor(s.scores.flow)}">${num(s.scores.flow)}</td><td class="r" style="color:${scoreColor(s.scores.momentum)}">${num(s.scores.momentum)}</td>
      <td class="r ${cls(s.flow.nf5)}">${rp(s.flow.nf5)}</td><td class="${s.flow.status === "AKUMULASI" ? "up" : s.flow.status === "DISTRIBUSI" ? "down" : "mut"}">${s.flow.status}</td>
      <td class="r down">${num(s.levels.sl)}</td><td class="r">${rules.filter((r) => r.t === s.ticker).length || ""}</td></tr>`).join("")
      || `<tr><td colspan="14" class="mut">Watchlist masih kosong. Tambah lewat kotak di atas, tombol ☆ di halaman saham, atau perintah <b>W ADD BBCA</b>.</td></tr>`}</tbody></table></div>
  </div></div>
  <div class="stack">
    <div class="panel"><h3>Buat Alert</h3><div class="pb">
      <div class="form"><label>Saham<input id="a-t" list="tickers" autocomplete="off" spellcheck="false" style="text-transform:uppercase" value="${rows[0] ? rows[0].ticker : ""}"></label>
        <label>Kondisi<select id="a-type">${Object.entries(ATYPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
        <label>Batas (harga / skor)<input id="a-v" inputmode="decimal" placeholder="mis. 9500"></label></div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><button class="btn" id="a-addbtn">Simpan alert</button>
        ${perm === "default" ? `<button class="btn" id="a-notif">Aktifkan notifikasi browser</button>` : ""}</div>
      <p class="note">Alert dicek setiap data baru masuk (±30 menit saat jam bursa) <b>selama halaman ini terbuka</b>. Notifikasi browser: ${perm === "granted" ? "aktif" : perm === "denied" ? "diblokir di pengaturan browser" : perm === "unsupported" ? "tidak didukung perangkat ini" : "belum diaktifkan"}. Untuk alert saat halaman tertutup, pakai Telegram (lihat README).</p>
    </div></div>
    <div class="panel"><h3>Alert Aktif <span class="fn">${rules.length}</span></h3><div class="pb small">
      ${rules.map((r) => `<div class="arow"><b class="amb" data-t="${r.t}" style="cursor:pointer">${r.t}</b><span style="flex:1">${ATYPE[r.type]}${r.v != null ? " " + num(r.v) : ""}</span>
        <span class="${r.state ? "up" : "mut"}">${r.type === "sig" ? esc(r.last || "") : r.state ? "terpenuhi" : "menunggu"}</span><button data-adel="${r.id}" title="Hapus">✕</button></div>`).join("") || `<span class="mut">Belum ada alert.</span>`}
    </div></div>
    <div class="panel"><h3>Riwayat Alert <span class="fn">${log.length}</span></h3><div class="pb small">
      ${log.slice(0, 20).map((x) => `<div class="arow"><span class="mut">${esc((x.at || "").slice(5, 16).replace("T", " "))}</span><span style="flex:1">${esc(x.m)}</span></div>`).join("") || `<span class="mut">Belum ada alert yang terpicu.</span>`}
      ${log.length ? `<div style="margin-top:8px"><button class="btn" id="a-clear">Bersihkan riwayat</button></div>` : ""}
    </div></div>
  </div></div>`;
}

/* ================= F8 MAP (heatmap pasar) ================= */
function squarify(items, x, y, w, h) {
  const out = [], total = items.reduce((a, b) => a + b.v, 0);
  if (!total || w <= 0 || h <= 0) return out;
  const k = (w * h) / total, rest = items.map((i) => ({ i, a: i.v * k }));
  let row = [];
  const worst = (r, side) => { const s = r.reduce((a, b) => a + b.a, 0), mx = Math.max(...r.map((q) => q.a)), mn = Math.min(...r.map((q) => q.a)); return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn)); };
  const flush = () => {
    const s = row.reduce((a, b) => a + b.a, 0);
    if (w >= h) { const rw = s / h; let yy = y; row.forEach((r) => { const rh = r.a / rw; out.push({ i: r.i, x, y: yy, w: rw, h: rh }); yy += rh; }); x += rw; w -= rw; }
    else { const rh = s / w; let xx = x; row.forEach((r) => { const rw = r.a / rh; out.push({ i: r.i, x: xx, y, w: rw, h: rh }); xx += rw; }); y += rh; h -= rh; }
    row = [];
  };
  while (rest.length) {
    const side = Math.min(w, h);
    if (!row.length || worst(row.concat(rest[0]), side) <= worst(row, side)) row.push(rest.shift()); else flush();
  }
  if (row.length) flush();
  return out;
}
const heatCol = (t) => { t = Math.max(-1, Math.min(1, t || 0)); const a = Math.pow(Math.abs(t), 0.75), b = [40, 40, 40], to = t >= 0 ? [24, 150, 72] : [205, 46, 54];
  return `rgb(${b.map((v, i) => Math.round(v + (to[i] - v) * a)).join(",")})`; };
const MAPC = {
  chg: ["Hari ini", (s) => s.chg_pct, 0.04, (s) => pct(s.chg_pct)], w1: ["1 minggu", (s) => s.ind.ret5, 0.10, (s) => pct(s.ind.ret5)],
  m1: ["1 bulan", (s) => s.ind.ret21, 0.20, (s) => pct(s.ind.ret21, 0)], m3: ["3 bulan", (s) => s.ind.ret63, 0.40, (s) => pct(s.ind.ret63, 0)],
  flow: ["Flow 5H", (s) => (s.flow.avg_val20 ? s.flow.nf5 / (s.flow.avg_val20 * 5) : null), 0.25, (s) => rp(s.flow.nf5)],
  skor: ["Skor model", (s) => (s.scores.composite == null ? null : (s.scores.composite - 50) / 100), 0.30, (s) => num(s.scores.composite)],
};
function vMap(root) {
  const d = S.d, [clab, cval, cscale, ctext] = MAPC[S.mapColor];
  const items = (S.fund && S.fund.items) || {};
  if (S.mapSize === "cap" && !S.fund) loadFund().then(() => { if (S.view === "map" && S.fund) renderView(true); });
  const size = (s) => (S.mapSize === "cap" && S.fund ? (items[s.ticker] || {}).mcap : s.flow.avg_val20) || 0;
  let list = pool().filter((s) => size(s) > 0);
  if (list.length > 350) list = list.sort((a, b) => size(b) - size(a)).slice(0, 350);
  const up = list.filter((s) => s.chg_pct > 0).length, dn = list.filter((s) => s.chg_pct < 0).length;
  const H = Math.max(380, Math.min(window.innerHeight - 250, 900));
  root.innerHTML = `<div class="panel"><h3>Heatmap Pasar <span class="fn">ukuran kotak = ${S.mapSize === "cap" && S.fund ? "kapitalisasi pasar" : "nilai transaksi rata-rata 20 hari"} · klik kotak untuk buka saham</span></h3><div class="pb">
    <div class="filters">${scopeBar()}</div>
    <div class="filters"><span class="mut small">Warna</span>${Object.entries(MAPC).map(([k, v]) => `<button data-mapc="${k}" class="${S.mapColor === k ? "on" : ""}">${v[0]}</button>`).join("")}
      <span class="mut small" style="margin-left:10px">Ukuran</span><button data-maps="val" class="${S.mapSize === "val" ? "on" : ""}">Nilai transaksi</button><button data-maps="cap" class="${S.mapSize === "cap" ? "on" : ""}">Kapitalisasi</button>
      <span class="heatlg">${[-1, -0.66, -0.33, 0, 0.33, 0.66, 1].map((t) => `<i style="background:${heatCol(t)}">${S.mapColor === "skor" ? num(50 + t * cscale * 100) : S.mapColor === "flow" ? (t > 0 ? "+" : "") + num(t * cscale * 100) + "%" : pct(t * cscale, 0)}</i>`).join("")}</span></div>
    <div class="heat" id="heat" style="height:${H}px"></div>
    <div class="note">${list.length} saham · hari ini naik <span class="up">${up}</span> · turun <span class="down">${dn}</span> · tetap ${list.length - up - dn}.${S.mapColor === "flow" ? " Flow 5H = net flow 5 hari dibanding nilai transaksi normal 5 hari." : ""}${S.mapSize === "cap" && S.fund ? ` Kapitalisasi tersedia untuk ${list.length} saham (sumber: ${esc(S.fund.source || "Yahoo Finance")}).` : ""}</div>
  </div></div><div id="maptip" hidden></div>`;
  const el = $("#heat"), W = el.clientWidth;
  const secs = {};
  list.forEach((s) => { (secs[s.sector] = secs[s.sector] || []).push(s); });
  const secItems = Object.entries(secs).map(([name, arr]) => ({ name, arr, v: arr.reduce((a, s) => a + size(s), 0) })).sort((a, b) => b.v - a.v);
  let html = "";
  squarify(secItems, 0, 0, W, H).forEach((r) => {
    const hd = r.w > 70 && r.h > 34 ? 14 : 0;
    html += `<div class="sec" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px">${hd ? `<div class="sh">${esc(r.i.name)}</div>` : ""}`;
    const tiles = r.i.arr.map((s) => ({ s, v: size(s) })).sort((a, b) => b.v - a.v);
    squarify(tiles, 0, hd, r.w - 2, r.h - hd - 2).forEach((q) => {
      const s = q.i.s, v = cval(s), fs = Math.max(9, Math.min(22, Math.sqrt(q.w * q.h) / 5.2));
      html += `<div class="t" data-t="${s.ticker}" style="left:${q.x}px;top:${q.y}px;width:${q.w}px;height:${q.h}px;background:${v == null ? "#1c1c1c" : heatCol(v / cscale)};font-size:${fs}px">${q.w > 30 && q.h > 15 ? `<b>${s.ticker}</b>` : ""}${q.w > 44 && q.h > fs * 2.5 ? `<span>${ctext(s)}</span>` : ""}</div>`;
    });
    html += `</div>`;
  });
  el.innerHTML = html || `<span class="mut">Tidak ada saham yang cocok.</span>`;
  const tip = $("#maptip");
  el.addEventListener("mousemove", (e) => {
    const t = e.target.closest("[data-t]"); if (!t) { tip.hidden = true; return; }
    const s = stock(t.dataset.t), f = items[s.ticker];
    tip.innerHTML = `<b class="amb">${s.ticker}</b> ${esc(s.name)}<div class="mut">${esc(s.sector)}</div>
      <dl class="kv"><dt>Harga</dt><dd>${num(s.last)} <span class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</span></dd><dt>1 minggu / 1 bulan</dt><dd><span class="${cls(s.ind.ret5)}">${pct(s.ind.ret5)}</span> / <span class="${cls(s.ind.ret21)}">${pct(s.ind.ret21)}</span></dd>
      <dt>Nilai transaksi 20H</dt><dd>${rp(s.flow.avg_val20, false)}</dd><dt>Flow 5H</dt><dd class="${cls(s.flow.nf5)}">${rp(s.flow.nf5)}</dd>${f && f.mcap ? `<dt>Kapitalisasi</dt><dd>${big(f.mcap)}</dd>` : ""}
      <dt>Sinyal · komposit</dt><dd>${s.signal} · ${num(s.scores.composite)}</dd></dl>`;
    tip.hidden = false;
    const tw = tip.offsetWidth, thh = tip.offsetHeight;
    tip.style.left = Math.min(window.innerWidth - tw - 8, e.clientX + 14) + "px";
    tip.style.top = Math.min(window.innerHeight - thh - 8, e.clientY + 14) + "px";
  });
  el.addEventListener("mouseleave", () => { tip.hidden = true; });
}

/* ================= DES / FA / CN (tab di halaman saham) ================= */
/* Emiten yang melapor dalam USD: rasio per-saham dari Yahoo mencampur rupiah & dolar (PBV bisa ribuan kali).
   Hitung ulang PER, PBV, EPS, nilai buku dalam rupiah memakai kurs; tanpa kurs -> dikosongkan. */
function normFund(F) {
  Object.entries((F && F.items) || {}).forEach(([t, f]) => {
    if (f._n || !f.cur || f.cur === "IDR") return;
    f._n = 1;
    const m = f.cur === "USD" ? (S.d.market.macro || []).find((x) => x.name === "USDIDR") : null, fx = m && m.last > 1000 ? m.last : null, s = stock(t);
    f.pe = fx && f.mcap > 0 && f.ni > 0 ? f.mcap / (f.ni * fx) : null;
    f.bvps = fx && f.bvps > 0 ? f.bvps * fx : null;
    f.pbv = f.bvps && s && s.last > 0 ? s.last / f.bvps : null;
    f.eps = fx && f.ni != null && f.shares > 0 ? (f.ni * fx) / f.shares : null;
    f.ps = fx && f.mcap > 0 && f.rev > 0 ? f.mcap / (f.rev * fx) : null;
    f.fpe = null; f.ev_ebitda = null;
  });
  return F;
}
async function loadFund() {
  if (S.fund) return S.fund;
  if (!S.fundP) S.fundP = fetch(`data/fund.json?v=${encodeURIComponent(S.d.meta.generated_at.slice(0, 13))}`)
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(async (j) => (S.fund = normFund(j.enc ? await decryptEnv(j, S.key) : j)))
    .catch(() => { S.fundP = null; return { items: {}, n: 0, err: true }; });
  return S.fundP;
}
const big = (x, cur) => { if (x == null || isNaN(x)) return "–"; const a = Math.abs(x), p = !cur || cur === "IDR" ? "Rp" : cur + " ";
  return a >= 1e12 ? p + num(x / 1e12, 2) + " T" : a >= 1e9 ? p + num(x / 1e9, 1) + " M" : a >= 1e6 ? p + num(x / 1e6, 1) + " jt" : p + num(x); };
const xr = (v, d = 1) => (v == null || isNaN(v) ? "–" : v <= 0 ? "negatif" : num(v, d) + "x");
const pr = (v, d = 1) => (v == null || isNaN(v) ? "–" : NF(d).format(v * 100) + "%");
const dyield = (s, f) => { const y = f && f.dps && s.last ? f.dps / s.last : null; return y != null && y >= 0 && y < 0.5 ? y : null; };
const median = (a) => { const v = a.filter((x) => x != null && isFinite(x)).sort((x, y) => x - y); return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null; };
const noFund = (s) => `<div class="callout">Data fundamental belum tersedia untuk <b>${s.ticker}</b>. Sumbernya Yahoo Finance, hanya untuk saham dengan nilai transaksi ≥ Rp1 M/hari, diperbarui seminggu sekali — sebagian saham memang tidak punya datanya di Yahoo.</div>`;
const modelBox = (s) => `<div class="panel"><h3>Posisi di Model</h3><div class="pb"><dl class="kv small"><dt>Sinyal</dt><dd>${sig(s.signal)}</dd><dt>Skor komposit</dt><dd style="color:${scoreColor(s.scores.composite)}">${num(s.scores.composite)}</dd>
  <dt>Flow / Momentum / Trend</dt><dd>${num(s.scores.flow)} / ${num(s.scores.momentum)} / ${num(s.scores.trend)}</dd>${s.checks && s.checks.length ? `<dt>Syarat beli lolos</dt><dd>${s.checks.filter((c) => c.ok).length}/${s.checks.length}</dd>` : ""}
  <dt>Status flow</dt><dd class="${s.flow.status === "AKUMULASI" ? "up" : s.flow.status === "DISTRIBUSI" ? "down" : ""}">${s.flow.status}</dd></dl>
  <div class="note">Fundamental hanya informasi; sinyal model tetap dari momentum + akumulasi inflow.</div></div></div>`;
function tabDes(s, f) {
  const lo = s.ind.lo52, hi = s.ind.hi52, pos = hi > lo ? Math.max(0, Math.min(1, (s.last - lo) / (hi - lo))) : 0.5, y = dyield(s, f);
  const web = f && f.web && /^https?:\/\//.test(f.web) ? `<a href="${esc(f.web)}" target="_blank" rel="noopener">${esc(f.web.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))}</a>` : "–";
  return `<div class="grid g21"><div class="stack">
    <div class="panel"><h3>Profil Perusahaan <span class="fn">${f ? "sumber: " + esc((S.fund && S.fund.source) || "Yahoo Finance") + " · deskripsi dalam bahasa Inggris" : ""}</span></h3><div class="pb">
      ${f ? `<p style="margin:0 0 10px;line-height:1.55">${esc(f.desc || "Deskripsi tidak tersedia.")}</p>` : noFund(s)}
      <dl class="kv small"><dt>Sektor (IDX-IC)</dt><dd>${esc(s.sector)}</dd>${f ? `<dt>Industri</dt><dd>${esc(f.industry || "–")}</dd><dt>Kantor pusat</dt><dd>${esc(f.city || "–")}</dd><dt>Situs</dt><dd>${web}</dd><dt>Karyawan</dt><dd>${f.emp ? num(f.emp) : "–"}</dd>` : ""}</dl></div></div>
    <div class="panel"><h3>Harga & Perdagangan</h3><div class="pb">
      <div class="rng"><span>${num(lo)}</span><div class="trk"><i style="left:${pos * 100}%"></i></div><span>${num(hi)}</span></div>
      <div class="note" style="margin:2px 0 8px">Posisi harga ${num(s.last)} di rentang 52 minggu (${num(pos * 100)}% dari low ke high)</div>
      <dl class="kv small"><dt>Return 1M / 1B / 3B / 12B</dt><dd><span class="${cls(s.ind.ret5)}">${pct(s.ind.ret5)}</span> / <span class="${cls(s.ind.ret21)}">${pct(s.ind.ret21)}</span> / <span class="${cls(s.ind.ret63)}">${pct(s.ind.ret63)}</span> / <span class="${cls(s.ind.ret252)}">${pct(s.ind.ret252)}</span></dd>
        <dt>Nilai transaksi hari ini / rata-rata 20H</dt><dd>${rp(s.flow.value, false)} / ${rp(s.flow.avg_val20, false)}</dd><dt>ATR-14 (gerak harian wajar)</dt><dd>${num(s.levels.atr)} (${pr(s.levels.atr_pct)})</dd>
        <dt>MA20 / MA50 / MA200</dt><dd>${num(s.ind.ma20)} / ${num(s.ind.ma50)} / ${num(s.ind.ma200)}</dd>${f && f.beta != null ? `<dt>Beta</dt><dd>${num(f.beta, 2)}</dd>` : ""}</dl></div></div>
  </div><div class="stack">
    ${f ? `<div class="panel"><h3>Ringkasan</h3><div class="pb"><div class="tiles">
      <div class="tile"><div class="l">Kapitalisasi</div><div class="v">${big(f.mcap)}</div></div><div class="tile"><div class="l">PER</div><div class="v">${xr(f.pe)}</div></div>
      <div class="tile"><div class="l">PBV</div><div class="v">${xr(f.pbv, 2)}</div></div><div class="tile"><div class="l">ROE</div><div class="v">${pr(f.roe)}</div></div>
      <div class="tile"><div class="l">Dividend yield</div><div class="v">${pr(y)}</div></div><div class="tile"><div class="l">EPS</div><div class="v">${f.eps == null ? "–" : num(f.eps, Math.abs(f.eps) < 100 ? 1 : 0)}</div></div></div>
      <dl class="kv small" style="margin-top:8px"><dt>Saham beredar</dt><dd>${f.shares ? num(f.shares / 1e9, 2) + " miliar lembar" : "–"}</dd><dt>Free float</dt><dd>${f.float && f.shares ? pr(f.float / f.shares, 0) : "–"}</dd><dt>Data per</dt><dd>${esc(f.t || "–")}</dd></dl>
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" data-dtab="fa">Fundamental lengkap (FA)</button><button class="btn" data-dtab="val">Harga wajar (DCF)</button></div></div></div>` : ""}
    ${modelBox(s)}
  </div></div>`;
}
function tabFa(s, f) {
  if (!f) return `<div class="grid g21"><div class="stack">${noFund(s)}</div><div class="stack">${modelBox(s)}</div></div>`;
  const items = (S.fund && S.fund.items) || {}, cur = f.cur || "IDR", y = dyield(s, f);
  const yrs = f.years || [], mxR = Math.max(1, ...yrs.map((q) => Math.abs(q.rev || 0))), mxN = Math.max(1, ...yrs.map((q) => Math.abs(q.ni || 0)));
  const g = (a, b) => (a != null && b != null && b > 0 ? a / b - 1 : null);
  const peers = S.d.stocks.filter((x) => x.sector === s.sector && items[x.ticker]);
  const rv = [["PER", f.pe, (x) => (x.pe > 0 ? x.pe : null), xr, -1], ["PBV", f.pbv, (x) => (x.pbv > 0 ? x.pbv : null), (v) => xr(v, 2), -1], ["ROE", f.roe, (x) => x.roe, pr, 1],
    ["Margin laba bersih", f.npm, (x) => x.npm, pr, 1], ["Dividend yield", y, null, pr, 1]];
  const rvRow = ([lab, val, get, fmt, dir]) => {
    const vals = peers.map((x) => (get ? get(items[x.ticker]) : dyield(x, items[x.ticker]))).filter((v) => v != null && isFinite(v));
    const med = median(vals), ok = val != null && isFinite(val) && (dir > 0 || val > 0) && vals.length >= 3;
    const rank = ok ? vals.filter((v) => v < val).length / vals.length : null;
    const good = ok ? (dir > 0 ? rank : 1 - rank) : null;
    return `<tr><td>${lab}</td><td class="r b">${fmt(val)}</td><td class="r mut">${fmt(med)}</td><td style="width:44%;white-space:normal">${ok ? `<div class="rvb"><i style="left:${rank * 100}%"></i></div>` : ""}
      <div class="small ${good == null ? "mut" : good >= 0.66 ? "up" : good <= 0.33 ? "down" : "mut"}" style="margin-top:6px">${!ok ? "–" : dir < 0 ? (rank <= 0.5 ? `lebih murah dari ${num((1 - rank) * 100)}% saham sektor` : `lebih mahal dari ${num(rank * 100)}% saham sektor`) : (rank >= 0.5 ? `lebih tinggi dari ${num(rank * 100)}% saham sektor` : `lebih rendah dari ${num((1 - rank) * 100)}% saham sektor`)}</div></td></tr>`;
  };
  const top = peers.slice().sort((a, b) => (items[b.ticker].mcap || 0) - (items[a.ticker].mcap || 0)).slice(0, 12);
  if (!top.some((x) => x.ticker === s.ticker)) top.push(s);
  return `<div class="grid g21"><div class="stack">
    <div class="panel"><h3>Laba Rugi Tahunan <span class="fn">${cur === "IDR" ? "rupiah" : "mata uang laporan: " + esc(cur)} · sumber: ${esc((S.fund && S.fund.source) || "Yahoo Finance")}</span></h3><div class="pb">
      ${yrs.length ? `<div class="tw"><table><thead><tr><th>Tahun</th><th class="r">Pendapatan</th><th style="width:16%"></th><th class="r">YoY</th><th class="r">Laba bersih</th><th style="width:16%"></th><th class="r">YoY</th><th class="r">Margin</th></tr></thead><tbody>
        ${yrs.map((q, i) => { const p = yrs[i - 1] || {}, gr = g(q.rev, p.rev), gn = g(q.ni, p.ni); return `<tr><td class="b">${q.y}</td><td class="r">${big(q.rev, cur)}</td><td><div class="ybar"><i style="width:${Math.abs(q.rev || 0) / mxR * 100}%;background:${COL.s2}"></i></div></td><td class="r ${cls(gr)}">${gr == null ? "–" : pct(gr, 0)}</td>
          <td class="r ${q.ni < 0 ? "down" : ""}">${big(q.ni, cur)}</td><td><div class="ybar"><i style="width:${Math.abs(q.ni || 0) / mxN * 100}%;background:${q.ni < 0 ? COL.down : COL.up}"></i></div></td><td class="r ${cls(gn)}">${gn == null ? "–" : pct(gn, 0)}</td><td class="r">${q.rev > 0 && q.ni != null ? pr(q.ni / q.rev) : "–"}</td></tr>`; }).join("")}</tbody></table></div>`
        : `<span class="mut">Laporan tahunan tidak tersedia di Yahoo untuk saham ini.</span>`}</div></div>
    <div class="grid g2">
      <div class="panel"><h3>Valuasi</h3><div class="pb"><dl class="kv small"><dt>Kapitalisasi pasar</dt><dd>${big(f.mcap)}</dd><dt>PER (12 bln terakhir)</dt><dd>${xr(f.pe)}</dd><dt>PER proyeksi</dt><dd>${xr(f.fpe)}</dd><dt>PBV</dt><dd>${xr(f.pbv, 2)}</dd>
        <dt>Harga / penjualan</dt><dd>${xr(f.ps, 2)}</dd><dt>EV / EBITDA</dt><dd>${xr(evEbitda(f) || f.ev_ebitda)}</dd><dt>EPS / nilai buku per saham</dt><dd>${f.eps == null ? "–" : num(f.eps, 1)} / ${f.bvps == null ? "–" : num(f.bvps, 1)}</dd></dl></div></div>
      <div class="panel"><h3>Profitabilitas</h3><div class="pb"><dl class="kv small"><dt>ROE</dt><dd>${pr(f.roe)}</dd><dt>ROA</dt><dd>${pr(f.roa)}</dd><dt>Margin kotor</dt><dd>${pr(f.gpm)}</dd><dt>Margin operasi</dt><dd>${pr(f.opm)}</dd><dt>Margin laba bersih</dt><dd>${pr(f.npm)}</dd>
        <dt>Pendapatan 12 bln</dt><dd>${big(f.rev, cur)}</dd><dt>Laba bersih 12 bln</dt><dd>${big(f.ni, cur)}</dd></dl></div></div>
      <div class="panel"><h3>Pertumbuhan & Neraca</h3><div class="pb"><dl class="kv small"><dt>Pertumbuhan pendapatan (YoY)</dt><dd class="${cls(f.rev_g)}">${f.rev_g == null ? "–" : pct(f.rev_g)}</dd><dt>Pertumbuhan laba (YoY)</dt><dd class="${cls(f.eps_g)}">${f.eps_g == null ? "–" : pct(f.eps_g)}</dd>
        <dt>Utang / ekuitas (DER)</dt><dd>${xr(f.der, 2)}</dd><dt>Rasio lancar</dt><dd>${xr(f.cr, 2)}</dd><dt>Beta</dt><dd>${f.beta == null ? "–" : num(f.beta, 2)}</dd></dl></div></div>
      <div class="panel"><h3>Dividen</h3><div class="pb"><dl class="kv small"><dt>Dividen per saham (setahun)</dt><dd>${f.dps ? "Rp" + num(f.dps, f.dps < 100 ? 1 : 0) : "–"}</dd><dt>Dividend yield</dt><dd>${pr(y)}</dd><dt>Payout ratio</dt><dd>${f.payout != null && f.payout >= 0 && f.payout < 3 ? pr(f.payout, 0) : "–"}</dd><dt>Ex-date terakhir</dt><dd>${esc(f.exdiv || "–")}</dd></dl></div></div>
    </div>
  </div><div class="stack">
    <div class="panel"><h3>Valuasi Relatif <span class="fn">vs ${peers.length} saham ${esc(s.sector)}</span></h3><div class="pb">
      <div class="tw"><table><thead><tr><th>Metrik</th><th class="r">${s.ticker}</th><th class="r">Median</th><th>Posisi di sektor</th></tr></thead><tbody>${rv.map(rvRow).join("")}</tbody></table></div>
      <div class="note">Titik = posisi ${s.ticker} di antara saham sektornya (kiri = paling rendah, garis tengah = median). Murah belum tentu bagus: bandingkan dengan ROE dan pertumbuhannya.</div></div></div>
    <div class="panel"><h3>Pembanding Sektor <span class="fn">12 kapitalisasi terbesar</span></h3><div class="pb"><div class="tw"><table><thead><tr><th>Ticker</th><th class="r">Kap.</th><th class="r">PER</th><th class="r">PBV</th><th class="r">ROE</th><th class="r">Yield</th><th class="r">Skor</th></tr></thead><tbody>
      ${top.map((x) => { const q = items[x.ticker] || {}; return `<tr data-t="${x.ticker}" class="${x.ticker === s.ticker ? "hl" : ""}"><td class="tk">${x.ticker}</td><td class="r">${big(q.mcap).replace("Rp", "")}</td><td class="r">${xr(q.pe)}</td><td class="r">${xr(q.pbv, 2)}</td><td class="r">${pr(q.roe)}</td><td class="r">${pr(dyield(x, q))}</td><td class="r" style="color:${scoreColor(x.scores.composite)}">${num(x.scores.composite)}</td></tr>`; }).join("")}</tbody></table></div></div></div>
    ${modelBox(s)}
  </div></div>`;
}
function tabCn(s) {
  const news = S.d.news.filter((x) => x.tickers.includes(s.ticker));
  return `<div class="grid g21"><div class="panel"><h3>Berita ${s.ticker} <span class="fn">${news.length} berita · 14 hari terakhir</span></h3><div class="pb">${news.slice(0, 40).map(newsItem).join("") || `<span class="mut">Tidak ada berita yang menyebut ${s.ticker} dalam 14 hari terakhir.</span>`}</div></div>
    <div class="stack"><div class="panel"><h3>Sentimen</h3><div class="pb"><dl class="kv small"><dt>Skor sentimen (0–100)</dt><dd style="color:${scoreColor(s.scores.sentiment)}">${num(s.scores.sentiment)}</dd><dt>Jumlah berita</dt><dd>${s.sent.n || 0}</dd><dt>Positif / negatif</dt><dd><span class="up">${s.sent.pos || 0}</span> / <span class="down">${s.sent.neg || 0}</span></dd></dl>
      <div class="note">Sentimen dinilai otomatis dari judul berita (${esc(S.d.sentiment.method || "leksikon")}); bobotnya ${Math.round((S.d.config.weights.sentiment || 0) * 100)}% di skor komposit.</div></div></div>${modelBox(s)}</div></div>`;
}

/* ================= DCF / VALUASI HARGA WAJAR (tab di halaman saham) ================= */
const quant = (a, q) => { const v = a.filter((x) => x != null && isFinite(x)).sort((x, y) => x - y); if (!v.length) return null; const i = (v.length - 1) * q, lo = Math.floor(i); return v[lo] + (v[Math.min(v.length - 1, lo + 1)] - v[lo]) * (i - lo); };
const fxOf = (cur) => { if (!cur || cur === "IDR") return 1; if (cur !== "USD") return null; const m = (S.d.market.macro || []).find((x) => x.name === "USDIDR"); return m && m.last > 1000 ? m.last : null; };
const netDebt = (f) => { const fx = fxOf(f.cur); return fx == null || (f.debt == null && f.cash == null) ? null : ((f.debt || 0) - (f.cash || 0)) * fx; };          // rupiah
const evEbitda = (f) => { const fx = fxOf(f.cur), nd = netDebt(f); return fx && nd != null && f.mcap > 0 && f.ebitda > 0 ? (f.mcap + nd) / (f.ebitda * fx) : null; };
function valAssump(s, f) {
  const g0 = store.get("val", {}), per = store.get("valg", {});
  const ys = (f.years || []).filter((q) => q.rev > 0);
  let g = 0.08;
  if (ys.length >= 2) { const n = ys[ys.length - 1].y - ys[0].y; if (n > 0) g = Math.pow(ys[ys.length - 1].rev / ys[0].rev, 1 / n) - 1; }
  g = Math.max(0.02, Math.min(0.15, g));
  return { w: g0.w ?? 0.11, tg: g0.tg ?? 0.04, coe: g0.coe ?? 0.13, g: per[s.ticker] ?? Math.round(g * 100) / 100, gAuto: per[s.ticker] == null };
}
function valuation(s, f, a) {
  const items = (S.fund && S.fund.items) || {}, peers = S.d.stocks.filter((x) => x.sector === s.sector && items[x.ticker]).map((x) => items[x.ticker]);
  const fin = s.sector === "Financials", fx = fxOf(f.cur), nd = netDebt(f), sh = f.shares, px = s.last, out = [];
  // --- DCF: arus kas bebas 5 tahun + nilai terminal, dikurangi utang bersih
  const hist = (f.years || []).map((q) => q.fcf).filter((v) => v != null).slice(-3);
  const base = hist.length ? hist.reduce((x, y) => x + y, 0) / hist.length : f.fcf;
  const dcf = (w, g, tg) => { if (w - tg < 0.02) return null; let c = base * fx, pv = 0; const rows = [];
    for (let i = 1; i <= 5; i++) { c *= 1 + g; const p = c / Math.pow(1 + w, i); pv += p; rows.push({ i, c, p }); }
    const tv = (c * (1 + tg)) / (w - tg), ptv = tv / Math.pow(1 + w, 5);
    return { rows, tv, ptv, ev: pv + ptv, eq: pv + ptv - (nd || 0), v: (pv + ptv - (nd || 0)) / sh }; };
  let dcfD = null, dcfWhy = null;
  if (fin) dcfWhy = "tidak cocok untuk bank & keuangan (arus kas dan utangnya bagian dari bisnis)";
  else if (fx == null) dcfWhy = "mata uang laporan " + f.cur + " belum didukung";
  else if (!sh) dcfWhy = "jumlah saham tidak tersedia";
  else if (base == null) dcfWhy = "data arus kas bebas tidak tersedia";
  else if (base <= 0) dcfWhy = "arus kas bebas rata-rata negatif, DCF tidak bermakna";
  else { dcfD = dcf(a.w, a.g, a.tg); const lo = dcf(a.w + 0.01, Math.max(0, a.g - 0.02), a.tg), hi = dcf(a.w - 0.01, a.g + 0.02, a.tg);
    if (dcfD) out.push({ k: "dcf", lab: "DCF (arus kas bebas)", mid: dcfD.v, lo: lo ? lo.v : dcfD.v, hi: hi ? hi.v : dcfD.v, note: `WACC ${pr(a.w)} · tumbuh ${pr(a.g)} · terminal ${pr(a.tg)}; rentang = WACC ±1%, tumbuh ±2%` }); }
  // --- kelipatan sektor: median, rentang = kuartil 25–75
  const mult = (k, lab, own, vals, fair, unit, cap) => {
    const v = vals.filter((x) => x != null && isFinite(x) && x > 0 && x <= cap);
    if (!(own > 0) || v.length < 4) return;
    const q = [quant(v, 0.25), quant(v, 0.5), quant(v, 0.75)].map(fair);
    out.push({ k, lab, mid: q[1], lo: Math.min(q[0], q[2]), hi: Math.max(q[0], q[2]), note: `${unit} ${s.ticker} ${xr(own, 2)} · median sektor ${xr(quant(v, 0.5), 2)} (${v.length} saham)` });
  };
  if (!fin && fx && sh && nd != null) mult("ev", "EV/EBITDA sektor", evEbitda(f), peers.map(evEbitda), (m) => (m * f.ebitda * fx - nd) / sh, "EV/EBITDA", 60);
  mult("per", "PER sektor", f.pe, peers.map((x) => x.pe), (m) => (px * m) / f.pe, "PER", 100);
  mult("pbv", "PBV sektor", f.pbv, peers.map((x) => x.pbv), (m) => (px * m) / f.pbv, "PBV", 30);
  // --- PBV wajar dari ROE (Gordon): PBV* = (ROE − g) / (biaya ekuitas − g)
  if (f.pbv > 0 && f.roe != null && f.roe > a.tg && a.coe - a.tg >= 0.02) {
    const j = (r) => (px * ((f.roe - a.tg) / (r - a.tg))) / f.pbv;
    out.push({ k: "roe", lab: "PBV wajar dari ROE", mid: j(a.coe), lo: j(a.coe + 0.01), hi: a.coe - 0.01 - a.tg >= 0.02 ? j(a.coe - 0.01) : j(a.coe), note: `ROE ${pr(f.roe)} · biaya ekuitas ${pr(a.coe)} · tumbuh ${pr(a.tg)} → PBV wajar ${xr((f.roe - a.tg) / (a.coe - a.tg), 2)}` });
  }
  const mids = out.map((m) => m.mid).filter((v) => v > 0);
  return { out, fair: mids.length ? median(mids) : null, dcfD, dcfWhy, base, fx, nd, fin, dcf: dcfD ? dcf : null };
}
function tabVal(s, f) {
  if (!f) return `<div class="grid g21"><div class="stack">${noFund(s)}</div><div class="stack">${modelBox(s)}</div></div>`;
  const a = valAssump(s, f), V = valuation(s, f, a), px = s.last, cur = f.cur || "IDR";
  const up = V.fair ? V.fair / px - 1 : null;
  const all = V.out.flatMap((m) => [m.lo, m.hi, m.mid]).concat(px).filter((v) => v > 0);
  const mn = Math.min(...all) * 0.85, mx = Math.max(...all) * 1.08, pos = (v) => Math.max(0, Math.min(100, ((Math.max(v, mn) - mn) / (mx - mn)) * 100));
  const verdict = up == null ? ["mut", "Belum bisa dihitung"] : up > 0.2 ? ["up", "Harga di bawah perkiraan wajar"] : up < -0.2 ? ["down", "Harga di atas perkiraan wajar"] : ["amb", "Harga di sekitar perkiraan wajar"];
  const D = V.dcfD;
  const sens = D ? [-0.02, -0.01, 0, 0.01, 0.02].map((dw) => [a.w + dw, [-0.01, 0, 0.01].map((dt) => { const r = V.dcf(a.w + dw, a.g, a.tg + dt); return r ? r.v : null; })]) : [];
  const inp = (id, lab, v) => `<label>${lab}<input id="v-${id}" type="number" step="0.5" min="0" max="40" value="${Math.round(v * 1000) / 10}"></label>`;
  return `<div class="grid g21"><div class="stack">
    <div class="panel"><h3>Perkiraan Harga Wajar <span class="fn">per saham, rupiah · bukan target harga</span></h3><div class="pb">
      <div class="tiles" style="margin-bottom:10px">
        <div class="tile"><div class="l">Harga sekarang</div><div class="v">${num(px)}</div></div>
        <div class="tile"><div class="l">Perkiraan wajar (median ${V.out.length} metode)</div><div class="v amb">${V.fair ? num(V.fair) : "–"}</div></div>
        <div class="tile"><div class="l">Selisih ke harga wajar</div><div class="v ${cls(up)}">${up == null ? "–" : pct(up, 0)}</div></div>
        <div class="tile"><div class="l">Kesimpulan kasar</div><div class="v ${verdict[0]}" style="font-size:12px;line-height:1.3">${verdict[1]}</div></div></div>
      ${V.out.length ? `<div class="ff">${V.out.map((m) => `<div class="ffr"><span class="ffl">${m.lab}</span>
        <div class="fft"><i class="bar" style="left:${pos(m.lo)}%;width:${Math.max(0.6, pos(m.hi) - pos(m.lo))}%"></i>${m.mid > 0 ? `<i class="mid" style="left:${pos(m.mid)}%"></i>` : ""}<i class="px" style="left:${pos(px)}%"></i></div>
        <span class="ffv"><b>${m.mid > 0 ? num(m.mid) : "negatif"}</b> <span class="mut">${num(Math.max(0, m.lo))}–${num(Math.max(0, m.hi))}</span></span>
        <span class="ffu ${cls(m.mid / px - 1)}">${m.mid > 0 ? pct(m.mid / px - 1, 0) : ""}</span></div>
        <div class="ffn">${esc(m.note)}</div>`).join("")}
        <div class="ffr"><span class="ffl"></span><div class="ffk"><span><i class="px"></i> harga sekarang ${num(px)}</span><span><i class="mid"></i> nilai tengah</span><span><i class="bar"></i> rentang</span></div></div></div>`
        : `<div class="callout">Tidak ada metode yang bisa dihitung untuk ${s.ticker} (data laba, arus kas, atau pembanding sektor tidak cukup).</div>`}
      ${V.dcfWhy ? `<div class="note">DCF tidak dihitung: ${esc(V.dcfWhy)}.</div>` : ""}
    </div></div>
    ${D ? `<div class="panel"><h3>Rincian DCF <span class="fn">arus kas bebas awal = rata-rata ${Math.min(3, (f.years || []).filter((q) => q.fcf != null).length) || 1} tahun terakhir: ${big(V.base, cur)}${cur !== "IDR" ? " · kurs " + num(V.fx) : ""}</span></h3><div class="pb">
      <div class="tw"><table><thead><tr><th>Tahun ke</th>${D.rows.map((r) => `<th class="r">${r.i}</th>`).join("")}<th class="r">Terminal</th></tr></thead><tbody>
        <tr><td>Arus kas bebas</td>${D.rows.map((r) => `<td class="r">${big(r.c).replace("Rp", "")}</td>`).join("")}<td class="r">${big(D.tv).replace("Rp", "")}</td></tr>
        <tr><td>Nilai sekarang</td>${D.rows.map((r) => `<td class="r">${big(r.p).replace("Rp", "")}</td>`).join("")}<td class="r">${big(D.ptv).replace("Rp", "")}</td></tr></tbody></table></div>
      <dl class="kv small" style="margin-top:8px"><dt>Nilai perusahaan (EV)</dt><dd>${big(D.ev)}</dd><dt>Utang bersih (utang − kas)</dt><dd>${V.nd == null ? "tidak tersedia, dianggap 0" : big(V.nd)}</dd><dt>Nilai ekuitas</dt><dd>${big(D.eq)}</dd>
        <dt>Jumlah saham</dt><dd>${num(f.shares / 1e9, 2)} miliar</dd><dt>Harga wajar DCF per saham</dt><dd class="amb b">${D.v > 0 ? num(D.v) : "negatif"}</dd><dt>Porsi nilai terminal</dt><dd>${pr(D.ptv / D.ev, 0)} dari EV</dd></dl>
      <h4 style="margin:12px 0 4px">Sensitivitas harga wajar DCF</h4>
      <div class="tw"><table><thead><tr><th>WACC \\ tumbuh terminal</th>${[-0.01, 0, 0.01].map((dt) => `<th class="r">${pr(a.tg + dt)}</th>`).join("")}</tr></thead><tbody>
        ${sens.map(([w, vs]) => `<tr class="${Math.abs(w - a.w) < 1e-9 ? "hl" : ""}"><td>${pr(w)}</td>${vs.map((v) => `<td class="r ${v == null ? "mut" : cls(v / px - 1)}">${v == null ? "–" : v > 0 ? num(v) : "negatif"}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="note">Hijau = di atas harga sekarang, merah = di bawah. Kalau hasilnya berubah jauh hanya karena WACC bergeser 1%, anggap angka DCF-nya kasar.</div>
    </div></div>` : ""}
  </div><div class="stack">
    <div class="panel"><h3>Asumsi <span class="fn">ubah lalu tekan Enter</span></h3><div class="pb">
      <div class="form">${inp("w", "WACC / tingkat diskonto (%)", a.w)}${inp("g", `Pertumbuhan 5 tahun (%)${a.gAuto ? " · otomatis" : ""}`, a.g)}${inp("tg", "Pertumbuhan terminal (%)", a.tg)}${inp("coe", "Biaya ekuitas, untuk PBV-ROE (%)", a.coe)}</div>
      <div style="margin-top:10px"><button class="btn" id="v-reset">Kembalikan ke bawaan</button></div>
      <p class="note">Bawaan: WACC 11%, terminal 4%, biaya ekuitas 13%. Pertumbuhan 5 tahun diambil dari rata-rata pertumbuhan pendapatan historis (dibatasi 2–15%). WACC, terminal, dan biaya ekuitas berlaku untuk semua saham; pertumbuhan disimpan per saham, di browser ini.</p></div></div>
    <div class="panel"><h3>Data yang Dipakai <span class="fn">${esc((S.fund && S.fund.source) || "Yahoo Finance")}${cur !== "IDR" ? " · laporan dalam " + esc(cur) : ""}</span></h3><div class="pb"><dl class="kv small">
      <dt>Arus kas bebas 12 bln</dt><dd>${big(f.fcf, cur)}</dd><dt>Arus kas bebas per tahun</dt><dd>${(f.years || []).filter((q) => q.fcf != null).map((q) => `${String(q.y).slice(2)}: ${big(q.fcf, cur).replace(/^Rp|^[A-Z]{3} /, "")}`).join(" · ") || "–"}</dd>
      <dt>EBITDA 12 bln</dt><dd>${big(f.ebitda, cur)}</dd><dt>Utang / kas</dt><dd>${big(f.debt, cur)} / ${big(f.cash, cur)}</dd><dt>EV/EBITDA sekarang</dt><dd>${xr(evEbitda(f))}</dd><dt>PER / PBV sekarang</dt><dd>${xr(f.pe)} / ${xr(f.pbv, 2)}</dd><dt>ROE</dt><dd>${pr(f.roe)}</dd><dt>Data per</dt><dd>${esc(f.t || "–")}</dd></dl></div></div>
    <div class="callout">Ini hitungan otomatis dari data Yahoo dengan asumsi seragam, bukan riset emiten. Hasilnya sangat peka terhadap asumsi, data bisa salah atau telat, dan "murah" bisa berarti pasar melihat masalah yang tidak tertangkap angka. Pakai sebagai pembanding, bukan sinyal beli; sinyal model tetap dari momentum + akumulasi inflow.</div>
    ${modelBox(s)}
  </div></div>`;
}

/* ================= F10 EQS (screener bebas) ================= */
const fnd = (s) => ((S.fund && S.fund.items) || {})[s.ticker];
const pos0 = (v) => (v != null && isFinite(v) && v > 0 ? v : null);
const upCache = { key: null, m: {} };
function upside(s) {                     // selisih ke perkiraan harga wajar (%), dari tab DCF
  const key = S.d.meta.generated_at + "|" + JSON.stringify(store.get("val", {}));
  if (upCache.key !== key) { upCache.key = key; upCache.m = {}; }
  if (!(s.ticker in upCache.m)) { const f = fnd(s); let v = null; if (f) { try { const V = valuation(s, f, valAssump(s, f)); v = V.fair ? (V.fair / s.last - 1) * 100 : null; } catch { v = null; } } upCache.m[s.ticker] = v; }
  return upCache.m[s.ticker];
}
const SF = {   // kunci: [label, kelompok, ambil nilai, satuan, desimal]
  comp: ["Skor komposit", "Model", (s) => s.scores.composite, "", 0], flow: ["Skor flow (akumulasi)", "Model", (s) => s.scores.flow, "", 0],
  mom: ["Skor momentum", "Model", (s) => s.scores.momentum, "", 0], trend: ["Skor trend", "Model", (s) => s.scores.trend, "", 0],
  sent: ["Skor sentimen", "Model", (s) => s.scores.sentiment, "", 0], pass: ["Syarat beli lolos (jumlah)", "Model", (s) => (s.checks && s.checks.length ? s.checks.filter((c) => c.ok).length : null), "", 0],
  px: ["Harga", "Harga", (s) => s.last, "", 0], chg: ["Perubahan hari ini", "Harga", (s) => s.chg_pct * 100, "%", 1],
  r5: ["Return 1 minggu", "Harga", (s) => s.ind.ret5 * 100, "%", 1], r21: ["Return 1 bulan", "Harga", (s) => s.ind.ret21 * 100, "%", 1],
  r63: ["Return 3 bulan", "Harga", (s) => s.ind.ret63 * 100, "%", 0], r252: ["Return 12 bulan", "Harga", (s) => s.ind.ret252 * 100, "%", 0],
  hi52: ["Jarak dari high 52 mgg", "Harga", (s) => (s.ind.hi52 ? (s.last / s.ind.hi52 - 1) * 100 : null), "%", 0],
  ma50: ["Harga vs MA50", "Harga", (s) => (s.ind.ma50 ? (s.last / s.ind.ma50 - 1) * 100 : null), "%", 1], ma200: ["Harga vs MA200", "Harga", (s) => (s.ind.ma200 ? (s.last / s.ind.ma200 - 1) * 100 : null), "%", 1],
  rsi: ["RSI-14", "Harga", (s) => s.ind.rsi, "", 0], atr: ["ATR harian", "Harga", (s) => s.levels.atr_pct * 100, "%", 1],
  val: ["Nilai transaksi 20H", "Flow", (s) => s.flow.avg_val20, " M", 1], volr: ["Lonjakan volume", "Flow", (s) => s.flow.volratio, "x", 1],
  nf5: ["Net flow 5H", "Flow", (s) => s.flow.nf5, " M", 1], nf20: ["Net flow 20H", "Flow", (s) => s.flow.nf20, " M", 1], nf60: ["Net flow 60H", "Flow", (s) => s.flow.nf60, " M", 1],
  acc: ["Hari inflow (60H)", "Flow", (s) => (s.flow.accdays == null ? null : s.flow.accdays * 100), "%", 0], cmf: ["CMF-20", "Flow", (s) => s.flow.cmf, "", 2], mfi: ["MFI-14", "Flow", (s) => s.flow.mfi, "", 0],
  mcap: ["Kapitalisasi", "Fundamental", (s) => { const f = fnd(s); return f && f.mcap ? f.mcap / 1e12 : null; }, " T", 1],
  pe: ["PER", "Fundamental", (s) => pos0((fnd(s) || {}).pe), "x", 1], pbv: ["PBV", "Fundamental", (s) => pos0((fnd(s) || {}).pbv), "x", 2],
  eve: ["EV/EBITDA", "Fundamental", (s) => { const f = fnd(s); return f ? evEbitda(f) : null; }, "x", 1],
  roe: ["ROE", "Fundamental", (s) => { const f = fnd(s); return f && f.roe != null ? f.roe * 100 : null; }, "%", 1], npm: ["Margin laba bersih", "Fundamental", (s) => { const f = fnd(s); return f && f.npm != null ? f.npm * 100 : null; }, "%", 1],
  dy: ["Dividend yield", "Fundamental", (s) => { const y = dyield(s, fnd(s)); return y == null ? null : y * 100; }, "%", 1], der: ["Utang / ekuitas", "Fundamental", (s) => (fnd(s) || {}).der, "x", 2],
  revg: ["Pertumbuhan pendapatan", "Fundamental", (s) => { const f = fnd(s); return f && f.rev_g != null ? f.rev_g * 100 : null; }, "%", 0],
  up: ["Selisih ke harga wajar", "Fundamental", upside, "%", 0],
};
const sfFmt = (k, v) => (v == null || !isFinite(v) ? "–" : (SF[k][3] === "%" && v > 0 && !["acc", "roe", "npm", "dy", "atr"].includes(k) ? "+" : "") + num(v, SF[k][4]) + SF[k][3]);
const SFS = { chg: "%", comp: "Komposit", flow: "Flow", mom: "Mom", trend: "Trend", sent: "Sent", pass: "Syarat", r5: "1M", r21: "1B", r63: "3B", r252: "12B", hi52: "vs High", ma50: "vs MA50", ma200: "vs MA200",
  rsi: "RSI", atr: "ATR", val: "Nilai 20H", volr: "Volume", nf5: "Flow 5H", nf20: "Flow 20H", nf60: "Flow 60H", acc: "Hari inflow", cmf: "CMF", mfi: "MFI", mcap: "Kap.", pe: "PER", pbv: "PBV", eve: "EV/EBITDA",
  roe: "ROE", npm: "Margin", dy: "Yield", der: "DER", revg: "Tumbuh", up: "vs Wajar" };   // judul kolom pendek
const SIGNED = ["chg", "r5", "r21", "r63", "r252", "hi52", "ma50", "ma200", "nf5", "nf20", "nf60", "cmf", "revg", "up"];
const SCR_PRE = [
  ["Kandidat model", "Momentum papan atas + inflow akumulasi kuat (syarat inti model)", [["mom", ">=", 70], ["flow", ">=", 60]]],
  ["Akumulasi sebelum harga naik", "Inflow kuat dan bertahan, tapi harga sebulan terakhir belum lari", [["flow", ">=", 70], ["acc", ">=", 55], ["r21", "<=", 5]]],
  ["Murah & berkualitas", "PER rendah, ROE tinggi, utang wajar", [["pe", "<=", 12], ["roe", ">=", 15], ["der", "<=", 1]]],
  ["Dividen tinggi", "Yield besar dari perusahaan yang masih untung", [["dy", ">=", 5], ["roe", ">=", 10]]],
  ["Dekat high 52 minggu + volume", "Maksimal 5% di bawah high setahun dengan volume membesar", [["hi52", ">=", -5], ["volr", ">=", 1.5]]],
  ["Di bawah harga wajar + momentum", "Lebih murah dari perkiraan wajar dan momentumnya sudah di atas rata-rata", [["up", ">=", 20], ["mom", ">=", 60]]],
  ["Oversold di uptrend", "RSI rendah padahal harga masih di atas MA200", [["rsi", "<=", 35], ["ma200", ">=", 0]]],
];
const scrCfg = () => Object.assign({ rules: SCR_PRE[0][2].map(([f, op, v]) => ({ f, op, v })), sec: "ALL", sig: "ALL", st: "ALL", name: SCR_PRE[0][0] }, store.get("scr", {}));
const scrSet = (c) => store.set("scr", c);
function scrRows() {
  const c = scrCfg(), rules = c.rules.filter((r) => SF[r.f] && r.v !== "" && r.v != null && isFinite(r.v));
  return pool().filter((s) => (c.sec === "ALL" || s.sector === c.sec) && (c.st === "ALL" || s.flow.status === c.st)
    && (c.sig === "ALL" || (c.sig === "BUYS" ? s.signal === "BUY" || s.signal === "STRONG BUY" : c.sig === "HELD" ? isHeld(s) : s.signal === c.sig))
    && rules.every((r) => { const v = SF[r.f][2](s); return v != null && isFinite(v) && (r.op === ">=" ? v >= r.v : v <= r.v); }));
}
function vScr(root) {
  const d = S.d, c = scrCfg();
  if (!S.fund) loadFund().then(() => { if (S.view === "scr" && S.fund) renderView(true); });
  const needFund = c.rules.some((r) => SF[r.f] && SF[r.f][1] === "Fundamental");
  const rows = scrRows();
  const cols = [...new Set(["chg", "comp"].concat(c.rules.map((r) => r.f).filter((f) => SF[f])))].filter((k) => k !== "px");
  if (!S.sort.scr) S.sort.scr = ["comp", -1];
  const [sk, sd] = S.sort.scr, key = (s) => (sk === "ticker" ? s.ticker : sk === "sector" ? s.sector : sk === "px" ? s.last : SF[sk] ? SF[sk][2](s) : s.scores.composite);
  rows.sort((a, b) => { const x = key(a), y = key(b); if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * sd; });
  const th = (k, lab, r) => `<th class="${r ? "r" : ""}" data-sort="scr:${k}" style="cursor:pointer" title="${SF[k] ? SF[k][0] : lab}">${lab}${sk === k ? (sd > 0 ? " ▴" : " ▾") : ""}</th>`;
  const groups = [...new Set(Object.values(SF).map((x) => x[1]))];
  const fsel = (i, cur) => `<select data-sr="${i}:f">${groups.map((g) => `<optgroup label="${g}">${Object.entries(SF).filter(([, x]) => x[1] === g).map(([k, x]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${x[0]}${x[3].trim() ? " (" + x[3].trim() + ")" : ""}</option>`).join("")}</optgroup>`).join("")}</select>`;
  const custom = store.get("scrp", []);
  root.innerHTML = `<div class="grid g12">
  <div class="stack">
    <div class="panel"><h3>Aturan Screener <span class="fn">semua aturan harus terpenuhi</span></h3><div class="pb">
      ${c.rules.map((r, i) => `<div class="srow">${fsel(i, r.f)}<select data-sr="${i}:op"><option value=">=" ${r.op === ">=" ? "selected" : ""}>≥</option><option value="<=" ${r.op === "<=" ? "selected" : ""}>≤</option></select>
        <input data-sr="${i}:v" type="number" step="any" value="${r.v ?? ""}"><button data-srdel="${i}" title="Hapus aturan">✕</button></div>`).join("") || `<span class="mut small">Belum ada aturan — semua saham tampil.</span>`}
      <div style="display:flex;gap:8px;margin:8px 0 12px;flex-wrap:wrap"><button class="btn" id="sr-add">+ Aturan</button><button class="btn" id="sr-reset">Kosongkan</button></div>
      <div class="form"><label>Sektor<select data-sr="x:sec"><option value="ALL">Semua sektor</option>${d.market.sectors.map((x) => `<option ${c.sec === x.sector ? "selected" : ""}>${esc(x.sector)}</option>`).join("")}</select></label>
        <label>Sinyal<select data-sr="x:sig">${[["ALL", "Semua sinyal"], ["BUYS", "BUY + STRONG BUY"], ["HELD", "Ditahan filter pasar"], ["HOLD", "HOLD"], ["REDUCE", "REDUCE"], ["EXIT", "EXIT"]].map(([k, l]) => `<option value="${k}" ${c.sig === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>Status flow<select data-sr="x:st">${[["ALL", "Semua"], ["AKUMULASI", "Akumulasi"], ["NETRAL", "Netral"], ["DISTRIBUSI", "Distribusi"]].map(([k, l]) => `<option value="${k}" ${c.st === k ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
      ${needFund && !S.fund ? `<div class="note">Memuat data fundamental…</div>` : ""}
    </div></div>
    <div class="panel"><h3>Preset</h3><div class="pb small">
      ${SCR_PRE.map(([n, desc], i) => `<div class="prow" data-srp="b${i}"><b class="${c.name === n ? "amb" : ""}">${n}</b><span class="mut">${desc}</span></div>`).join("")}
      ${custom.map((p, i) => `<div class="prow" data-srp="c${i}"><b class="${c.name === p.name ? "amb" : ""}">${esc(p.name)}</b><span class="mut">preset kamu · ${p.cfg.rules.length} aturan</span><button data-srpdel="${i}" title="Hapus preset">✕</button></div>`).join("")}
      <div class="filters" style="margin-top:10px"><input id="sr-name" placeholder="Nama preset baru" maxlength="40" autocomplete="off"><button id="sr-save">Simpan aturan sekarang</button></div>
      <div class="note">Preset buatanmu disimpan di browser ini.</div>
    </div></div>
  </div>
  <div class="panel"><h3>Hasil <span class="fn">${rows.length} saham lolos dari ${pool().length} · data fundamental: Yahoo, mingguan</span></h3><div class="pb">
    <div class="filters">${scopeBar()}<button id="sr-csv" style="margin-left:auto">Unduh CSV</button></div>
    <div class="tw"><table><thead><tr>${th("ticker", "Ticker")}<th>Nama</th>${th("sector", "Sektor")}<th>Sinyal</th>${th("px", "Harga", 1)}${cols.map((k) => th(k, SFS[k] || SF[k][0], 1)).join("")}</tr></thead>
    <tbody>${rows.slice(0, S.cap).map((s) => `<tr data-t="${s.ticker}"><td class="tk">${s.ticker}</td><td class="mut">${esc(s.name.slice(0, 18))}</td><td class="mut">${esc(s.sector)}</td><td>${sig(s.signal)}</td><td class="r b">${num(s.last)}</td>
      ${cols.map((k) => { const v = SF[k][2](s); return `<td class="r ${SIGNED.includes(k) ? cls(v) : ""}" ${["comp", "flow", "mom", "trend", "sent"].includes(k) ? `style="color:${scoreColor(v)}"` : ""}>${sfFmt(k, v)}</td>`; }).join("")}</tr>`).join("")
      || `<tr><td colspan="${5 + cols.length}" class="mut">Tidak ada saham yang lolos semua aturan. Longgarkan salah satu aturan, atau pilih "Semua saham".</td></tr>`}</tbody></table></div>${moreBar(rows.length)}
    <div class="note">Persen diisi sebagai angka (15 = 15%). Nilai transaksi & net flow dalam miliar rupiah, kapitalisasi dalam triliun. Saham tanpa data untuk suatu aturan dianggap tidak lolos. Screener ini alat pencari; sinyal beli tetap di tab SIGNAL.</div>
  </div></div></div>`;
}
function scrCsv() {
  const c = scrCfg(), rows = scrRows(), keys = Object.keys(SF);
  const q = (x) => `"${String(x == null ? "" : x).replace(/"/g, '""')}"`;
  const lines = [["Ticker", "Nama", "Sektor", "Sinyal"].concat(keys.map((k) => SF[k][0] + (SF[k][3].trim() ? " (" + SF[k][3].trim() + ")" : ""))).map(q).join(",")]
    .concat(rows.map((s) => [s.ticker, s.name, s.sector, s.signal].map(q).concat(keys.map((k) => { const v = SF[k][2](s); return v == null || !isFinite(v) ? "" : Math.round(v * 1000) / 1000; })).join(",")));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" }));
  a.download = `screener-${(c.name || "kustom").toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${S.d.meta.generated_at.slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ================= LP (layar multi-panel / launchpad) ================= */
const PADT = { chart: "Chart harga", plan: "Rencana trade & syarat", val: "Fundamental & harga wajar", news: "Berita saham", sig: "Daftar sinyal", flowtop: "Top inflow / outflow", movers: "Top movers hari ini", watch: "Watchlist", scr: "Hasil screener", mkt: "Ringkasan pasar" };
const PADL = { "2": ["2 kolom", 2], "2x2": ["2 × 2", 4], "1+2": ["1 besar + 2", 3], "3": ["3 kolom", 3] };
const padCfg = () => { const c = Object.assign({ layout: "2x2", panels: ["chart", "sig", "plan", "news"], t: null, sub: {} }, store.get("pad", {})); if (!stock(c.t)) c.t = (S.d.stocks.find((s) => s.signal !== "AVOID") || S.d.stocks[0]).ticker; return c; };
const padRow = (s, right) => `<tr data-pt="${s.ticker}" class="${padCfg().t === s.ticker ? "hl" : ""}"><td class="tk">${s.ticker}</td><td>${sig(s.signal)}</td><td class="r">${num(s.last)}</td><td class="r ${cls(s.chg_pct)}">${pct(s.chg_pct)}</td>${right}</tr>`;
const padSub = (i, cur, opts) => `<div class="filters" style="margin-bottom:6px">${opts.map(([k, l]) => `<button data-padsub="${i}:${k}" class="${cur === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
function padBody(type, i, c) {
  const d = S.d, s = stock(c.t), f = fnd(s), sub = c.sub[i];
  const liq = d.stocks.filter((x) => x.signal !== "AVOID");
  const tbl = (rows, head, cell) => `<div class="tw"><table><thead><tr><th>Ticker</th><th>Sinyal</th><th class="r">Harga</th><th class="r">%</th><th class="r">${head}</th></tr></thead><tbody>${rows.map((x) => padRow(x, cell(x))).join("") || `<tr><td colspan="5" class="mut">Kosong.</td></tr>`}</tbody></table></div>`;
  if (type === "chart") return `<div class="padhd"><b class="amb">${s.ticker}</b> ${esc(s.name.slice(0, 28))} <b>${num(s.last)}</b> <span class="${cls(s.chg_pct)}">${pct(s.chg_pct)}</span> ${sig(s.signal)}<button class="btn" data-t="${s.ticker}" style="margin-left:auto;padding:1px 8px">Buka ↗</button></div><div class="padchart" id="pad-c${i}"><span class="mut small">Memuat chart…</span></div>`;
  if (type === "plan") { const L = s.levels; return `<div class="padhd"><b class="amb">${s.ticker}</b> komposit <b style="color:${scoreColor(s.scores.composite)}">${num(s.scores.composite)}</b> · flow ${num(s.scores.flow)} · mom ${num(s.scores.momentum)}</div>
    <dl class="kv small"><dt>Zona beli</dt><dd>${num(L.entry_low)} – ${num(L.entry_high)}</dd><dt>Stop loss</dt><dd class="down">${num(L.sl)} (${pct(-Math.abs(L.sl_pct))})</dd><dt>TP1 / TP2</dt><dd class="up">${num(L.tp1)} / ${num(L.tp2)}</dd><dt>Trailing stop</dt><dd>${num(L.trail)}</dd>
      <dt>Flow 5H / 20H / 60H</dt><dd><span class="${cls(s.flow.nf5)}">${rp(s.flow.nf5)}</span> / <span class="${cls(s.flow.nf20)}">${rp(s.flow.nf20)}</span> / <span class="${cls(s.flow.nf60)}">${rp(s.flow.nf60)}</span></dd><dt>Status flow</dt><dd class="${s.flow.status === "AKUMULASI" ? "up" : s.flow.status === "DISTRIBUSI" ? "down" : ""}">${s.flow.status}</dd></dl>
    ${(s.checks || []).length ? `<div class="small" style="margin-top:6px">${s.checks.map((k) => `<div style="display:flex;gap:6px"><b class="${k.ok ? "up" : "down"}" style="width:12px">${k.ok ? "✓" : "✗"}</b><span style="flex:1" class="${k.ok ? "mut" : ""}">${esc(k.t)}</span><span class="mut">${esc(k.v || "")}</span></div>`).join("")}</div>` : `<div class="note">Saham tidak likuid: tidak dinilai model.</div>`}`; }
  if (type === "val") { if (!S.fund) return `<span class="mut small">Memuat data fundamental…</span>`; if (!f) return `<span class="mut small">Data fundamental ${s.ticker} tidak tersedia.</span>`;
    const V = valuation(s, f, valAssump(s, f)), up = V.fair ? V.fair / s.last - 1 : null;
    return `<div class="padhd"><b class="amb">${s.ticker}</b> ${esc(f.industry || s.sector)}<button class="btn" data-padgo="${s.ticker}.val" style="margin-left:auto;padding:1px 8px">DCF ↗</button></div>
    <dl class="kv small"><dt>Kapitalisasi</dt><dd>${big(f.mcap)}</dd><dt>PER / PBV</dt><dd>${xr(f.pe)} / ${xr(f.pbv, 2)}</dd><dt>ROE / margin bersih</dt><dd>${pr(f.roe)} / ${pr(f.npm)}</dd><dt>Dividend yield</dt><dd>${pr(dyield(s, f))}</dd><dt>Utang / ekuitas</dt><dd>${xr(f.der, 2)}</dd>
      <dt>Perkiraan harga wajar</dt><dd class="amb b">${V.fair ? num(V.fair) : "–"} <span class="${cls(up)}">${up == null ? "" : pct(up, 0)}</span></dd></dl>
    <div class="small" style="margin-top:6px">${V.out.map((m) => `<div style="display:flex;gap:6px"><span style="flex:1" class="mut">${m.lab}</span><b>${m.mid > 0 ? num(m.mid) : "negatif"}</b><span class="${cls(m.mid / s.last - 1)}" style="width:48px;text-align:right">${m.mid > 0 ? pct(m.mid / s.last - 1, 0) : ""}</span></div>`).join("") || `<span class="mut">Tidak ada metode yang bisa dihitung.</span>`}</div>`; }
  if (type === "news") { const nw = d.news.filter((x) => x.tickers.includes(s.ticker)); return `<div class="padhd"><b class="amb">${s.ticker}</b> ${nw.length} berita · sentimen <b style="color:${scoreColor(s.scores.sentiment)}">${num(s.scores.sentiment)}</b></div>${(nw.length ? nw : d.news).slice(0, 12).map(newsItem).join("")}${nw.length ? "" : `<div class="note">Tidak ada berita ${s.ticker}; menampilkan berita pasar terbaru.</div>`}`; }
  if (type === "sig") { const m = sub || "CAND"; const rows = liq.filter((x) => (m === "BUY" ? x.signal === "BUY" || x.signal === "STRONG BUY" : m === "HELD" ? isHeld(x) : m === "CAND" ? isCand(x) : x.signal === "EXIT")).sort((a, b) => (b.scores.composite || 0) - (a.scores.composite || 0)).slice(0, 25);
    return padSub(i, m, [["BUY", "BUY"], ["HELD", "Ditahan"], ["CAND", "Kandidat"], ["EXIT", "EXIT"]]) + tbl(rows, "Komposit", (x) => `<td class="r" style="color:${scoreColor(x.scores.composite)}">${num(x.scores.composite)}</td>`); }
  if (type === "flowtop") { const m = sub || "IN"; const rows = liq.slice().sort((a, b) => (m === "IN" ? b.flow.nf5 - a.flow.nf5 : a.flow.nf5 - b.flow.nf5)).slice(0, 20);
    return padSub(i, m, [["IN", "Inflow 5H"], ["OUT", "Outflow 5H"]]) + tbl(rows, "Flow 5H", (x) => `<td class="r ${cls(x.flow.nf5)}">${rp(x.flow.nf5)}</td>`); }
  if (type === "movers") { const m = sub || "UP"; const rows = liq.slice().sort((a, b) => (m === "UP" ? b.chg_pct - a.chg_pct : m === "DN" ? a.chg_pct - b.chg_pct : m === "VAL" ? b.flow.value - a.flow.value : b.flow.volratio - a.flow.volratio)).slice(0, 20);
    return padSub(i, m, [["UP", "Naik"], ["DN", "Turun"], ["VAL", "Teraktif"], ["VOL", "Lonjakan volume"]]) + tbl(rows, m === "VOL" ? "Volume" : "Nilai", (x) => `<td class="r">${m === "VOL" ? num(x.flow.volratio, 1) + "x" : rp(x.flow.value, false)}</td>`); }
  if (type === "watch") return tbl(watch().map(stock).filter(Boolean), "Komposit", (x) => `<td class="r" style="color:${scoreColor(x.scores.composite)}">${num(x.scores.composite)}</td>`) + (watch().length ? "" : `<div class="note">Watchlist kosong — tambah dengan perintah W ADD BBCA.</div>`);
  if (type === "scr") { const rows = scrRows().sort((a, b) => (b.scores.composite || 0) - (a.scores.composite || 0)); return `<div class="padhd">Screener: <b class="amb">${esc(scrCfg().name || "kustom")}</b> · ${rows.length} saham<button class="btn" data-view="scr" style="margin-left:auto;padding:1px 8px">Atur ↗</button></div>` + tbl(rows.slice(0, 25), "Komposit", (x) => `<td class="r" style="color:${scoreColor(x.scores.composite)}">${num(x.scores.composite)}</td>`); }
  const m = d.market, ih = m.ihsg, g = m.gate || {};
  return `<div class="padhd">IHSG <b>${num(ih.last, 2)}</b> <span class="${cls(ih.chg_pct)}">${pct(ih.chg_pct, 2)}</span> · rezim <b class="amb">${esc(m.regime.label)}</b></div>
    <dl class="kv small"><dt>Gerbang beli</dt><dd class="${g.open ? "up" : "down"}">${g.open ? "TERBUKA" : "TERTUTUP"}${g.held ? " · " + g.held + " saham ditahan" : ""}</dd><dt>Sinyal BUY / EXIT</dt><dd><span class="up">${(m.signal_count["BUY"] || 0) + (m.signal_count["STRONG BUY"] || 0)}</span> / <span class="down">${m.signal_count["EXIT"] || 0}</span></dd>
      <dt>Saham naik / turun (likuid)</dt><dd><span class="up">${liq.filter((x) => x.chg_pct > 0).length}</span> / <span class="down">${liq.filter((x) => x.chg_pct < 0).length}</span></dd>
      ${(m.macro || []).map((x) => `<dt>${esc(x.name)}</dt><dd>${num(x.last, x.last < 100 ? 2 : 0)} <span class="${cls(x.chg_pct)}">${pct(x.chg_pct)}</span></dd>`).join("")}</dl>`;
}
function vPad(root) {
  const c = padCfg(), n = PADL[c.layout] ? PADL[c.layout][1] : 4, s = stock(c.t);
  if (!S.fund && c.panels.slice(0, n).some((t) => t === "val" || t === "scr")) loadFund().then(() => { if (S.view === "pad" && S.fund) renderView(true); });
  while (c.panels.length < n) c.panels.push(Object.keys(PADT)[c.panels.length % Object.keys(PADT).length]);
  root.innerHTML = `<div class="filters"><span class="mut small">Tata letak</span>${Object.entries(PADL).map(([k, v]) => `<button data-padlay="${k}" class="${c.layout === k ? "on" : ""}">${v[0]}</button>`).join("")}
      <span class="mut small" style="margin-left:10px">Saham aktif</span><input id="pad-t" list="tickers" value="${s.ticker}" autocomplete="off" spellcheck="false" style="text-transform:uppercase;width:90px">
      <span class="mut small hide-m">klik baris di panel daftar untuk mengganti saham di semua panel</span></div>
    <div class="pad pad-${c.layout.replace("+", "p")}">${c.panels.slice(0, n).map((t, i) => `<div class="panel"><h3><select data-padtype="${i}">${Object.entries(PADT).map(([k, l]) => `<option value="${k}" ${k === t ? "selected" : ""}>${l}</option>`).join("")}</select></h3><div class="pb padb">${padBody(t, i, c)}</div></div>`).join("")}</div>`;
  c.panels.slice(0, n).forEach((t, i) => { if (t === "chart") padChart($("#pad-c" + i), s); });
}
async function padChart(el, s) {
  if (!el) return;
  if (!s.series) { try { s.series = await loadSeries(s.ticker); } catch (e) { el.innerHTML = `<span class="mut small">Gagal memuat chart (${esc(e.message)})</span>`; return; } }
  if (!document.body.contains(el) || S.view !== "pad") return;
  el.innerHTML = "";
  const n = s.series.c.length, dates = S.d.dates.slice(-n), L = s.levels;
  const ch = mkChart(el, S.charts, { localization: { priceFormatter: (x) => num(x, 0) } });
  const cs = ch.addCandlestickSeries({ upColor: COL.up, downColor: COL.down, borderVisible: false, wickUpColor: COL.up, wickDownColor: COL.down, priceFormat: { type: "price", precision: 0, minMove: 1 } });
  cs.setData(dates.map((tm, i) => ({ time: tm, open: s.series.o[i], high: s.series.h[i], low: s.series.l[i], close: s.series.c[i] })).filter((x) => x.close != null));
  [["ma20", COL.s1], ["ma50", COL.s2]].forEach(([k, col]) => ch.addLineSeries({ color: col, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }).setData(ser(dates, s.series[k])));
  const vs = ch.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
  ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false });
  vs.setData(dates.map((tm, i) => ({ time: tm, value: s.series.v[i] || 0, color: (s.series.nf[i] || 0) >= 0 ? "rgba(46,189,107,.45)" : "rgba(240,71,79,.45)" })));
  if (L.sl) cs.createPriceLine({ price: L.sl, color: COL.down, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: "SL" });
  if (L.entry_low) cs.createPriceLine({ price: L.entry_low, color: COL.s1, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "BUY" });
  ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 110), to: n + 3 });
}

/* ================= WEI / GLCO / WCRS (pasar global) ================= */
const gspark = (a, w = 96, h = 24) => {
  const v = (a || []).filter((x) => x != null); if (v.length < 2) return "";
  const mn = Math.min(...v), mx = Math.max(...v), r = mx - mn || 1;
  const pts = v.map((x, i) => `${((i / (v.length - 1)) * (w - 3) + 1).toFixed(1)},${(h - 2 - ((x - mn) / r) * (h - 4)).toFixed(1)}`).join(" ");
  const up = v[v.length - 1] >= v[0], last = pts.split(" ").pop().split(",");
  return `<svg width="${w}" height="${h}" class="spk"><polyline points="${pts}" fill="none" stroke="${up ? COL.up : COL.down}" stroke-width="1.3"/><circle cx="${last[0]}" cy="${last[1]}" r="2" fill="${up ? COL.up : COL.down}"/></svg>`;
};
const GORDER = ["Indeks", "Komoditas", "Kurs", "Obligasi", "Kripto"];
function vGlob(root) {
  const g = S.d.market.global || {}, items = g.items || [];
  if (!items.length) { root.innerHTML = `<div class="callout">Data pasar global belum tersedia. Akan muncul setelah update berikutnya.</div>`; return; }
  const by = (n) => items.find((x) => x.name === n);
  const isY = (x) => x.g === "Obligasi";
  const lastF = (x) => (isY(x) ? num(x.last, 2) + "%" : x.g === "Kurs" && x.last > 100 ? num(x.last, 0) : num(x.last, x.last < 10 ? 3 : 2));
  const chg = (x, k) => { if (isY(x)) { const v = x.abs && x.abs[k]; return v == null ? `<td class="r mut">–</td>` : `<td class="r ${cls(-v)}">${v > 0 ? "+" : ""}${num(v * 100, 0)} bp</td>`; }
    const v = x[k]; return v == null ? `<td class="r mut">–</td>` : `<td class="r ${x.g === "Kurs" && x.name.endsWith("/IDR") ? cls(-v) : x.name.startsWith("VIX") ? cls(-v) : cls(v)}">${pct(v, Math.abs(v) < 0.1 ? 1 : 0)}</td>`; };
  const rng = (x) => { const p = x.hi52 > x.lo52 ? (x.last - x.lo52) / (x.hi52 - x.lo52) : 0.5; return `<div class="rvb" title="52 mgg: ${num(x.lo52, 2)} – ${num(x.hi52, 2)}"><i style="left:${Math.max(0, Math.min(1, p)) * 100}%"></i></div>`; };
  const key = ["S&P 500", "Nikkei 225", "Hang Seng", "Emas", "Minyak Brent", "Batu bara (Newcastle)", "USD/IDR", "Indeks dolar (DXY)", "Yield US 10 tahun"].map(by).filter(Boolean);
  const grp = (gn) => { const rows = items.filter((x) => x.g === gn); if (!rows.length) return "";
    return `<div class="panel"><h3>${gn} <span class="fn">${gn === "Kurs" ? "kenaikan = rupiah melemah (merah)" : gn === "Obligasi" ? "perubahan dalam basis poin; naik = merah" : rows.length + " instrumen"}</span></h3><div class="pb"><div class="tw"><table>
      <thead><tr><th>Nama</th><th class="r">Terakhir</th><th class="r">Hari ini</th><th class="r">1M</th><th class="r">1B</th><th class="r">3B</th><th class="r">YTD</th><th class="r">1T</th><th>Rentang 52 mgg</th><th class="r" title="Korelasi return harian dengan IHSG, 1 tahun">Kor. IHSG</th><th>90 hari</th></tr></thead>
      <tbody>${rows.map((x) => `<tr title="${esc(x.sym)} · data ${esc(x.date)}"><td class="b">${esc(x.name)}</td><td class="r b">${lastF(x)}</td>${["chg", "w1", "m1", "m3", "ytd", "y1"].map((k) => chg(x, k)).join("")}
        <td style="width:90px">${rng(x)}</td><td class="r ${x.corr >= 0.4 ? "up" : x.corr <= -0.2 ? "down" : "mut"}">${x.corr == null ? "–" : num(x.corr, 2)}</td><td>${gspark(x.spark)}</td></tr>`).join("")}</tbody></table></div></div></div>`; };
  root.innerHTML = `<div class="tiles" style="margin-bottom:8px">${key.map((x) => `<div class="tile"><div class="l">${esc(x.name)}</div><div class="v">${lastF(x)} ${isY(x) ? "" : `<span class="small ${x.g === "Kurs" ? cls(-x.chg) : cls(x.chg)}">${pct(x.chg, 1)}</span>`}</div>${gspark(x.spark.slice(-30), 120, 20)}</div>`).join("")}</div>
    <div class="grid g2">${GORDER.map(grp).join("")}</div>
    <div class="note">Sumber: ${esc(g.source || "Yahoo Finance")}; tiap pasar memakai harga penutupan terakhirnya sendiri (zona waktu berbeda). Kor. IHSG = korelasi return harian dengan IHSG selama ±1 tahun; karena jam bursa berbeda, pengaruh pasar AS ke IHSG sering baru muncul esok harinya, jadi angka ini cenderung lebih kecil dari pengaruh sebenarnya.
    ${(g.missing || []).length ? `<br>Tidak tersedia di Yahoo Finance: ${(g.missing || []).map(esc).join(", ")}. Yield SBN Indonesia juga tidak tersedia gratis.` : ""}</div>`;
}

/* ================= COMP / CORR (bandingkan saham) ================= */
const CPAL = ["#ffa028", "#4aa3e8", "#d0559a", "#2ebd6b", "#a67de8", "#38c7c0"];
const compCfg = () => { const c = Object.assign({ t: [], win: 63 }, store.get("comp", {})); c.t = c.t.filter(stock).slice(0, 6);
  if (!c.t.length) c.t = (watch().filter(stock).length ? watch().filter(stock) : S.d.stocks.filter((s) => s.signal !== "AVOID").sort((a, b) => (b.flow.avg_val20 || 0) - (a.flow.avg_val20 || 0)).map((s) => s.ticker)).slice(0, 4);
  return c; };
function compStats(r, m) {     // r, m: return harian sejajar (tanpa null)
  const n = r.length; if (n < 10) return {};
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length, mr = mean(r), mm = mean(m);
  let cov = 0, vr = 0, vm = 0; for (let i = 0; i < n; i++) { cov += (r[i] - mr) * (m[i] - mm); vr += (r[i] - mr) ** 2; vm += (m[i] - mm) ** 2; }
  return { vol: Math.sqrt(vr / (n - 1)) * Math.sqrt(252), beta: vm > 0 ? cov / vm : null, corr: vr > 0 && vm > 0 ? cov / Math.sqrt(vr * vm) : null };
}
function vComp(root) {
  const c = compCfg(), d = S.d, ih = d.market.ihsg.series, N = ih.length;
  const need = c.t.map(stock).filter((s) => !s.series);
  root.innerHTML = `<div class="filters"><span class="mut small">Saham (maks 6)</span>${c.t.map((t, i) => `<span class="chip2" style="border-color:${CPAL[i]}"><b style="color:${CPAL[i]}" data-t="${t}">${t}</b><button data-cdel="${t}" title="Hapus">✕</button></span>`).join("")}
      ${c.t.length < 6 ? `<input id="c-add" list="tickers" placeholder="+ kode saham" autocomplete="off" spellcheck="false" style="text-transform:uppercase;width:120px">` : ""}
      <span class="mut small" style="margin-left:10px">Periode</span>${[[21, "1B"], [63, "3B"], [126, "6B"], [9999, "Maks"]].map(([w, l]) => `<button data-cwin="${w}" class="${c.win === w ? "on" : ""}">${l}</button>`).join("")}</div>
    <div id="c-body">${need.length ? `<span class="mut">Memuat data ${need.map((s) => s.ticker).join(", ")}…</span>` : ""}</div>`;
  if (need.length) { Promise.all(need.map((s) => loadSeries(s.ticker).then((x) => { s.series = x; }).catch(() => {}))).then(() => { if (S.view === "comp") renderView(true); }); return; }
  const W = Math.min(c.win, N - 1), from = N - 1 - W;
  const dates = d.dates.slice(-N).slice(from);
  const al = (s) => { const a = s.series.c, pad = N - a.length; return Array.from({ length: N }, (_, i) => (i - pad >= 0 ? a[i - pad] : null)).slice(from); };
  const sers = c.t.map((t, i) => { const s = stock(t); return { t, s, col: CPAL[i], px: al(s) }; });
  const ihs = ih.slice(from);
  const rets = (px) => px.map((x, i) => (i && x != null && px[i - 1] != null && px[i - 1] > 0 ? x / px[i - 1] - 1 : null));
  const ihr = rets(ihs);
  const rows = sers.map((o) => { const r = rets(o.px), pr2 = [], pm = []; r.forEach((x, i) => { if (x != null && ihr[i] != null) { pr2.push(x); pm.push(ihr[i]); } });
    const st = compStats(pr2, pm), first = o.px.find((x) => x != null), last = o.px[o.px.length - 1];
    let pk = -Infinity, dd = 0; o.px.forEach((x) => { if (x == null) return; pk = Math.max(pk, x); dd = Math.min(dd, x / pk - 1); });
    return Object.assign(o, st, { ret: first && last ? last / first - 1 : null, dd, r }); });
  const ihRet = ihs[ihs.length - 1] / ihs[0] - 1; let pk = -Infinity, ihdd = 0; ihs.forEach((x) => { pk = Math.max(pk, x); ihdd = Math.min(ihdd, x / pk - 1); });
  const ihst = compStats(ihr.filter((x) => x != null), ihr.filter((x) => x != null));
  const all = rows.map((o) => ({ lab: o.t, col: o.col, r: o.r })).concat({ lab: "IHSG", col: "#ddd", r: ihr });
  const cor = (a, b) => { const x = [], y = []; a.forEach((v, i) => { if (v != null && b[i] != null) { x.push(v); y.push(b[i]); } }); return compStats(x, y).corr; };
  const corrCol = (v) => (v == null ? "#1c1c1c" : v >= 0 ? `rgba(46,143,208,${0.15 + 0.75 * v})` : `rgba(240,71,79,${0.15 + 0.75 * -v})`);
  $("#c-body").innerHTML = `<div class="grid g21"><div class="stack">
    <div class="panel"><h3>Return Relatif <span class="fn">awal periode = 100 · ${dates[0]} s/d ${dates[dates.length - 1]}</span></h3><div class="pb"><div id="c-ch" style="height:420px"></div>
      <div class="lg" style="margin-top:6px">${rows.map((o) => `<span><i style="background:${o.col}"></i>${o.t}</span>`).join("")}<span><i class="dash" style="color:#ddd"></i>IHSG</span></div></div></div>
    <div class="panel"><h3>Statistik <span class="fn">return harian, periode yang dipilih</span></h3><div class="pb"><div class="tw"><table>
      <thead><tr><th>Ticker</th><th>Sinyal</th><th class="r">Return</th><th class="r">vs IHSG</th><th class="r" title="Volatilitas tahunan">Volatilitas</th><th class="r" title="Kepekaan terhadap IHSG: 1,5 = rata-rata bergerak 1,5% saat IHSG bergerak 1%">Beta</th><th class="r">Korelasi IHSG</th><th class="r">Turun terdalam</th><th class="r">Komposit</th></tr></thead>
      <tbody>${rows.map((o) => `<tr data-t="${o.t}"><td class="tk" style="color:${o.col}">${o.t}</td><td>${sig(o.s.signal)}</td><td class="r b ${cls(o.ret)}">${pct(o.ret, 1)}</td><td class="r ${cls(o.ret - ihRet)}">${pct(o.ret - ihRet, 1)}</td>
        <td class="r">${o.vol == null ? "–" : pr(o.vol, 0)}</td><td class="r b">${o.beta == null ? "–" : num(o.beta, 2)}</td><td class="r">${o.corr == null ? "–" : num(o.corr, 2)}</td><td class="r down">${pct(o.dd, 1)}</td><td class="r" style="color:${scoreColor(o.s.scores.composite)}">${num(o.s.scores.composite)}</td></tr>`).join("")}
      <tr class="hl"><td class="b">IHSG</td><td></td><td class="r b ${cls(ihRet)}">${pct(ihRet, 1)}</td><td class="r mut">–</td><td class="r">${ihst.vol == null ? "–" : pr(ihst.vol, 0)}</td><td class="r">1,00</td><td class="r">1,00</td><td class="r down">${pct(ihdd, 1)}</td><td></td></tr></tbody></table></div>
      <div class="note">Beta dan korelasi dihitung dari return harian periode ini; periode 1 bulan hanya ±20 data, jadi angkanya kasar. Data harga per saham tersedia ±200 hari bursa terakhir.</div></div></div>
  </div><div class="stack">
    <div class="panel"><h3>Matriks Korelasi <span class="fn">return harian</span></h3><div class="pb">
      <div class="tw"><table class="cmx"><thead><tr><th></th>${all.map((a) => `<th class="r" style="color:${a.col}">${a.lab}</th>`).join("")}</tr></thead><tbody>
      ${all.map((a) => `<tr><td class="b" style="color:${a.col}">${a.lab}</td>${all.map((b) => { const v = a === b ? 1 : cor(a.r, b.r); return `<td class="r" style="background:${corrCol(v)}">${v == null ? "–" : num(v, 2)}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="note">Biru = bergerak searah, merah = berlawanan. Korelasi tinggi antar saham (di atas ±0,7) berarti memegang keduanya hampir sama dengan memegang satu saham dua kali lipat: diversifikasinya kecil.</div></div></div>
  </div></div>`;
  const ch = mkChart($("#c-ch"), S.charts, { localization: { priceFormatter: (x) => num(x, 0) } });
  const base = (px) => { const f = px.find((x) => x != null); return px.map((x) => (x == null || !f ? null : (x / f) * 100)); };
  ch.addLineSeries({ color: "#ddd", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: true, title: "IHSG" }).setData(ser(dates, base(ihs)));
  rows.forEach((o) => ch.addLineSeries({ color: o.col, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: o.t }).setData(ser(dates, base(o.px))));
  ch.timeScale().fitContent();
}

/* ================= JRNL (jurnal trading, disimpan di browser) ================= */
const jr = () => Object.assign({ open: [], closed: [] }, store.get("jrnl", {}));
const jrSet = (j) => store.set("jrnl", j);
const today = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const feeB = () => (S.d.rules.fee_buy ?? 0.0015), feeS = () => (S.d.rules.fee_sell ?? 0.0025);
const lotSz = () => S.d.rules.lot_size || 100;
function jrPos(p) {
  const s = stock(p.t), px = s ? s.last : null, sh = p.lots * lotSz(), cost = p.px * sh * (1 + feeB());
  const val = px != null ? px * sh * (1 - feeS()) : null, pl = val != null ? val - cost : null;
  const risk = p.sl && p.sl < p.px ? (p.px - p.sl) * sh : null;
  const warn = [];
  if (s && p.sl && px <= p.sl) warn.push(["down", "Harga ≤ stop loss"]);
  if (s && s.levels.trail && px < s.levels.trail) warn.push(["down", "Di bawah trailing stop model (" + num(s.levels.trail) + ")"]);
  if (s && s.signal === "EXIT") warn.push(["down", "Sinyal model: EXIT"]);
  else if (s && s.signal === "REDUCE") warn.push(["amb", "Sinyal model: REDUCE"]);
  if (s && p.tp && px >= p.tp) warn.push(["up", "Target tercapai"]);
  return { s, px, sh, cost, val, pl, plp: pl != null ? pl / cost : null, r: risk && pl != null ? pl / risk : null, risk, toSl: p.sl && px ? p.sl / px - 1 : null, warn };
}
function jrClosed(p) {
  const sh = p.lots * lotSz(), cost = p.px * sh * (1 + feeB()), got = p.xpx * sh * (1 - feeS()), pl = got - cost, risk = p.sl && p.sl < p.px ? (p.px - p.sl) * sh : null;
  return { cost, pl, plp: pl / cost, r: risk ? pl / risk : null, days: Math.max(0, Math.round((new Date(p.xd) - new Date(p.d)) / 864e5)) };
}
function jrAlerts() {       // peringatan stop untuk posisi di jurnal -> masuk riwayat alert
  const j = jr(); let fired = [];
  j.open.forEach((p) => { const q = jrPos(p); const hit = !!(q.s && p.sl && q.px <= p.sl); if (hit && !p.hit) fired.push(`JURNAL ${p.t}: harga ${num(q.px)} ≤ stop ${num(p.sl)}`); p.hit = hit; });
  jrSet(j);
  if (!fired.length) return;
  store.set("alog", fired.map((m) => ({ ts: Date.now(), m, at: S.d.meta.generated_at })).concat(store.get("alog", [])).slice(0, 60));
  toast("ALERT · " + fired[0]);
  if ("Notification" in window && Notification.permission === "granted") { try { new Notification("IDX Quant Terminal", { body: fired.join("\n") }); } catch { /* tidak didukung */ } }
}
function vJrnl(root) {
  const j = jr(), d = S.d, open = j.open.map((p) => Object.assign({ p }, jrPos(p))), closed = j.closed.map((p) => Object.assign({ p }, jrClosed(p)));
  const sum = (a, k) => a.reduce((x, y) => x + (y[k] || 0), 0);
  const wins = closed.filter((x) => x.pl > 0), loss = closed.filter((x) => x.pl <= 0);
  const pf = sum(loss, "pl") ? sum(wins, "pl") / -sum(loss, "pl") : null;
  const rs = closed.filter((x) => x.r != null);
  const pre = S.jpre && stock(S.jpre) ? stock(S.jpre) : null;
  const rpx = (x) => (x == null ? "–" : (x < 0 ? "−Rp" : "Rp") + num(Math.abs(x)));
  const editing = S.jsell;
  root.innerHTML = `<div class="grid g21"><div class="stack">
    <div class="panel"><h3>Posisi Terbuka <span class="fn">${open.length} posisi · harga terakhir ${esc(d.meta.generated_at.slice(0, 16).replace("T", " "))}</span></h3><div class="pb">
      <div class="tiles" style="margin-bottom:8px"><div class="tile"><div class="l">Modal terpakai</div><div class="v">${rpx(sum(open, "cost"))}</div></div><div class="tile"><div class="l">Nilai pasar (bersih fee jual)</div><div class="v">${rpx(sum(open, "val"))}</div></div>
        <div class="tile"><div class="l">Untung/rugi belum terealisasi</div><div class="v ${cls(sum(open, "pl"))}">${rpx(sum(open, "pl"))}</div></div><div class="tile"><div class="l">Risiko ke stop loss</div><div class="v down">${rpx(-sum(open, "risk"))}</div></div></div>
      <div class="tw"><table><thead><tr><th>Ticker</th><th>Beli</th><th class="r">Lot</th><th class="r">Harga beli</th><th class="r">Sekarang</th><th class="r">U/R</th><th class="r">%</th><th class="r" title="Untung/rugi dibagi risiko awal (harga beli − stop)">R</th><th class="r">Stop</th><th class="r">Ke stop</th><th>Peringatan</th><th></th></tr></thead>
      <tbody>${open.map((o) => editing === o.p.id ? `<tr class="hl"><td class="tk">${o.p.t}</td><td colspan="11"><div class="jsell">Jual <input id="js-lots" type="number" min="1" max="${o.p.lots}" value="${o.p.lots}"> lot di harga <input id="js-px" type="number" value="${o.px ?? o.p.px}"> tanggal <input id="js-d" type="date" value="${today()}"><button class="btn" data-jsok="${o.p.id}">Simpan penjualan</button><button class="btn" data-jscancel>Batal</button></div></td></tr>`
        : `<tr><td class="tk" data-t="${o.p.t}">${o.p.t}</td><td class="mut">${esc(o.p.d)}</td><td class="r">${num(o.p.lots)}</td><td class="r">${num(o.p.px)}</td><td class="r b">${o.px == null ? "–" : num(o.px)}</td><td class="r ${cls(o.pl)}">${rpx(o.pl)}</td><td class="r ${cls(o.plp)}">${o.plp == null ? "–" : pct(o.plp, 1)}</td>
          <td class="r ${cls(o.r)}">${o.r == null ? "–" : num(o.r, 1) + "R"}</td><td class="r down">${o.p.sl ? num(o.p.sl) : "–"}</td><td class="r">${o.toSl == null ? "–" : pct(o.toSl, 1)}</td>
          <td style="white-space:normal;min-width:200px">${o.warn.map(([c, t]) => `<span class="chip n ${c}">${t}</span>`).join("") || `<span class="mut small">aman</span>`}</td><td style="white-space:nowrap"><button class="btn sm" data-jsell="${o.p.id}">Jual</button> <button class="xbtn" data-jdel="${o.p.id}" title="Hapus catatan (tanpa menjual)">✕</button></td></tr>`).join("")
        || `<tr><td colspan="12" class="mut">Belum ada posisi. Catat pembelianmu di form sebelah kanan.</td></tr>`}</tbody></table></div>
      <div class="note">U/R sudah dikurangi fee beli ${pr(feeB(), 2)} dan fee jual ${pr(feeS(), 2)}. Peringatan memakai data model terbaru; posisi yang menembus stop juga masuk riwayat alert di tab WATCH.</div></div></div>
    <div class="panel"><h3>Trade Selesai <span class="fn">${closed.length} trade</span></h3><div class="pb">
      ${closed.length ? `<div class="tiles" style="margin-bottom:8px"><div class="tile"><div class="l">Total terealisasi</div><div class="v ${cls(sum(closed, "pl"))}">${rpx(sum(closed, "pl"))}</div></div><div class="tile"><div class="l">Win rate</div><div class="v">${pr(wins.length / closed.length, 0)}</div></div>
        <div class="tile"><div class="l">Rata-rata untung / rugi</div><div class="v"><span class="up">${wins.length ? pct(sum(wins, "plp") / wins.length, 1) : "–"}</span> / <span class="down">${loss.length ? pct(sum(loss, "plp") / loss.length, 1) : "–"}</span></div></div>
        <div class="tile"><div class="l">Profit factor</div><div class="v">${pf == null ? "–" : num(pf, 2)}</div></div><div class="tile"><div class="l">Rata-rata R</div><div class="v ${cls(sum(rs, "r"))}">${rs.length ? num(sum(rs, "r") / rs.length, 2) + "R" : "–"}</div></div><div class="tile"><div class="l">Rata-rata lama pegang</div><div class="v">${num(sum(closed, "days") / closed.length)} hari</div></div></div>
        <div id="j-eq" style="height:180px;margin-bottom:8px"></div>` : ""}
      <div class="tw"><table><thead><tr><th>Ticker</th><th>Beli</th><th>Jual</th><th class="r">Hari</th><th class="r">Lot</th><th class="r">Beli</th><th class="r">Jual</th><th class="r">U/R</th><th class="r">%</th><th class="r">R</th><th>Catatan</th><th></th></tr></thead>
      <tbody>${closed.slice().reverse().map((o) => `<tr><td class="tk" data-t="${o.p.t}">${o.p.t}</td><td class="mut">${esc(o.p.d)}</td><td class="mut">${esc(o.p.xd)}</td><td class="r">${o.days}</td><td class="r">${num(o.p.lots)}</td><td class="r">${num(o.p.px)}</td><td class="r">${num(o.p.xpx)}</td>
        <td class="r ${cls(o.pl)}">${rpx(o.pl)}</td><td class="r ${cls(o.plp)}">${pct(o.plp, 1)}</td><td class="r ${cls(o.r)}">${o.r == null ? "–" : num(o.r, 1) + "R"}</td><td class="mut small">${esc(o.p.note || "")}</td><td><button class="xbtn" data-jcdel="${o.p.id}" title="Hapus">✕</button></td></tr>`).join("") || `<tr><td colspan="12" class="mut">Belum ada trade yang ditutup.</td></tr>`}</tbody></table></div></div></div>
  </div><div class="stack">
    <div class="panel"><h3>Catat Pembelian</h3><div class="pb">
      <div class="form"><label>Saham<input id="j-t" list="tickers" autocomplete="off" spellcheck="false" style="text-transform:uppercase" value="${pre ? pre.ticker : ""}"></label>
        <label>Tanggal beli<input id="j-d" type="date" value="${today()}"></label>
        <label>Harga beli<input id="j-px" type="number" min="1" value="${pre ? pre.last : ""}"></label>
        <label>Jumlah lot<input id="j-lots" type="number" min="1" value=""></label>
        <label>Stop loss<input id="j-sl" type="number" min="0" value="${pre ? pre.levels.sl : ""}"></label>
        <label>Target (opsional)<input id="j-tp" type="number" min="0" value="${pre ? pre.levels.tp1 : ""}"></label>
        <label style="grid-column:1/-1">Catatan (alasan masuk)<input id="j-note" maxlength="140" placeholder="mis. lolos 9/9 syarat, breakout volume"></label></div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><button class="btn" id="j-add">Catat beli</button></div>
      <p class="note">Ketik kode saham lalu pindah kolom: harga, stop loss, dan target terisi otomatis dari model (bisa diubah). Membeli saham yang sama dua kali dicatat sebagai dua posisi.</p></div></div>
    <div class="panel"><h3>Simpan & Pindah Perangkat</h3><div class="pb">
      <p class="note" style="margin-top:0">Jurnal tersimpan di browser ini saja. Unduh cadangan secara berkala, lalu impor di perangkat lain untuk memindahkannya.</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="j-exp">Unduh cadangan (.json)</button><label class="btn" style="cursor:pointer">Impor cadangan<input id="j-imp" type="file" accept=".json,application/json" hidden></label></div></div></div>
  </div></div>`;
  if (closed.length) {
    const byDate = closed.slice().sort((a, b) => (a.p.xd < b.p.xd ? -1 : a.p.xd > b.p.xd ? 1 : 0)); let cum = 0; const pts = [];
    byDate.forEach((o) => { cum += o.pl; if (pts.length && pts[pts.length - 1].time === o.p.xd) pts[pts.length - 1].value = cum; else pts.push({ time: o.p.xd, value: cum }); });
    const ch = mkChart($("#j-eq"), S.charts, { localization: { priceFormatter: (x) => (x < 0 ? "−" : "") + num(Math.abs(x) / 1e6, 1) + " jt" } });
    ch.addBaselineSeries({ baseValue: { type: "price", price: 0 }, topLineColor: COL.up, bottomLineColor: COL.down, topFillColor1: "rgba(46,189,107,.25)", topFillColor2: "rgba(46,189,107,0)", bottomFillColor1: "rgba(240,71,79,0)", bottomFillColor2: "rgba(240,71,79,.25)", priceLineVisible: false }).setData(pts);
    ch.timeScale().fitContent();
  }
}
function jrAdd() {
  const t = ($("#j-t").value || "").trim().toUpperCase(), px = +$("#j-px").value, lots = Math.floor(+$("#j-lots").value), sl = +$("#j-sl").value || null, tp = +$("#j-tp").value || null, dd = $("#j-d").value || today();
  if (!stock(t)) { toast("Ticker tidak ditemukan: " + t); return; }
  if (!(px > 0)) { toast("Isi harga beli"); return; }
  if (!(lots > 0)) { toast("Isi jumlah lot"); return; }
  if (sl && sl >= px) { toast("Stop loss harus di bawah harga beli"); return; }
  const j = jr(); j.open.push({ id: Date.now(), t, d: dd, px, lots, sl, tp, note: ($("#j-note").value || "").trim() }); jrSet(j);
  S.jpre = null; toast(`Tercatat: beli ${t} ${lots} lot @ ${num(px)}`); renderView(true);
}
function jrSell(id) {
  const j = jr(), i = j.open.findIndex((p) => String(p.id) === String(id)); if (i < 0) return;
  const p = j.open[i], lots = Math.floor(+$("#js-lots").value), xpx = +$("#js-px").value, xd = $("#js-d").value || today();
  if (!(lots > 0 && lots <= p.lots)) { toast("Jumlah lot jual 1 sampai " + p.lots); return; }
  if (!(xpx > 0)) { toast("Isi harga jual"); return; }
  if (xd < p.d) { toast("Tanggal jual sebelum tanggal beli"); return; }
  j.closed.push(Object.assign({}, p, { id: Date.now(), lots, xpx, xd }));
  if (lots === p.lots) j.open.splice(i, 1); else p.lots -= lots;
  jrSet(j); S.jsell = null; toast(`Tercatat: jual ${p.t} ${lots} lot @ ${num(xpx)}`); renderView(true);
}

/* ================= FS (ringkasan laporan keuangan) & EE (proyeksi) ================= */
async function loadFs(t) {
  S.fsc = S.fsc || {};
  if (t in S.fsc) return S.fsc[t];
  const f = ((S.fund && S.fund.items) || {})[t];
  if (f && f.fs) return (S.fsc[t] = Object.assign({ cur: f.cur }, f.fs));
  try {
    const r = await fetch(`data/fs/${t}.json?v=${encodeURIComponent(S.d.meta.generated_at.slice(0, 10))}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json(); S.fsc[t] = j.enc ? await decryptEnv(j, S.key) : j;
  } catch { S.fsc[t] = null; }
  return S.fsc[t];
}
const FSL = {
  is: [["rev", "Pendapatan"], ["nii", "Pendapatan bunga bersih"], ["gp", "Laba kotor"], ["op", "Laba operasi"], ["ebitda", "EBITDA"], ["intx", "Beban bunga"], ["pbt", "Laba sebelum pajak"], ["tax", "Pajak"], ["ni", "Laba bersih"], ["eps", "EPS (per saham)"]],
  bs: [["ta", "Total aset"], ["ca", "Aset lancar"], ["cash", "Kas & setara kas"], ["rec", "Piutang"], ["inv", "Persediaan"], ["tl", "Total liabilitas"], ["cl", "Liabilitas lancar"], ["debt", "Total utang"], ["eq", "Ekuitas"]],
  cf: [["ocf", "Arus kas operasi"], ["capex", "Belanja modal (capex)"], ["fcf", "Arus kas bebas"], ["div", "Dividen dibayar"]],
};
const gr = (a, b) => (a != null && b != null && b !== 0 ? (a - b) / Math.abs(b) : null);
const cmp = (v, cur) => (v == null ? "–" : big(v, cur).replace(/^Rp|^[A-Z]{3} /, ""));
const curLab = (cur) => (!cur || cur === "IDR" ? "rupiah" : esc(cur));
const noFs = (s) => `<div class="callout">Laporan keuangan <b>${s.ticker}</b> belum tersedia. Datanya diambil dari Yahoo Finance bertahap (saham dengan nilai transaksi terbesar lebih dulu) untuk saham dengan nilai transaksi ≥ Rp1 M/hari; sebagian saham memang tidak punya laporan di Yahoo.</div>`;
function fsBlock(B, part, cur, fr) {
  const P = B.p, n = P.length, lagY = fr === "q" ? 4 : 1;
  const rows = FSL[part].filter(([k]) => B[k] && B[k].some((v) => v != null));
  if (!rows.length) return `<span class="mut small">Tidak ada data.</span>`;
  return `<div class="tw"><table><thead><tr><th></th>${P.map((p) => `<th class="r">${p}</th>`).join("")}<th class="r" title="${fr === "q" ? "Kuartal terakhir dibanding kuartal yang sama tahun lalu" : "Tahun terakhir dibanding tahun sebelumnya"}">YoY</th></tr></thead><tbody>
    ${rows.map(([k, lab]) => { const a = B[k], y = n > lagY ? gr(a[n - 1], a[n - 1 - lagY]) : null, bad = k === "intx" || k === "tax" || k === "debt" || k === "tl";
      return `<tr class="${k === "ni" || k === "rev" || k === "fcf" || k === "eq" ? "b" : ""}"><td>${lab}</td>${a.map((v) => `<td class="r ${v < 0 && !["capex", "div", "intx", "tax"].includes(k) ? "down" : ""}">${k === "eps" ? (v == null ? "–" : num(v, Math.abs(v) < 10 ? 2 : 0)) : cmp(v, cur)}</td>`).join("")}
        <td class="r ${y == null ? "mut" : cls(bad ? -y : y)}">${y == null || Math.abs(y) > 20 ? "–" : pct(y, 0)}</td></tr>`; }).join("")}</tbody></table></div>`;
}
function fsRatios(B, fr) {
  const P = B.p, k = fr === "q" ? 4 : 1, g = (x, i) => (B[x] ? B[x][i] : null);
  const R = [
    ["Margin kotor", (i) => (g("gp", i) != null && g("rev", i) > 0 ? g("gp", i) / g("rev", i) : null), "p"],
    ["Margin operasi", (i) => (g("op", i) != null && g("rev", i) > 0 ? g("op", i) / g("rev", i) : null), "p"],
    ["Margin laba bersih", (i) => (g("ni", i) != null && g("rev", i) > 0 ? g("ni", i) / g("rev", i) : null), "p"],
    [fr === "q" ? "ROE (disetahunkan)" : "ROE", (i) => (g("ni", i) != null && g("eq", i) > 0 ? (g("ni", i) * k) / g("eq", i) : null), "p"],
    [fr === "q" ? "ROA (disetahunkan)" : "ROA", (i) => (g("ni", i) != null && g("ta", i) > 0 ? (g("ni", i) * k) / g("ta", i) : null), "p"],
    ["Utang / ekuitas", (i) => (g("debt", i) != null && g("eq", i) > 0 ? g("debt", i) / g("eq", i) : null), "x"],
    ["Rasio lancar", (i) => (g("ca", i) != null && g("cl", i) > 0 ? g("ca", i) / g("cl", i) : null), "x"],
    ["Arus kas operasi / laba", (i) => (g("ocf", i) != null && g("ni", i) > 0 ? g("ocf", i) / g("ni", i) : null), "x"],
    ["Payout dividen", (i) => (g("div", i) != null && g("ni", i) > 0 ? -g("div", i) / g("ni", i) : null), "p"],
  ].filter(([, f]) => P.some((_, i) => f(i) != null));
  if (!R.length) return `<span class="mut small">Tidak ada data.</span>`;
  return `<div class="tw"><table><thead><tr><th></th>${P.map((p) => `<th class="r">${p}</th>`).join("")}</tr></thead><tbody>
    ${R.map(([lab, f, t]) => `<tr><td>${lab}</td>${P.map((_, i) => { const v = f(i); return `<td class="r">${v == null || !isFinite(v) || Math.abs(v) > 50 ? "–" : t === "p" ? pr(v) : num(v, 2) + "x"}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function fsSummary(s, fs, f) {
  const cur = fs.cur, A = fs.a, Q = fs.q, out = [];
  const add = (sgn, t) => out.push(`<li class="${sgn > 0 ? "up" : sgn < 0 ? "down" : ""}"><span>${sgn > 0 ? "▲" : sgn < 0 ? "▼" : "●"}</span><div>${t}</div></li>`);
  if (A && A.rev) {
    const n = A.p.length, r = A.rev, y = gr(r[n - 1], r[n - 2]), i0 = r.findIndex((v) => v > 0), yrs = n - 1 - i0;
    const cg = i0 >= 0 && yrs >= 2 && r[n - 1] > 0 ? Math.pow(r[n - 1] / r[i0], 1 / yrs) - 1 : null;
    if (r[n - 1] != null) add(y, `Pendapatan ${A.p[n - 1]} <b>${big(r[n - 1], cur)}</b>${y != null ? `, ${y >= 0 ? "naik" : "turun"} <b>${pct(Math.abs(y), 0).replace("+", "")}</b> dari tahun sebelumnya` : ""}${cg != null ? `; rata-rata tumbuh ${pr(cg, 1)} per tahun sejak ${A.p[i0]}` : ""}.`);
  }
  if (A && A.ni) {
    const n = A.p.length, ni = A.ni, y = gr(ni[n - 1], ni[n - 2]), m = A.rev && A.rev[n - 1] > 0 ? ni[n - 1] / A.rev[n - 1] : null, mp = A.rev && A.rev[n - 2] > 0 && ni[n - 2] != null ? ni[n - 2] / A.rev[n - 2] : null;
    if (ni[n - 1] != null) add(ni[n - 1] < 0 ? -1 : y, `Laba bersih ${A.p[n - 1]} <b>${big(ni[n - 1], cur)}</b>${ni[n - 1] < 0 ? " (rugi)" : y != null && ni[n - 2] > 0 ? `, ${y >= 0 ? "naik" : "turun"} <b>${pct(Math.abs(y), 0).replace("+", "")}</b>` : ""}${m != null ? `; margin bersih ${pr(m)}${mp != null ? ` (tahun sebelumnya ${pr(mp)})` : ""}` : ""}.`);
  }
  if (Q && Q.rev) {
    const n = Q.p.length, yr = n > 4 ? gr(Q.rev[n - 1], Q.rev[n - 5]) : null, yn = n > 4 && Q.ni ? gr(Q.ni[n - 1], Q.ni[n - 5]) : null;
    if (yr != null || yn != null) add(yn != null ? yn : yr, `Kuartal terakhir (${Q.p[n - 1]}) dibanding ${Q.p[n - 5]}: pendapatan ${yr == null ? "–" : `<b>${pct(yr, 0)}</b>`}, laba bersih ${yn == null || Math.abs(yn) > 20 ? "–" : `<b>${pct(yn, 0)}</b>`}.`);
    if (n >= 4 && Q.ni && Q.ni.slice(-4).every((v) => v != null) && Q.rev.slice(-4).every((v) => v != null)) {
      const tr = Q.rev.slice(-4).reduce((a, b) => a + b, 0), tn = Q.ni.slice(-4).reduce((a, b) => a + b, 0);
      add(0, `12 bulan terakhir (${Q.p[n - 4]}–${Q.p[n - 1]}): pendapatan <b>${big(tr, cur)}</b>, laba bersih <b>${big(tn, cur)}</b>.`);
    }
  }
  const L = A || Q;
  if (L) {
    const n = L.p.length, eq = L.eq && L.eq[n - 1], dt = L.debt && L.debt[n - 1], cs = L.cash && L.cash[n - 1];
    if (eq > 0 && dt != null) { const der = dt / eq; add(der > 1.5 ? -1 : der < 0.5 ? 1 : 0, `Utang ${big(dt, cur)} = <b>${num(der, 2)}x ekuitas</b>${cs != null ? `; kas ${big(cs, cur)}, jadi posisi ${cs >= dt ? `<b>kas bersih ${big(cs - dt, cur)}</b>` : `utang bersih ${big(dt - cs, cur)}`}` : ""}.`); }
  }
  if (A && A.ocf && A.ni) {
    const n = A.p.length, o = A.ocf[n - 1], ni = A.ni[n - 1];
    if (o != null && ni > 0) add(o / ni >= 0.8 ? 1 : -1, `Arus kas operasi ${big(o, cur)} = <b>${num(o / ni, 2)}x laba bersih</b>${o / ni < 0.8 ? " — laba belum banyak berubah jadi kas" : " — laba didukung kas"}.`);
    if (A.fcf) { const fc = A.fcf.filter((v) => v != null), pos = fc.filter((v) => v > 0).length; if (fc.length >= 2) add(pos === fc.length ? 1 : pos === 0 ? -1 : 0, `Arus kas bebas positif di <b>${pos} dari ${fc.length}</b> tahun terakhir.`); }
  }
  if (A && A.ni && A.eq) { const n = A.p.length; if (A.ni[n - 1] != null && A.eq[n - 1] > 0) { const roe = A.ni[n - 1] / A.eq[n - 1]; add(roe >= 0.15 ? 1 : roe < 0.08 ? -1 : 0, `ROE ${A.p[n - 1]} <b>${pr(roe)}</b> (laba bersih ÷ ekuitas akhir tahun).`); } }
  return out.length ? `<ul class="fsum">${out.join("")}</ul>` : `<span class="mut">Tidak cukup data untuk ringkasan.</span>`;
}
function tabFs(s, f, fs) {
  if (!fs || (!fs.a && !fs.q)) return `<div class="grid g21"><div class="stack">${noFs(s)}</div><div class="stack">${modelBox(s)}</div></div>`;
  const fr = S.fsfr === "q" && fs.q ? "q" : fs.a ? "a" : "q", B = fs[fr], cur = fs.cur || (f && f.cur) || "IDR";
  return `<div class="filters"><button data-fsfr="a" class="${fr === "a" ? "on" : ""}" ${fs.a ? "" : "disabled"}>Tahunan</button><button data-fsfr="q" class="${fr === "q" ? "on" : ""}" ${fs.q ? "" : "disabled"}>Kuartalan</button>
      <span class="mut small">angka dalam ${curLab(cur)} (jt = juta, M = miliar, T = triliun) · sumber: Yahoo Finance${f && f.t ? " · diambil " + esc(f.t) : ""}</span><button class="btn sm" data-dtab="ee" style="margin-left:auto">Lihat proyeksi (EE) →</button></div>
    <div class="grid g21"><div class="stack">
      <div class="panel"><h3>Laba Rugi</h3><div class="pb">${fsBlock(B, "is", cur, fr)}</div></div>
      <div class="panel"><h3>Neraca <span class="fn">posisi akhir periode</span></h3><div class="pb">${fsBlock(B, "bs", cur, fr)}</div></div>
      <div class="panel"><h3>Arus Kas</h3><div class="pb">${fsBlock(B, "cf", cur, fr)}${fr === "q" ? `<div class="note">Arus kas kuartalan sering tidak tersedia di Yahoo untuk saham BEI.</div>` : ""}</div></div>
    </div><div class="stack">
      <div class="panel"><h3>Ringkasan <span class="fn">dibuat otomatis dari angka laporan</span></h3><div class="pb">${fsSummary(s, fs, f)}</div></div>
      <div class="panel"><h3>Tren Rasio <span class="fn">${fr === "q" ? "kuartalan" : "tahunan"}</span></h3><div class="pb">${fsRatios(B, fr)}</div></div>
      ${modelBox(s)}
    </div></div>`;
}
/* ---- proyeksi: tren pertumbuhan historis memudar ke pertumbuhan jangka panjang, margin rata-rata 3 tahun ---- */
function eeBase(fs) {
  const A = fs.a; if (!A || !A.rev) return null;
  const idx = A.p.map((_, i) => i).filter((i) => A.rev[i] != null && A.rev[i] > 0);
  if (!idx.length) return null;
  const L = idx[idx.length - 1], F0 = idx[0], yrs = +A.p[L] - +A.p[F0];
  let g = yrs >= 1 ? Math.pow(A.rev[L] / A.rev[F0], 1 / yrs) - 1 : 0.08;
  const ms = idx.slice(-3).map((i) => (A.ni && A.ni[i] != null ? A.ni[i] / A.rev[i] : null)).filter((v) => v != null);
  return { L, year: +A.p[L], rev: A.rev[L], g: Math.max(-0.1, Math.min(0.25, g)), m: ms.length ? Math.max(-0.5, Math.min(0.8, ms.reduce((a, b) => a + b, 0) / ms.length)) : null };
}
function eeAssump(t, b) { const o = (store.get("fc", {}))[t] || {}; return { g: o.g ?? Math.round(b.g * 1000) / 1000, tg: o.tg ?? 0.06, m: o.m ?? (b.m == null ? null : Math.round(b.m * 1000) / 1000), auto: !Object.keys(o).length }; }
function eeProj(b, a, dg = 0, mk = 1, sh) {
  const out = []; let r = b.rev;
  for (let k = 1; k <= 3; k++) { const g = a.g + (a.tg - a.g) * (k - 1) / 3 + dg; r *= 1 + g; const m = a.m * mk, ni = r * m; out.push({ y: b.year + k, g, rev: r, m, ni, eps: sh ? ni / sh : null }); }
  return out;
}
const REC = { strong_buy: "Beli kuat", buy: "Beli", hold: "Tahan", underperform: "Di bawah pasar", sell: "Jual" };
function eeBars(lab, hist, fc, lo, hi, cur) {
  const vals = hist.map((h) => h.v).concat(fc.map((x) => x.v), hi.map((x) => x.v)).filter((v) => v != null);
  const mx = Math.max(1, ...vals.map(Math.abs)), mn = Math.min(0, ...vals);
  const H = (v) => (Math.abs(v) / (mx - Math.min(0, mn))) * 100;
  const col = (p, v, cls2, w) => `<div class="bc ${cls2}"><div class="bw">${w || ""}<i style="height:${v == null ? 0 : H(v)}%;${v < 0 ? "background:" + COL.down : ""}"></i></div><span>${p}</span><b>${v == null ? "–" : cmp(v, cur)}</b></div>`;
  return `<div class="bars"><div class="bt">${lab}</div><div class="bcs">${hist.map((h) => col(h.p, h.v, "")).join("")}${fc.map((x, i) => col(x.p, x.v, "fc", lo[i] && hi[i] && hi[i].v > 0 ? `<em style="bottom:${H(Math.max(0, lo[i].v))}%;height:${Math.max(0, H(hi[i].v) - H(Math.max(0, lo[i].v)))}%"></em>` : "")).join("")}</div></div>`;
}
function tabEe(s, f, fs) {
  if (!fs || !fs.a) return `<div class="grid g21"><div class="stack">${noFs(s)}</div><div class="stack">${modelBox(s)}</div></div>`;
  const b = eeBase(fs), cur = fs.cur || (f && f.cur) || "IDR", fx = fxOf(cur);
  if (!b || b.m == null) return `<div class="grid g21"><div class="stack"><div class="callout">Data pendapatan atau laba ${s.ticker} tidak cukup untuk membuat proyeksi.</div></div><div class="stack">${modelBox(s)}</div></div>`;
  const a = eeAssump(s.ticker, b), sh = f && f.shares, px = s.last;
  const sc = { bear: eeProj(b, a, -0.05, 0.85, sh), base: eeProj(b, a, 0, 1, sh), bull: eeProj(b, a, 0.05, 1.15, sh) };
  const A = fs.a, hist = A.p.map((p, i) => ({ p, rev: A.rev[i], ni: A.ni ? A.ni[i] : null, eps: A.eps ? A.eps[i] : sh && A.ni && A.ni[i] != null ? A.ni[i] / sh : null })).filter((h) => h.rev != null);
  const items = (S.fund && S.fund.items) || {}, peers = S.d.stocks.filter((x) => x.sector === s.sector && items[x.ticker]).map((x) => items[x.ticker].pe).filter((v) => v > 0 && v <= 100);
  const secPe = peers.length >= 4 ? median(peers) : null;
  const epsIdr = (e) => (e == null || fx == null ? null : e * fx);
  const per = (e) => { const v = epsIdr(e); return v == null ? "–" : v <= 0 ? "negatif" : num(px / v, 1) + "x"; };
  const Q = fs.q; let ttm = null;
  if (Q && Q.rev && Q.ni && Q.p.length >= 4 && Q.rev.slice(-4).every((v) => v != null) && Q.ni.slice(-4).every((v) => v != null) && Q.end[Q.end.length - 1] > A.end[b.L]) {
    ttm = { p: "12 bln s/d " + Q.p[Q.p.length - 1], rev: Q.rev.slice(-4).reduce((x, y) => x + y, 0), ni: Q.ni.slice(-4).reduce((x, y) => x + y, 0) };
    ttm.g = gr(ttm.rev, b.rev) * (12 / Math.max(1, Math.round((new Date(Q.end[Q.end.length - 1]) - new Date(A.end[b.L])) / (30.4 * 864e5))));
  }
  const inp = (id, lab, v) => `<label>${lab}<input id="e-${id}" type="number" step="0.5" min="-50" max="80" value="${Math.round(v * 1000) / 10}"></label>`;
  const cagrE = (p) => { const e0 = hist[hist.length - 1].ni, e3 = p[2].ni; return e0 > 0 && e3 > 0 ? Math.pow(e3 / e0, 1 / 3) - 1 : null; };
  const conIdr = cur === "IDR";
  return `<div class="grid g21"><div class="stack">
    <div class="panel"><h3>Proyeksi 3 Tahun <span class="fn">skenario dasar · angka dalam ${curLab(cur)}</span></h3><div class="pb">
      <div class="tw"><table><thead><tr><th></th>${hist.slice(-3).map((h) => `<th class="r">${h.p}</th>`).join("")}${ttm ? `<th class="r" title="${ttm.p}">12 bln terakhir</th>` : ""}${sc.base.map((x) => `<th class="r amb">${x.y}P</th>`).join("")}</tr></thead><tbody>
        <tr class="b"><td>Pendapatan</td>${hist.slice(-3).map((h) => `<td class="r">${cmp(h.rev, cur)}</td>`).join("")}${ttm ? `<td class="r">${cmp(ttm.rev, cur)}</td>` : ""}${sc.base.map((x) => `<td class="r fcv">${cmp(x.rev, cur)}</td>`).join("")}</tr>
        <tr><td>Pertumbuhan</td>${hist.slice(-3).map((h, i, arr) => { const p = hist[hist.length - 3 + i - 1]; const g = p ? gr(h.rev, p.rev) : null; return `<td class="r ${cls(g)}">${g == null ? "–" : pct(g, 0)}</td>`; }).join("")}${ttm ? `<td class="r mut">–</td>` : ""}${sc.base.map((x) => `<td class="r fcv ${cls(x.g)}">${pct(x.g, 1)}</td>`).join("")}</tr>
        <tr class="b"><td>Laba bersih</td>${hist.slice(-3).map((h) => `<td class="r ${h.ni < 0 ? "down" : ""}">${cmp(h.ni, cur)}</td>`).join("")}${ttm ? `<td class="r">${cmp(ttm.ni, cur)}</td>` : ""}${sc.base.map((x) => `<td class="r fcv ${x.ni < 0 ? "down" : ""}">${cmp(x.ni, cur)}</td>`).join("")}</tr>
        <tr><td>Margin bersih</td>${hist.slice(-3).map((h) => `<td class="r">${h.ni != null && h.rev > 0 ? pr(h.ni / h.rev) : "–"}</td>`).join("")}${ttm ? `<td class="r">${ttm.rev > 0 ? pr(ttm.ni / ttm.rev) : "–"}</td>` : ""}${sc.base.map((x) => `<td class="r fcv">${pr(x.m)}</td>`).join("")}</tr>
        <tr><td>EPS</td>${hist.slice(-3).map((h) => `<td class="r">${h.eps == null ? "–" : num(h.eps, Math.abs(h.eps) < 10 ? 2 : 0)}</td>`).join("")}${ttm ? `<td class="r">${sh ? num(ttm.ni / sh, Math.abs(ttm.ni / sh) < 10 ? 2 : 0) : "–"}</td>` : ""}${sc.base.map((x) => `<td class="r fcv b">${x.eps == null ? "–" : num(x.eps, Math.abs(x.eps) < 10 ? 2 : 0)}</td>`).join("")}</tr>
        <tr><td>PER pada harga ${num(px)}</td>${hist.slice(-3).map((h) => `<td class="r mut">${per(h.eps)}</td>`).join("")}${ttm ? `<td class="r mut">${sh ? per(ttm.ni / sh) : "–"}</td>` : ""}${sc.base.map((x) => `<td class="r fcv">${per(x.eps)}</td>`).join("")}</tr>
      </tbody></table></div>
      <div class="grid g2" style="margin-top:10px">${eeBars("Pendapatan", hist.slice(-4).map((h) => ({ p: h.p, v: h.rev })), sc.base.map((x) => ({ p: x.y + "P", v: x.rev })), sc.bear.map((x) => ({ v: x.rev })), sc.bull.map((x) => ({ v: x.rev })), cur)}
        ${eeBars("Laba bersih", hist.slice(-4).map((h) => ({ p: h.p, v: h.ni })), sc.base.map((x) => ({ p: x.y + "P", v: x.ni })), sc.bear.map((x) => ({ v: x.ni })), sc.bull.map((x) => ({ v: x.ni })), cur)}</div>
      <div class="note">Batang terang = proyeksi skenario dasar; garis tipis di atasnya = rentang skenario pesimis–optimis. ${ttm && ttm.g != null ? `Pendapatan 12 bulan terakhir tumbuh sekitar ${pr(ttm.g, 0)} disetahunkan dari ${b.year} — bandingkan dengan asumsi tahun pertama ${pr(a.g, 1)}.` : ""}</div>
    </div></div>
    <div class="panel"><h3>Skenario</h3><div class="pb"><div class="tw"><table><thead><tr><th>Skenario</th><th>Asumsi</th><th class="r">EPS ${b.year + 1}</th><th class="r">EPS ${b.year + 3}</th><th class="r">Laba tumbuh/thn</th><th class="r">PER ${b.year + 1} di harga sekarang</th><th class="r" title="EPS ${b.year + 1} × PER median sektor">Harga implisit ${b.year + 1}</th><th class="r">vs harga</th></tr></thead><tbody>
      ${[["bear", "Pesimis", "tumbuh −5 poin, margin −15%"], ["base", "Dasar", "asumsi di kanan"], ["bull", "Optimis", "tumbuh +5 poin, margin +15%"]].map(([k, lab, d]) => { const p = sc[k], e1 = epsIdr(p[0].eps), imp = e1 > 0 && secPe ? e1 * secPe : null, cg = cagrE(p);
        return `<tr class="${k === "base" ? "hl" : ""}"><td class="b">${lab}</td><td class="mut small">${d}</td><td class="r">${p[0].eps == null ? "–" : num(p[0].eps, Math.abs(p[0].eps) < 10 ? 2 : 0)}</td><td class="r">${p[2].eps == null ? "–" : num(p[2].eps, Math.abs(p[2].eps) < 10 ? 2 : 0)}</td>
          <td class="r ${cls(cg)}">${cg == null ? "–" : pr(cg, 1)}</td><td class="r">${per(p[0].eps)}</td><td class="r b">${imp ? num(imp) : "–"}</td><td class="r ${cls(imp ? imp / px - 1 : null)}">${imp ? pct(imp / px - 1, 0) : "–"}</td></tr>`; }).join("")}</tbody></table></div>
      <div class="note">${secPe ? `Harga implisit = EPS ${b.year + 1} (rupiah) × PER median sektor ${esc(s.sector)} ${num(secPe, 1)}x.` : "PER median sektor belum cukup data, harga implisit tidak dihitung."}${cur !== "IDR" ? ` Laporan dalam ${esc(cur)}; EPS dikonversi ke rupiah dengan kurs ${fx ? num(fx) : "–"} untuk PER dan harga implisit.` : ""}</div></div></div>
  </div><div class="stack">
    <div class="panel"><h3>Asumsi <span class="fn">ubah lalu tekan Enter</span></h3><div class="pb">
      <div class="form">${inp("g", `Pertumbuhan pendapatan tahun 1 (%)${a.auto ? " · otomatis" : ""}`, a.g)}${inp("tg", "Pertumbuhan jangka panjang (%)", a.tg)}${inp("m", "Margin laba bersih (%)", a.m)}</div>
      <div style="margin-top:10px"><button class="btn" id="e-reset">Kembalikan ke bawaan</button></div>
      <p class="note">Bawaan: pertumbuhan tahun 1 = rata-rata pertumbuhan pendapatan ${hist[0].p}–${b.year} (${pr(b.g, 1)}, dibatasi −10% s/d 25%), lalu memudar ke pertumbuhan jangka panjang 6% di tahun 3. Margin = rata-rata margin bersih 3 tahun terakhir (${pr(b.m, 1)}). Jumlah saham dianggap tetap. Tersimpan per saham di browser ini.</p></div></div>
    <div class="panel"><h3>Konsensus Analis <span class="fn">Yahoo Finance</span></h3><div class="pb">
      ${f && (f.tgt || f.n_an) ? `<dl class="kv small"><dt>Jumlah analis</dt><dd>${f.n_an ? num(f.n_an) : "–"}</dd><dt>Rekomendasi rata-rata</dt><dd>${esc(REC[f.rec_k] || f.rec_k || "–")}${f.rec_m ? ` (${num(f.rec_m, 1)}; 1 = beli kuat, 5 = jual)` : ""}</dd>
        <dt>Target harga rata-rata</dt><dd class="b">${f.tgt ? num(f.tgt) + ` <span class="${cls(f.tgt / px - 1)}">${pct(f.tgt / px - 1, 0)}</span>` : "–"}</dd><dt>Target terendah – tertinggi</dt><dd>${f.tgt_lo ? num(f.tgt_lo) : "–"} – ${f.tgt_hi ? num(f.tgt_hi) : "–"}</dd>
        <dt>EPS 12 bln ke depan (analis)</dt><dd>${conIdr && f.feps ? num(f.feps, Math.abs(f.feps) < 10 ? 2 : 0) : "–"}</dd><dt>EPS ${b.year + 1} (model ini, dasar)</dt><dd>${sc.base[0].eps == null ? "–" : num(sc.base[0].eps, Math.abs(sc.base[0].eps) < 10 ? 2 : 0)}</dd></dl>
        <div class="note">Konsensus bisa tertinggal dan jumlah analis untuk saham BEI sering sedikit. Periode EPS analis (12 bulan ke depan) tidak persis sama dengan tahun buku.</div>`
        : `<span class="mut small">Tidak ada data konsensus analis untuk ${s.ticker} di Yahoo.</span>`}</div></div>
    <div class="callout">Proyeksi ini ekstrapolasi sederhana dari tren laporan keuangan, bukan perkiraan analis atau riset emiten. Tidak memperhitungkan siklus komoditas, aksi korporasi, atau perubahan bisnis. Pakai untuk melihat "kalau tren berlanjut, kira-kira labanya berapa", bukan sebagai target harga.</div>
    ${modelBox(s)}
  </div></div>`;
}

/* ================= DETAIL (ticker <GO>) ================= */
async function loadSeries(t) {
  const r = await fetch(`data/s/${t}.json?v=${encodeURIComponent(S.d.meta.generated_at)}`);
  if (!r.ok) throw new Error("HTTP " + r.status);
  let j = await r.json();
  if (j.enc) j = await decryptEnv(j, S.key);
  return j;
}
const dHead = (s) => `
  <div class="dhead"><span class="tk">${s.ticker}</span><button class="star ${isWatched(s.ticker) ? "on" : ""}" data-star="${s.ticker}" title="Tambah / hapus dari watchlist">${isWatched(s.ticker) ? "★" : "☆"}</button><span>${esc(s.name)}</span><span class="mut">${esc(s.sector)}</span>
    <span class="mid">${num(s.last)}</span><span class="${cls(s.chg_pct)}">${s.chg > 0 ? "+" : ""}${num(s.chg)} (${pct(s.chg_pct)})</span>${sig(s.signal)}
    <span class="mut">komposit</span><b style="color:${scoreColor(s.scores.composite)}">${num(s.scores.composite)}</b>
    <button class="close" data-close>✕ ESC</button></div>
  <div class="dtabs">${DTABS.map(([id, code, lab]) => `<button data-dtab="${id}" class="${S.dtab === id ? "on" : ""}" title="${lab}"><b>${code}</b> <span class="hide-m">${lab}</span></button>`).join("")}
    <span class="mut small hide-m" style="margin-left:auto">perintah: <b>${s.ticker} FS</b> · <b>${s.ticker} EE</b> · <b>${s.ticker} DCF</b></span>
    <button class="btn sm" data-dcomp="${s.ticker}" title="Bandingkan dengan saham lain">⇄ Bandingkan</button><button class="btn sm" data-djr="${s.ticker}" title="Catat pembelian di jurnal">+ Jurnal</button></div>`;
async function openDetail(t, push = true, tab = "gp") {
  const s = stock(t); if (!s) { toast("Ticker tidak ditemukan: " + t); return; }
  const hash = "t-" + t + (tab !== "gp" ? "." + tab : "");
  if (push && location.hash !== "#" + hash) { location.hash = hash; return; }
  S.ticker = t; S.dtab = tab;
  disposeCharts(S.dcharts);
  const el = $("#detail"); el.hidden = false; document.body.style.overflow = "hidden";
  if (tab !== "gp") {
    el.innerHTML = dHead(s) + `<div id="d-body"><span class="mut">Memuat…</span></div>`;
    el.scrollTop = 0;
    const f = tab === "cn" ? null : ((await loadFund()).items || {})[t];
    const fs = tab === "fs" || tab === "ee" ? await loadFs(t) : null;
    if (S.ticker !== t || S.dtab !== tab) return;
    $("#d-body").innerHTML = tab === "des" ? tabDes(s, f) : tab === "fa" ? tabFa(s, f) : tab === "fs" ? tabFs(s, f, fs) : tab === "ee" ? tabEe(s, f, fs) : tab === "val" ? tabVal(s, f) : tabCn(s);
    return;
  }
  if (!s.series) {   // data chart per saham dimuat saat dibuka
    const head = (msg) => `<div class="dhead"><span class="tk">${s.ticker}</span><span>${esc(s.name)}</span><span class="mut">${msg}</span><button class="close" data-close>✕ ESC</button></div>`;
    el.innerHTML = head("Memuat chart…");
    try { s.series = await loadSeries(t); } catch (e) { if (S.ticker === t) el.innerHTML = head("Gagal memuat data chart (" + esc(e.message) + ")"); return; }
    if (S.ticker !== t || S.dtab !== "gp") return;
  }
  const L = s.levels, n = s.series.c.length, dates = S.d.dates.slice(-n);
  const buy = s.signal === "BUY" || s.signal === "STRONG BUY";
  const p = Object.assign(portDefaults(), store.get("port", {}));
  const rps = L.entry_high - L.sl;
  const lots = rps > 0 ? Math.max(0, Math.floor(Math.min((p.equity * p.risk / 100) / rps, (p.equity * p.maxw / 100) / L.entry_high) / 100)) : 0;
  el.innerHTML = dHead(s) + `
  <div class="grid g21">
    <div class="stack">
      <div class="panel"><h3>Chart Harian + Level Trade <span class="fn">candle · MA20/50/200 · volume diwarnai arah flow</span></h3><div class="pb">
        <div class="chart lg" id="d-px"><div class="legend" id="d-lg"></div></div></div></div>
      <div class="grid g2">
        <div class="panel"><h3>Kumulatif Net Flow (Rp M)</h3><div class="pb"><div class="chart sm" id="d-nf"></div></div></div>
        <div class="panel"><h3>Riwayat Skor Komposit <span class="fn">tanpa sentimen</span></h3><div class="pb"><div class="chart sm" id="d-sc"></div></div></div>
      </div>
      <div class="panel"><h3>Berita Terkait</h3><div class="pb">${S.d.news.filter((x) => x.tickers.includes(t)).slice(0, 8).map(newsItem).join("") || `<span class="mut">Tidak ada berita 14 hari terakhir.</span>`}</div></div>
    </div>
    <div class="stack">
      <div class="panel"><h3>Rencana Trade</h3><div class="pb">
        ${buy ? "" : `<div class="callout" style="margin-bottom:8px">Status <b>${s.signal}</b>: level di bawah hanya acuan — ${s.signal === "EXIT" ? "keluar / jangan masuk dulu." : s.signal === "REDUCE" ? "kurangi posisi / perketat stop." : s.signal === "AVOID" ? "tidak likuid untuk model ini." : "tunggu konfirmasi sinyal BUY."}</div>`}
        <div class="lvl">
          <span class="sw" style="background:${COL.up}"></span><span>Target 2 (${S.d.config.signal.tp2_r}R)</span><b class="up">${num(L.tp2)}</b>
          <span class="sw" style="background:${COL.up}"></span><span>Target 1 (${S.d.config.signal.tp1_r}R)</span><b class="up">${num(L.tp1)}</b>
          <span class="sw" style="background:${COL.s1}"></span><span>Zona beli</span><b>${num(L.entry_low)} – ${num(L.entry_high)}</b>
          <span class="sw" style="background:#999"></span><span>Trailing stop (chandelier)</span><b>${num(L.trail)}</b>
          <span class="sw" style="background:${COL.down}"></span><span>Stop loss (close) ${pct(L.sl_pct)}</span><b class="down">${num(L.sl)}</b>
        </div>
        <dl class="kv small" style="margin-top:8px"><dt>ATR-14</dt><dd>${num(L.atr)} (${pct(L.atr_pct, 1).replace("+", "")})</dd><dt>R:R ke TP1 / TP2</dt><dd>${num(L.rr1, 1)} / ${num(L.rr2, 1)}</dd>
          <dt>Ukuran @ modal ${rupiah(p.equity)}, risiko ${p.risk}%</dt><dd class="amb b">${num(lots)} lot ≈ ${rupiah(lots * 100 * L.entry_high)}</dd></dl>
        ${s.notes.map((x) => `<div class="callout" style="margin-top:6px">${esc(x)}</div>`).join("")}
      </div></div>
      ${s.checks && s.checks.length ? `<div class="panel"><h3>Syarat Beli <span class="fn">${s.checks.filter((c) => c.ok).length}/${s.checks.length} lolos · sama dengan aturan backtest</span></h3><div class="pb small">
        ${s.checks.map((c) => `<div style="display:flex;gap:8px;padding:2px 0"><b class="${c.ok ? "up" : "down"}" style="width:12px">${c.ok ? "✓" : "✗"}</b><span style="flex:1" class="${c.ok ? "" : "b"}">${esc(c.t)}</span><span class="mut">${esc(c.v || "")}</span></div>`).join("")}
      </div></div>` : ""}
      <div class="panel"><h3>Komponen Skor</h3><div class="pb comp-bars">
        ${[["Flow", "flow"], ["Momentum", "momentum"], ["Trend", "trend"], ["Sentimen", "sentiment"], ["Timing", "timing"]].filter(([, k]) => k !== "timing" || useTiming()).map(([l, k]) =>
          `<span class="mut">${l}</span><div class="bar"><span style="width:${s.scores[k]}%;background:${scoreColor(s.scores[k])}"></span></div><b class="r">${num(s.scores[k])}</b>`).join("")}
      </div></div>
      <div class="panel"><h3>Kenapa?</h3><div class="pb">${s.reasons.map(chip).join("") || `<span class="mut">–</span>`}</div></div>
      <div class="panel"><h3>Data Kunci</h3><div class="pb"><dl class="kv small">
        <dt>Flow 1H / 5H / 20H</dt><dd><span class="${cls(s.flow.nf1)}">${rp(s.flow.nf1)}</span> / <span class="${cls(s.flow.nf5)}">${rp(s.flow.nf5)}</span> / <span class="${cls(s.flow.nf20)}">${rp(s.flow.nf20)}</span></dd>
        ${s.flow.fnet5 != null ? `<dt>Asing 1H / 5H / 20H</dt><dd>${rp(s.flow.fnet1)} / ${rp(s.flow.fnet5)} / ${rp(s.flow.fnet20)}</dd>` : ""}
        ${s.flow.nf60 != null ? `<dt>Flow 60H / hari inflow</dt><dd><span class="${cls(s.flow.nf60)}">${rp(s.flow.nf60)}</span> / ${s.flow.accdays == null ? "–" : num(s.flow.accdays * 100) + "% hari"}</dd>` : ""}
        <dt>Status</dt><dd class="${s.flow.status === "AKUMULASI" ? "up" : s.flow.status === "DISTRIBUSI" ? "down" : ""}">${s.flow.status}</dd>
        <dt>CMF-20 / MFI-14</dt><dd>${num(s.flow.cmf, 2)} / ${num(s.flow.mfi)}</dd><dt>Nilai transaksi / rata-rata 20H</dt><dd>${rp(s.flow.value, false)} / ${rp(s.flow.avg_val20, false)}</dd>
        <dt>RSI-14</dt><dd>${num(s.ind.rsi)}</dd><dt>MA20 / MA50 / MA200</dt><dd>${num(s.ind.ma20)} / ${num(s.ind.ma50)} / ${num(s.ind.ma200)}</dd>
        <dt>Return 1M / 1B / 3B / 12B</dt><dd><span class="${cls(s.ind.ret5)}">${pct(s.ind.ret5)}</span> / <span class="${cls(s.ind.ret21)}">${pct(s.ind.ret21)}</span> / <span class="${cls(s.ind.ret63)}">${pct(s.ind.ret63)}</span> / <span class="${cls(s.ind.ret252)}">${pct(s.ind.ret252)}</span></dd>
        <dt>52W high / low</dt><dd>${num(s.ind.hi52)} / ${num(s.ind.lo52)}</dd>
        <dt>Sentimen</dt><dd>${num(s.scores.sentiment)} (${s.sent.n || 0} berita, ${s.sent.pos || 0}+ / ${s.sent.neg || 0}−)</dd></dl></div></div>
      <div class="panel" id="ai-panel" hidden><h3>AI Brief <span class="fn">Claude</span></h3><div class="pb">
        <button class="btn" id="ai-btn">Buat ringkasan analisis</button><div id="ai-out"></div></div></div>
    </div>
  </div>`;
  // price chart
  const c = mkChart($("#d-px"), S.dcharts, { localization: { priceFormatter: (x) => num(x, 0) } });
  const cs = c.addCandlestickSeries({ upColor: COL.up, downColor: COL.down, borderVisible: false, wickUpColor: COL.up, wickDownColor: COL.down, priceFormat: { type: "price", precision: 0, minMove: 1 } });
  const ohlc = dates.map((tm, i) => ({ time: tm, open: s.series.o[i], high: s.series.h[i], low: s.series.l[i], close: s.series.c[i] })).filter((x) => x.close != null);
  cs.setData(ohlc);
  [["ma20", COL.s1, 0], ["ma50", COL.s2, 0], ["ma200", COL.s3, 2]].forEach(([k, col, st]) => {
    c.addLineSeries({ color: col, lineWidth: 1, lineStyle: st, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }).setData(ser(dates, s.series[k]));
  });
  const vs = c.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
  c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
  vs.setData(dates.map((tm, i) => ({ time: tm, value: s.series.v[i] || 0, color: (s.series.nf[i] || 0) >= 0 ? "rgba(46,189,107,.45)" : "rgba(240,71,79,.45)" })));
  const pl = (price, color, title, style = 2) => price && cs.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
  pl(L.tp2, COL.up, "TP2"); pl(L.tp1, COL.up, "TP1"); pl(L.entry_low, COL.s1, "BUY", 1); pl(L.sl, COL.down, "SL", 0); pl(L.trail, "#999", "TRAIL", 3);
  c.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 130), to: n + 3 });
  const lg = $("#d-lg");
  const setLg = (i) => { lg.innerHTML = `<span class="mut">${dates[i]}</span> O ${num(s.series.o[i])} H ${num(s.series.h[i])} L ${num(s.series.l[i])} C <b>${num(s.series.c[i])}</b> · Vol ${num((s.series.v[i] || 0) / 100)} lot · Flow <span class="${cls(s.series.nf[i])}">${rp(s.series.nf[i])}</span>
    <i style="background:${COL.s1}"></i>MA20<i style="background:${COL.s2}"></i>MA50<i class="dash" style="color:${COL.s3}"></i>MA200`; };
  setLg(n - 1);
  c.subscribeCrosshairMove((q) => { const i = q && q.time ? dates.indexOf(q.time) : -1; setLg(i >= 0 ? i : n - 1); });
  // flow & score charts (sinkron dengan chart harga)
  let cum = 0; const cumv = s.series.nf.map((x) => (cum += x || 0));
  const c2 = mkChart($("#d-nf"), S.dcharts, { localization: { priceFormatter: (x) => num(x, 0) } });
  c2.addBaselineSeries({ baseValue: { type: "price", price: 0 }, topLineColor: COL.up, bottomLineColor: COL.down, topFillColor1: "rgba(46,189,107,.25)", topFillColor2: "rgba(46,189,107,0)",
    bottomFillColor1: "rgba(240,71,79,0)", bottomFillColor2: "rgba(240,71,79,.25)", lineWidth: 2, priceLineVisible: false }).setData(ser(dates, cumv));
  const c3 = mkChart($("#d-sc"), S.dcharts);
  const sc = c3.addLineSeries({ color: COL.s1, lineWidth: 2, priceLineVisible: false });
  sc.setData(ser(dates, s.series.score));
  sc.createPriceLine({ price: S.d.config.signal.buy, color: "#2a6b45", lineWidth: 1, lineStyle: 2, title: "BUY" });
  sc.createPriceLine({ price: S.d.config.signal.exit, color: "#7a2a2e", lineWidth: 1, lineStyle: 2, title: "EXIT" });
  const sync = (src, dsts) => src.timeScale().subscribeVisibleLogicalRangeChange((r) => r && dsts.forEach((d) => d.timeScale().setVisibleLogicalRange(r)));
  sync(c, [c2, c3]);
  c2.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 130), to: n + 3 });
  c3.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 130), to: n + 3 });
  setupAI(s);
}
function closeDetail(push = true) {
  const el = $("#detail");
  if (el.hidden) return;
  disposeCharts(S.dcharts); el.hidden = true; el.innerHTML = ""; document.body.style.overflow = ""; S.ticker = null;
  if (push) { history.pushState(null, "", "#" + S.view); }
  if (!$("#view").innerHTML) renderView();
}

/* ---------------- AI brief (hanya di artifact Claude; otomatis tersembunyi di tempat lain) ---------------- */
async function aiCap() {
  if (S.ai !== null) return S.ai;
  try { S.ai = (window.claude && typeof window.claude.use === "function" ? await window.claude.use("sample") : null) || false; } catch { S.ai = false; }
  return S.ai;
}
async function setupAI(s) {
  const sample = await aiCap();
  if (!sample || S.ticker !== s.ticker) return;
  $("#ai-panel").hidden = false;
  $("#ai-btn").onclick = async () => {
    const out = $("#ai-out"); out.textContent = "Menganalisis…";
    const ctx = { ticker: s.ticker, nama: s.name, sektor: s.sector, harga: s.last, sinyal: s.signal, skor: s.scores, level: s.levels, flow: s.flow, indikator: s.ind,
      alasan: s.reasons.map((r) => r.t), catatan: s.notes, rezim: S.d.market.regime.label, berita: S.d.news.filter((x) => x.tickers.includes(s.ticker)).slice(0, 6).map((x) => x.title),
      mode_data: S.d.meta.mode };
    const prompt = `Kamu analis kuantitatif saham Indonesia. Dari data model berikut (JSON), tulis brief singkat berbahasa Indonesia santai-lugas, maks 140 kata, format:
1) Setup (1 kalimat) 2) Money flow 3) Risiko utama 4) Rencana: entry, stop, target, dan kapan batal (invalidasi).
Jangan mengarang data di luar JSON. ${S.d.meta.mode === "demo" ? "Sebutkan bahwa ini data simulasi." : ""}
${JSON.stringify(ctx)}`;
    try {
      await sample(prompt, { modelTier: "quick", onText: ({ text }) => { out.textContent = text; } });
    } catch (e) {
      out.textContent = e && e.code === "rate_limited" ? "Terlalu sering — coba lagi sebentar." : e && e.code === "not_granted" ? "Izin AI tidak diberikan." : "AI tidak tersedia.";
      if (e && e.code === "not_granted") $("#ai-panel").hidden = true;
    }
  };
}

/* ---------------- command line & events ---------------- */
function runCmd(raw) {
  if (!S.d) return;
  const v = raw.trim().toUpperCase();
  if (!v) return;
  const toks = v.replace(/[<>,]/g, " ").split(/\s+/).filter((x) => x && !["EQUITY", "IJ", "GO"].includes(x));
  const [a, b, c] = toks;
  if (!a) return;
  if ((a === "COMP" || a === "CORR" || a === "BANDING") && toks.length > 1) {
    const ts = toks.slice(1).filter(stock), bad = toks.slice(1).filter((t) => !stock(t));
    if (bad.length) toast("Tidak ditemukan: " + bad.join(", "));
    if (ts.length) store.set("comp", Object.assign(store.get("comp", {}), { t: [...new Set(ts)].slice(0, 6) }));
    closeDetail(false); go("comp"); if (location.hash === "#comp") route(); return;
  }
  if (stock(a) && (b === "COMP" || b === "CORR")) {
    const cc = compCfg(); if (!cc.t.includes(a)) cc.t = cc.t.concat(a).slice(-6); store.set("comp", cc); closeDetail(false); go("comp"); if (location.hash === "#comp") route(); return;
  }
  if (stock(a) && (b === "JRNL" || b === "BUY" || b === "BELI")) { S.jpre = a; closeDetail(false); go("jrnl"); if (location.hash === "#jrnl") route(); return; }
  if ((a === "W" || a === "WATCH") && (b === "ADD" || b === "DEL") && c) {
    if (!stock(c)) { toast("Ticker tidak ditemukan: " + c); return; }
    setWatch(c, b === "ADD"); toast(c + (b === "ADD" ? " masuk watchlist" : " dihapus dari watchlist")); closeDetail(false); go("watch"); if (location.hash === "#watch") route(); return;
  }
  const alias = { WEI: "glob", GLOBAL: "glob", GLCO: "glob", WCRS: "glob", FX: "glob", KOMODITAS: "glob", COMP: "comp", CORR: "comp", BANDING: "comp", JRNL: "jrnl", JURNAL: "jrnl", TRADE: "jrnl", TRADES: "jrnl", EQS: "scr", SCREEN: "scr", SCREENER: "scr", SCR: "scr", LP: "pad", PANEL: "pad", PAD: "pad", LAUNCHPAD: "pad", MAP: "map", IMAP: "map", HEATMAP: "map", W: "watch", WATCH: "watch", WL: "watch", ALRT: "watch", ALERT: "watch", MKT: "mkt", PASAR: "mkt", FLOW: "flow", SIG: "signal", SIGNAL: "signal", SINYAL: "signal", PORT: "porto", PORTO: "porto", NEWS: "news", BERITA: "news", BT: "btest", BTEST: "btest", BACKTEST: "btest", HELP: "help", METODE: "help" };
  if (a === "PORT" && b) {
    const eq = parseFloat(b.replace(/\./g, "")); if (eq > 0) { store.set("port", Object.assign(store.get("port", {}), { equity: eq })); }
  }
  if (alias[a]) { closeDetail(false); go(alias[a]); if (location.hash === "#" + alias[a]) route(); return; }
  if (stock(a)) {
    if (b === "W" || b === "ADD") { setWatch(a, true); toast(a + " masuk watchlist"); }
    openDetail(a, true, { DES: "des", GP: "gp", G: "gp", FA: "fa", RV: "fa", DVD: "fa", DCF: "val", VAL: "val", FS: "fs", LK: "fs", LAPORAN: "fs", EE: "ee", PROYEKSI: "ee", FCST: "ee", FORECAST: "ee", CN: "cn", NEWS: "cn" }[b] || "gp"); return;
  }
  toast("Perintah tidak dikenal: " + a);
}
document.addEventListener("click", (e) => {
  const st = e.target.closest("[data-star]"); if (st) { setWatch(st.dataset.star, !isWatched(st.dataset.star)); if (!$("#detail").hidden) { st.classList.toggle("on", isWatched(st.dataset.star)); st.textContent = isWatched(st.dataset.star) ? "★" : "☆"; } if (S.view === "watch") renderView(true); return; }
  const dt = e.target.closest("[data-dtab]"); if (dt && S.ticker) { openDetail(S.ticker, true, dt.dataset.dtab); return; }
  const mc = e.target.closest("[data-mapc]"); if (mc) { S.mapColor = mc.dataset.mapc; renderView(true); return; }
  const ms = e.target.closest("[data-maps]"); if (ms) { S.mapSize = ms.dataset.maps; renderView(true); return; }
  const ad = e.target.closest("[data-adel]"); if (ad) { store.set("alerts", alerts().filter((r) => String(r.id) !== ad.dataset.adel)); renderView(true); return; }
  if (e.target.closest("#w-addbtn")) { const t = ($("#w-add").value || "").trim().toUpperCase(); if (stock(t)) { setWatch(t, true); renderView(true); } else toast("Ticker tidak ditemukan: " + t); return; }
  if (e.target.closest("#a-addbtn")) { addAlert(); return; }
  const ff = e.target.closest("[data-fsfr]"); if (ff && S.ticker) { S.fsfr = ff.dataset.fsfr; openDetail(S.ticker, false, "fs"); return; }
  if (e.target.closest("#e-reset") && S.ticker) { const o = store.get("fc", {}); delete o[S.ticker]; store.set("fc", o); openDetail(S.ticker, false, "ee"); return; }
  if (e.target.closest("#v-reset") && S.ticker) { store.set("val", {}); const g = store.get("valg", {}); delete g[S.ticker]; store.set("valg", g); openDetail(S.ticker, false, "val"); return; }
  if (e.target.closest("#a-notif")) { if ("Notification" in window) Notification.requestPermission().then(() => renderView(true)); return; }
  if (e.target.closest("#a-clear")) { store.set("alog", []); renderView(true); return; }
  // bandingkan / jurnal
  const dcp = e.target.closest("[data-dcomp]"); if (dcp) { const t = dcp.dataset.dcomp, cc = compCfg(); if (!cc.t.includes(t)) cc.t = cc.t.concat(t).slice(-6); store.set("comp", cc); closeDetail(false); go("comp"); if (location.hash === "#comp") route(); return; }
  const djr = e.target.closest("[data-djr]"); if (djr) { S.jpre = djr.dataset.djr; closeDetail(false); go("jrnl"); if (location.hash === "#jrnl") route(); return; }
  const cdl = e.target.closest("[data-cdel]"); if (cdl) { const cc = compCfg(); cc.t = cc.t.filter((t) => t !== cdl.dataset.cdel); store.set("comp", cc); renderView(true); return; }
  const cw = e.target.closest("[data-cwin]"); if (cw) { const cc = compCfg(); cc.win = +cw.dataset.cwin; store.set("comp", cc); renderView(true); return; }
  if (e.target.closest("#j-add")) { jrAdd(); return; }
  const js = e.target.closest("[data-jsell]"); if (js) { S.jsell = +js.dataset.jsell; renderView(true); return; }
  const jok = e.target.closest("[data-jsok]"); if (jok) { jrSell(jok.dataset.jsok); return; }
  if (e.target.closest("[data-jscancel]")) { S.jsell = null; renderView(true); return; }
  const jd = e.target.closest("[data-jdel]"); if (jd) { if (confirmDel()) { const j = jr(); j.open = j.open.filter((p) => String(p.id) !== jd.dataset.jdel); jrSet(j); renderView(true); } return; }
  const jcd = e.target.closest("[data-jcdel]"); if (jcd) { if (confirmDel()) { const j = jr(); j.closed = j.closed.filter((p) => String(p.id) !== jcd.dataset.jcdel); jrSet(j); renderView(true); } return; }
  if (e.target.closest("#j-exp")) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify({ app: "idxq-jurnal", v: 1, at: new Date().toISOString(), jrnl: jr() }, null, 1)], { type: "application/json" }));
    a.download = `jurnal-idxq-${today()}.json`; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); return; }
  // screener
  if (e.target.closest("#sr-add")) { const c = scrCfg(); c.rules.push({ f: "comp", op: ">=", v: 60 }); c.name = "kustom"; scrSet(c); renderView(true); return; }
  if (e.target.closest("#sr-reset")) { const c = scrCfg(); c.rules = []; c.sec = c.sig = c.st = "ALL"; c.name = "kustom"; scrSet(c); S.cap = 200; renderView(true); return; }
  if (e.target.closest("#sr-csv")) { scrCsv(); return; }
  if (e.target.closest("#sr-save")) { const nm = ($("#sr-name").value || "").trim(); if (!nm) { toast("Isi nama presetnya dulu"); return; } const c = scrCfg(); c.name = nm; scrSet(c);
    store.set("scrp", store.get("scrp", []).filter((p) => p.name !== nm).concat({ name: nm, cfg: { rules: c.rules, sec: c.sec, sig: c.sig, st: c.st } })); renderView(true); toast("Preset disimpan: " + nm); return; }
  const sd = e.target.closest("[data-srdel]"); if (sd) { const c = scrCfg(); c.rules.splice(+sd.dataset.srdel, 1); c.name = "kustom"; scrSet(c); renderView(true); return; }
  const spd = e.target.closest("[data-srpdel]"); if (spd) { const l = store.get("scrp", []); l.splice(+spd.dataset.srpdel, 1); store.set("scrp", l); renderView(true); return; }
  const sp = e.target.closest("[data-srp]"); if (sp) { const id = sp.dataset.srp, i = +id.slice(1);
    if (id[0] === "b") scrSet({ rules: SCR_PRE[i][2].map(([f, op, v]) => ({ f, op, v })), sec: "ALL", sig: "ALL", st: "ALL", name: SCR_PRE[i][0] });
    else { const p = store.get("scrp", [])[i]; if (p) scrSet(Object.assign({ name: p.name }, JSON.parse(JSON.stringify(p.cfg)))); }
    S.cap = 200; renderView(true); return; }
  // layar multi-panel
  const pl = e.target.closest("[data-padlay]"); if (pl) { const c = padCfg(); c.layout = pl.dataset.padlay; store.set("pad", c); renderView(true); return; }
  const ps = e.target.closest("[data-padsub]"); if (ps) { const c = padCfg(), [i, k] = ps.dataset.padsub.split(":"); c.sub[i] = k; store.set("pad", c); renderView(true); return; }
  const pg = e.target.closest("[data-padgo]"); if (pg) { const [t, tab] = pg.dataset.padgo.split("."); openDetail(t, true, tab); return; }
  const pt = e.target.closest("[data-pt]"); if (pt && !e.target.closest("a")) { const c = padCfg(); c.t = pt.dataset.pt; store.set("pad", c); const y = window.scrollY; renderView(true); window.scrollTo(0, y); return; }
  const tk = e.target.closest("[data-t]"); if (tk && !e.target.closest("a")) { openDetail(tk.dataset.t); return; }
  const vw = e.target.closest("[data-view]"); if (vw) { closeDetail(false); go(vw.dataset.view); return; }
  const so = e.target.closest("[data-sort]");
  if (so) { const [tab, k] = so.dataset.sort.split(":"); const cur = S.sort[tab]; S.sort[tab] = [k, cur[0] === k ? -cur[1] : (k === "ticker" || k === "sector" || k === "rank" ? 1 : -1)]; renderView(); return; }
  const fs = e.target.closest("[data-fsec]"); if (fs) { S.fsec = fs.dataset.fsec; S.cap = 200; if (S.view !== "flow") go("flow"); else renderView(); return; }
  const fg = e.target.closest("[data-fsig]"); if (fg) { S.fsig = fg.dataset.fsig; S.cap = 200; renderView(); return; }
  const lq = e.target.closest("[data-liq]"); if (lq) { S.liq = lq.dataset.liq === "1"; S.q = ""; S.cap = 200; renderView(); return; }
  if (e.target.closest("[data-more]")) { S.cap += 300; renderView(true); return; }
  if (e.target.closest("[data-close]")) { closeDetail(); }
  if (e.target.closest("[data-logout]")) { logout(); }
});
document.addEventListener("keydown", (e) => {
  if (!S.d) return;
  const inInput = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
  if (e.key === "Escape") { if (!$("#detail").hidden) closeDetail(); else document.activeElement.blur(); return; }
  const fk = /^F([1-9]|10)$/.exec(e.key);
  const nk = !inInput && /^[0-9]$/.test(e.key) ? (+e.key || 10) : null;
  if (fk || nk) { e.preventDefault(); closeDetail(false); go(VIEWS[(fk ? +fk[1] : nk) - 1][0]); return; }
  if (e.key === "/" && !inInput) { e.preventDefault(); $("#cmd").focus(); }
});
$("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") { runCmd(e.target.value); e.target.value = ""; e.target.blur(); } });
window.addEventListener("hashchange", () => { if (S.d) route(); });
const confirmDel = () => { const k = "_del" + Date.now().toString().slice(0, -3); if (S.delArm && Date.now() - S.delArm < 3000) { S.delArm = 0; return true; } S.delArm = Date.now(); toast("Klik ✕ sekali lagi untuk menghapus"); return false; };
document.addEventListener("change", (e) => {      // bandingkan & jurnal
  if (e.target.id === "c-add") { const t = (e.target.value || "").trim().toUpperCase(); if (!stock(t)) { toast("Ticker tidak ditemukan: " + t); return; } const cc = compCfg(); if (!cc.t.includes(t)) cc.t = cc.t.concat(t).slice(-6); store.set("comp", cc); renderView(true); return; }
  if (e.target.id === "j-t") { const s = stock((e.target.value || "").trim().toUpperCase()); if (s) { $("#j-px").value = s.last; $("#j-sl").value = s.levels.sl || ""; $("#j-tp").value = s.levels.tp1 || ""; } return; }
  if (e.target.id === "j-imp" && e.target.files[0]) {
    e.target.files[0].text().then((txt) => { const o = JSON.parse(txt), j = o.jrnl || o; if (!Array.isArray(j.open) || !Array.isArray(j.closed)) throw new Error("format");
      const cur = jr(), ids = new Set(cur.open.concat(cur.closed).map((p) => String(p.id)));
      const add = (arr) => arr.filter((p) => p && p.t && p.px > 0 && p.lots > 0 && !ids.has(String(p.id)));
      const no = add(j.open), nc = add(j.closed).filter((p) => p.xpx > 0 && p.xd);
      cur.open = cur.open.concat(no); cur.closed = cur.closed.concat(nc); jrSet(cur); toast(`Diimpor: ${no.length} posisi terbuka, ${nc.length} trade selesai`); renderView(true); })
      .catch(() => toast("File tidak bisa dibaca sebagai cadangan jurnal"));
  }
});
document.addEventListener("change", (e) => {      // screener & layar multi-panel
  const sr = e.target.dataset && e.target.dataset.sr;
  if (sr) { const c = scrCfg(), [i, k] = sr.split(":");
    if (i === "x") c[k] = e.target.value; else if (c.rules[+i]) c.rules[+i][k] = k === "v" ? (e.target.value === "" ? "" : parseFloat(e.target.value)) : e.target.value;
    c.name = "kustom"; scrSet(c); S.cap = 200; renderView(true); return; }
  const pty = e.target.dataset && e.target.dataset.padtype;
  if (pty != null) { const c = padCfg(); c.panels[+pty] = e.target.value; delete c.sub[pty]; store.set("pad", c); renderView(true); return; }
  if (e.target.id === "pad-t") { const t = (e.target.value || "").trim().toUpperCase(); if (stock(t)) { const c = padCfg(); c.t = t; store.set("pad", c); renderView(true); } else toast("Ticker tidak ditemukan: " + t); }
});
document.addEventListener("change", (e) => {      // asumsi proyeksi (EE)
  const m = /^e-(g|tg|m)$/.exec(e.target.id || ""); if (!m || !S.ticker) return;
  const v = parseFloat(e.target.value) / 100; if (!(v >= -0.5 && v <= 0.8)) return;
  const o = store.get("fc", {}), cur = o[S.ticker] || {};
  ["g", "tg", "m"].forEach((k) => { const el = $("#e-" + k); if (el && el.value !== "") cur[k] = parseFloat(el.value) / 100; });
  o[S.ticker] = cur; store.set("fc", o);
  const y = $("#detail").scrollTop; openDetail(S.ticker, false, "ee").then(() => { $("#detail").scrollTop = y; });
});
document.addEventListener("change", (e) => {      // asumsi valuasi
  const m = /^v-(w|g|tg|coe)$/.exec(e.target.id || ""); if (!m || !S.ticker) return;
  const v = parseFloat(e.target.value) / 100; if (!(v >= 0 && v <= 0.4)) return;
  if (m[1] === "g") store.set("valg", Object.assign(store.get("valg", {}), { [S.ticker]: v }));
  else store.set("val", Object.assign(store.get("val", {}), { [m[1]]: v }));
  const y = $("#detail").scrollTop; openDetail(S.ticker, false, "val").then(() => { $("#detail").scrollTop = y; });
});
document.addEventListener("input", (e) => {
  if (e.target.id !== "q") return;
  S.q = e.target.value; S.cap = 200;
  clearTimeout(S.qt); S.qt = setTimeout(() => { S.refocus = true; renderView(); }, 220);
});

/* ---------------- boot ---------------- */
S.view = (location.hash.replace("#", "") || "mkt");
if (!VIEWS.some((v) => v[0] === S.view)) S.view = "mkt";
let rzT; window.addEventListener("resize", () => { clearTimeout(rzT); rzT = setTimeout(() => { if (S.d && S.view === "map" && $("#detail").hidden) renderView(true); }, 200); });
load(true);
setInterval(tick, 1000);
if (!window.__DATA__) setInterval(() => load(false), 5 * 60 * 1000);
if ("serviceWorker" in navigator && location.protocol === "https:" && !window.__DATA__) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* tidak didukung */ });
}
})();
