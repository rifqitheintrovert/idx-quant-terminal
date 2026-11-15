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
];
const DTABS = [["gp", "GP", "Chart & rencana trade"], ["des", "DES", "Profil"], ["fa", "FA", "Fundamental"], ["val", "DCF", "Harga wajar"], ["cn", "CN", "Berita"]];
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
    evalAlerts();
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
  const v = { mkt: vMkt, flow: vFlow, signal: vSignal, porto: vPorto, news: vNews, btest: vBtest, help: vHelp, map: vMap, watch: vWatch }[S.view];
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
    <div class="panel"><h3>Shortcut</h3><div class="pb small"><dl class="kv"><dt>F1–F9 / 1–9</dt><dd>pindah fungsi</dd><dt>/</dt><dd>fokus command line</dd><dt>BBCA &lt;Enter&gt;</dt><dd>buka saham (chart & rencana trade)</dd>
      <dt>BBCA DES</dt><dd>profil perusahaan</dd><dt>BBCA FA</dt><dd>fundamental & valuasi vs sektor</dd><dt>BBCA DCF</dt><dd>perkiraan harga wajar (DCF, EV/EBITDA, PER, PBV)</dd><dt>BBCA CN</dt><dd>berita saham</dd><dt>BBCA GP</dt><dd>chart harga</dd>
      <dt>MAP</dt><dd>heatmap pasar</dd><dt>W</dt><dd>watchlist & alert</dd><dt>W ADD BBCA / W DEL BBCA</dt><dd>tambah / hapus watchlist</dd>
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
    <span class="mut small hide-m" style="margin-left:auto">perintah: <b>${s.ticker} DES</b> · <b>${s.ticker} FA</b> · <b>${s.ticker} DCF</b> · <b>${s.ticker} CN</b></span></div>`;
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
    if (S.ticker !== t || S.dtab !== tab) return;
    $("#d-body").innerHTML = tab === "des" ? tabDes(s, f) : tab === "fa" ? tabFa(s, f) : tab === "val" ? tabVal(s, f) : tabCn(s);
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
  const [a, b, c] = v.replace(/[<>]/g, " ").split(/\s+/).filter((x) => x && !["EQUITY", "IJ", "GO"].includes(x));
  if (!a) return;
  if ((a === "W" || a === "WATCH") && (b === "ADD" || b === "DEL") && c) {
    if (!stock(c)) { toast("Ticker tidak ditemukan: " + c); return; }
    setWatch(c, b === "ADD"); toast(c + (b === "ADD" ? " masuk watchlist" : " dihapus dari watchlist")); closeDetail(false); go("watch"); if (location.hash === "#watch") route(); return;
  }
  const alias = { MAP: "map", IMAP: "map", HEATMAP: "map", W: "watch", WATCH: "watch", WL: "watch", ALRT: "watch", ALERT: "watch", MKT: "mkt", PASAR: "mkt", FLOW: "flow", SIG: "signal", SIGNAL: "signal", SINYAL: "signal", PORT: "porto", PORTO: "porto", NEWS: "news", BERITA: "news", BT: "btest", BTEST: "btest", BACKTEST: "btest", HELP: "help", METODE: "help" };
  if (a === "PORT" && b) {
    const eq = parseFloat(b.replace(/\./g, "")); if (eq > 0) { store.set("port", Object.assign(store.get("port", {}), { equity: eq })); }
  }
  if (alias[a]) { closeDetail(false); go(alias[a]); if (location.hash === "#" + alias[a]) route(); return; }
  if (stock(a)) {
    if (b === "W" || b === "ADD") { setWatch(a, true); toast(a + " masuk watchlist"); }
    openDetail(a, true, { DES: "des", GP: "gp", G: "gp", FA: "fa", RV: "fa", DVD: "fa", DCF: "val", VAL: "val", CN: "cn", NEWS: "cn" }[b] || "gp"); return;
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
  if (e.target.closest("#v-reset") && S.ticker) { store.set("val", {}); const g = store.get("valg", {}); delete g[S.ticker]; store.set("valg", g); openDetail(S.ticker, false, "val"); return; }
  if (e.target.closest("#a-notif")) { if ("Notification" in window) Notification.requestPermission().then(() => renderView(true)); return; }
  if (e.target.closest("#a-clear")) { store.set("alog", []); renderView(true); return; }
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
  const fk = /^F([1-9])$/.exec(e.key);
  const nk = !inInput && /^[1-9]$/.test(e.key) ? +e.key : null;
  if (fk || nk) { e.preventDefault(); closeDetail(false); go(VIEWS[(fk ? +fk[1] : nk) - 1][0]); return; }
  if (e.key === "/" && !inInput) { e.preventDefault(); $("#cmd").focus(); }
});
$("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") { runCmd(e.target.value); e.target.value = ""; e.target.blur(); } });
window.addEventListener("hashchange", () => { if (S.d) route(); });
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
