/* IDX QUANT TERMINAL — frontend (vanilla JS + lightweight-charts) */
(() => {
"use strict";
const LWC = window.LightweightCharts;
const S = {
  d: null, view: "mkt", ticker: null, charts: [], dcharts: [],
  sort: { flow: ["nf5", -1], signal: ["rank", 1] },
  fsig: "ALL", fsec: "ALL", fnews: "", ai: null, liq: true, q: "", cap: 200,
};
const VIEWS = [
  ["mkt", "F1", "MKT", "Pasar"], ["flow", "F2", "FLOW", "Money Flow"], ["signal", "F3", "SIGNAL", "Sinyal"],
  ["porto", "F4", "PORT", "Portofolio"], ["news", "F5", "NEWS", "Sentimen"], ["btest", "F6", "BTEST", "Backtest"],
  ["help", "F7", "HELP", "Metode"],
];
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
  if (changed) {
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
    `<button data-view="${id}" class="${S.view === id ? "on" : ""}" title="${lab} (${k})"><span class="k">${k}</span>${code}</button>`).join("");
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
    const t = h.slice(2).toUpperCase();
    if (stock(t)) { if (S.view === "mkt" && !$("#view").innerHTML) renderView(); openDetail(t, false); return; }
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
  const v = { mkt: vMkt, flow: vFlow, signal: vSignal, porto: vPorto, news: vNews, btest: vBtest, help: vHelp }[S.view];
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
    ["nf1", "Flow 1H", 1], ["nf5", "Flow 5H", 1], ["nf20", "Flow 20H", 1],
    ...(fa ? [["fnet5", "Asing 5H", 1]] : []),
    ["cmf", "CMF", 1], ["mfi", "MFI", 1], ["volratio", "Vol x", 1], ["status", "Status"], ["flowscore", "Skor Flow"],
  ];
  const val = (s, k) => ({ ticker: s.ticker, sector: s.sector, last: s.last, chg_pct: s.chg_pct, value: s.flow.value, nf1: s.flow.nf1, nf5: s.flow.nf5,
    nf20: s.flow.nf20, fnet5: s.flow.fnet5, cmf: s.flow.cmf, mfi: s.flow.mfi, volratio: s.flow.volratio, status: s.flow.status, flowscore: s.scores.flow }[k]);
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
        ${fa ? `<td class="r ${cls(s.flow.fnet5)}">${rp(s.flow.fnet5)}</td>` : ""}
        <td class="r ${cls(s.flow.cmf)}">${num(s.flow.cmf, 2)}</td><td class="r">${num(s.flow.mfi)}</td><td class="r ${s.flow.volratio >= 1.5 ? "amb" : ""}">${num(s.flow.volratio, 1)}x</td>
        <td class="${s.flow.status === "AKUMULASI" ? "up" : s.flow.status === "DISTRIBUSI" ? "down" : "mut"}">${s.flow.status}</td>
        <td style="width:110px">${scoreBar(s.scores.flow)}</td></tr>`).join("") || `<tr><td colspan="14" class="mut">Tidak ada saham yang cocok.</td></tr>`}</tbody></table></div>${moreBar(total)}
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
  let rows = pool(S.fsig === "AVOID").filter((s) => S.fsig === "ALL" || s.signal === S.fsig);
  const [sk, sd] = S.sort.signal;
  const key = (s) => ({ rank: SIGRANK[s.signal] * 1000 - (s.scores.composite || 0), ticker: s.ticker, comp: s.scores.composite, flow: s.scores.flow,
    mom: s.scores.momentum, trend: s.scores.trend, sent: s.scores.sentiment, time: s.scores.timing, last: s.last, rsi: s.ind.rsi, rr: s.levels.rr2 }[sk]);
  rows.sort((a, b) => { const x = key(a), y = key(b); return (typeof x === "string" ? x.localeCompare(y) : (x ?? -1e9) - (y ?? -1e9)) * sd; });
  const total = rows.length; rows = rows.slice(0, S.cap);
  const th = (k, l, r) => `<th data-sort="signal:${k}" class="${r ? "r" : ""} ${sk === k ? "sorted" + (sd > 0 ? " asc" : "") : ""}">${l}</th>`;
  root.innerHTML = `
  <div class="panel"><h3>Signal Board · kapan IN & EXIT <span class="fn">rezim ${d.market.regime.label} · klik baris untuk chart & rencana trade</span></h3><div class="pb">
    <div class="filters">${scopeBar()}</div>
    <div class="filters">${opts.map((o) => `<button data-fsig="${o}" class="${S.fsig === o ? "on" : ""}">${o === "ALL" ? "Semua sinyal" : o}${o === "ALL" ? "" : " " + (d.market.signal_count[o] || 0)}</button>`).join("")}</div>
    <div class="tw"><table><thead><tr>${th("ticker", "Ticker")}${th("rank", "Sinyal")}${th("comp", "Komposit")}${th("flow", "Flow", 1)}${th("mom", "Mom", 1)}${th("trend", "Trend", 1)}${th("sent", "Sent", 1)}${th("time", "Timing", 1)}
      ${th("last", "Harga", 1)}<th class="r">Zona Beli</th><th class="r">Stop (close)</th><th class="r">TP1 / TP2</th>${th("rr", "R:R", 1)}${th("rsi", "RSI", 1)}<th>Alasan utama</th></tr></thead>
    <tbody>${rows.map((s) => { const L = s.levels, buy = s.signal === "BUY" || s.signal === "STRONG BUY"; return `<tr data-t="${s.ticker}">
      <td class="tk">${s.ticker}</td><td>${sig(s.signal)}</td><td style="width:110px">${scoreBar(s.scores.composite)}</td>
      ${["flow", "momentum", "trend", "sentiment", "timing"].map((k) => `<td class="r" style="color:${scoreColor(s.scores[k])}">${num(s.scores[k])}</td>`).join("")}
      <td class="r b">${num(s.last)} <span class="${cls(s.chg_pct)} small">${pct(s.chg_pct)}</span></td>
      <td class="r ${buy ? "" : "dim"}">${num(L.entry_low)}–${num(L.entry_high)}</td>
      <td class="r ${buy ? "down" : "dim"}">${num(L.sl)} <span class="small">${pct(L.sl_pct)}</span></td>
      <td class="r ${buy ? "up" : "dim"}">${num(L.tp1)} / ${num(L.tp2)}</td><td class="r">${num(L.rr2, 1)}</td><td class="r ${s.ind.rsi >= cf.rsi_overbought ? "down" : ""}">${num(s.ind.rsi)}</td>
      <td>${s.reasons.slice(0, 2).map(chip).join("")}${s.signal === "EXIT" || s.signal === "REDUCE" ? s.reasons.filter((r) => r.s < 0).slice(0, 1).map(chip).join("") : ""}</td></tr>`; }).join("") || `<tr><td colspan="15" class="mut">Tidak ada saham yang cocok.</td></tr>`}</tbody></table></div>${moreBar(total)}
    <div class="note">STRONG BUY = komposit ≥ ${cf.strong_buy} + uptrend + flow positif ganda · BUY = komposit ≥ ${cf.buy} + uptrend + flow positif · EXIT = close &lt; trailing stop, atau tembus MA50 dengan CMF negatif, atau komposit &lt; ${cf.exit}.
    Stop dicek di harga <b>penutupan</b> (eksekusi besok pagi) karena stop intraday rawan kena “jarum”. Zona beli = harga − 0,75×ATR s/d harga (atau MA20).</div>
  </div></div>`;
}
const chip = (r) => `<span class="chip ${r.s > 0 ? "p" : r.s < 0 ? "n" : "z"}">${esc(r.t)}</span>`;

/* ================= F4 PORTO ================= */
function portDefaults() {
  const p = S.d.config.portfolio;
  return { equity: p.equity, risk: p.risk_per_trade * 100, maxpos: p.max_positions, maxw: p.max_weight * 100, maxsec: p.max_sector * 100,
    feeb: S.d.rules.fee_buy * 100, regime: true, entry: "last", buyFactor: 75 };
}
function buildPort(p) {
  const d = S.d, lot = d.rules.lot_size, fee = p.feeb / 100;
  const cap = p.regime ? d.market.regime.exposure : 1;
  const maxInvest = p.equity * cap;
  const cands = d.stocks.filter((s) => s.signal === "STRONG BUY" || s.signal === "BUY")
    .sort((a, b) => (SIGRANK[a.signal] - SIGRANK[b.signal]) || (b.scores.composite - a.scores.composite));
  let invested = 0; const secUsed = {}; const rows = []; const skipped = [];
  for (const s of cands) {
    if (rows.length >= p.maxpos) { skipped.push([s.ticker, "slot penuh"]); continue; }
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
  return { rows, skipped, invested, cash: p.equity - invested, risk, heat: risk / p.equity, cap, maxInvest, secUsed };
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
      maxsec: +g("maxsec"), feeb: +g("feeb"), buyFactor: +g("buyFactor"), entry: g("entry"), regime: g("regime") === "1" };
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
    <div class="panel"><h3>Kombinasi Posisi <span class="fn">lot 100 lembar · harga sudah dibulatkan ke fraksi BEI</span></h3><div class="pb"><div class="tw"><table>
      <thead><tr><th>Ticker</th><th>Sinyal</th><th class="r">Lot</th><th class="r">Entry</th><th class="r">Nilai (incl. fee)</th><th class="r">Bobot</th><th class="r">Stop</th><th class="r">Risiko Rp</th><th class="r">TP1 / TP2</th><th class="r">Potensi @TP1</th></tr></thead>
      <tbody>${r.rows.map((x) => `<tr data-t="${x.s.ticker}"><td class="tk">${x.s.ticker}</td><td>${sig(x.s.signal)}</td><td class="r b">${num(x.lots)}</td><td class="r">${num(x.entry)}</td>
        <td class="r">${rupiah(x.cost)}</td><td class="r">${pct(x.w, 1).replace("+", "")}</td><td class="r down">${num(x.sl)}</td><td class="r down">${rupiah(x.risk)}</td>
        <td class="r up">${num(x.s.levels.tp1)} / ${num(x.s.levels.tp2)}</td><td class="r up">+${rupiah(x.gain1)}</td></tr>`).join("") ||
        `<tr><td colspan="10" class="mut">Tidak ada posisi: belum ada sinyal BUY, atau modal terlalu kecil untuk 1 lot.</td></tr>`}</tbody></table></div>
      ${r.skipped.length ? `<div class="note">Dilewati: ${r.skipped.slice(0, 10).map(([t, w]) => `${t} (${w})`).join(" · ")}${r.skipped.length > 10 ? ` · +${r.skipped.length - 10} lainnya` : ""}</div>` : ""}
      <div class="note">Ukuran posisi = (modal × risiko%) ÷ (entry − stop), lalu dibatasi bobot saham, bobot sektor, dan eksposur rezim. Saham volatil otomatis dapat lot lebih sedikit.</div>
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
    <table><tbody>${[["Flow", w.flow, "Peringkat cross-sectional: intensitas net flow 20H & 5H (dinormalisasi likuiditas), CMF-20, momentum OBV, MFI-14" + (d.meta.foreign_available ? ", net beli asing 5H" : "")],
      ["Momentum", w.momentum, "Momentum 12-1 bulan (Jegadeesh-Titman / Asness-Moskowitz-Pedersen), 6-1 bulan, return 3 bulan, kedekatan ke 52-week high (George-Hwang)"],
      ["Trend", w.trend, "Absolut: posisi harga vs MA20/50/200, golden cross MA50>MA200, kemiringan MA50"],
      ["Sentimen", w.sentiment, "Berita 14 hari (Google News, CNBC Indonesia), leksikon keuangan ID/EN; opsional dinilai Claude"],
      ["Timing", w.timing, "Hindari mengejar: jarak dari MA20 dalam satuan ATR & RSI-14 (penalti overbought)"]]
      .map(([k, v, t]) => `<tr><td class="amb b">${k}</td><td class="r">${Math.round(v * 100)}%</td><td style="white-space:normal">${t}</td></tr>`).join("")}</tbody></table>
    <h4>2 · Aturan IN & EXIT (long-only)</h4>
    <ul><li><b>STRONG BUY</b>: komposit ≥ ${d.config.signal.strong_buy}, close &gt; MA50 &amp; MA20 &gt; MA50, CMF &gt; 0 <i>dan</i> flow 5H &gt; 0, RSI &lt; ${d.config.signal.rsi_overbought - 3}, rezim bukan RISK-OFF.</li>
      <li><b>BUY</b>: komposit ≥ ${d.config.signal.buy}, uptrend yang sama, CMF &gt; 0 <i>atau</i> flow 5H &gt; 0, RSI &lt; ${d.config.signal.rsi_overbought}.</li>
      <li><b>EXIT</b>: close &lt; chandelier stop (high 22H − ${d.config.signal.trail_atr_mult}×ATR), atau close &lt; MA50 dengan CMF &lt; 0, atau komposit &lt; ${d.config.signal.exit}.</li>
      <li><b>REDUCE</b>: komposit &lt; ${d.config.signal.reduce}, RSI &gt; 80, atau status DISTRIBUSI — ambil sebagian profit / perketat stop.</li>
      <li><b>Level</b>: Stop = harga − ${d.config.signal.atr_stop_mult}×ATR (dicek di close), TP1 = ${d.config.signal.tp1_r}R, TP2 = ${d.config.signal.tp2_r}R, semua dibulatkan ke fraksi BEI.</li></ul>
    <h4>3 · Rezim pasar</h4>
    <p>6 faktor: IHSG vs MA200, MA50 vs MA200, breadth (&gt;50% / &lt;30% saham di atas MA50), volatilitas IHSG (persentil &gt;80 = negatif), pelemahan rupiah 20H &gt; 1,5%. Skor ≥ 2 RISK-ON (eksposur ${Math.round(d.config.regime_exposure["RISK-ON"] * 100)}%), 0–1 NEUTRAL (${Math.round(d.config.regime_exposure.NEUTRAL * 100)}%), &lt; 0 RISK-OFF (${Math.round(d.config.regime_exposure["RISK-OFF"] * 100)}%).</p>
    <h4>4 · Position sizing</h4>
    <p>Fixed-fractional risk: lot = (modal × risiko%) ÷ (entry − stop) ÷ 100, dibatasi bobot maks per saham, per sektor, dan eksposur rezim. Half-Kelly dari backtest hanya sebagai batas atas referensi.</p>
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
    <div class="panel"><h3>Shortcut</h3><div class="pb small"><dl class="kv"><dt>F1–F7 / 1–7</dt><dd>pindah fungsi</dd><dt>/</dt><dd>fokus command line</dd><dt>KODE &lt;Enter&gt;</dt><dd>buka saham (mis. BBCA)</dd><dt>PORT 50000000</dt><dd>set modal</dd><dt>Esc</dt><dd>tutup detail</dd></dl></div></div>
    <div class="callout red">Bukan rekomendasi investasi. Model kuantitatif bisa salah, terutama saat rezim berubah, saham digoreng, atau ada aksi korporasi. Selalu cek ulang sebelum order dan pakai manajemen risiko.</div>
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
async function openDetail(t, push = true) {
  const s = stock(t); if (!s) { toast("Ticker tidak ditemukan: " + t); return; }
  if (push && location.hash !== "#t-" + t) { location.hash = "t-" + t; return; }
  S.ticker = t;
  disposeCharts(S.dcharts);
  const el = $("#detail"); el.hidden = false; document.body.style.overflow = "hidden";
  if (!s.series) {   // data chart per saham dimuat saat dibuka
    const head = (msg) => `<div class="dhead"><span class="tk">${s.ticker}</span><span>${esc(s.name)}</span><span class="mut">${msg}</span><button class="close" data-close>✕ ESC</button></div>`;
    el.innerHTML = head("Memuat chart…");
    try { s.series = await loadSeries(t); } catch (e) { if (S.ticker === t) el.innerHTML = head("Gagal memuat data chart (" + esc(e.message) + ")"); return; }
    if (S.ticker !== t) return;
  }
  const L = s.levels, n = s.series.c.length, dates = S.d.dates.slice(-n);
  const buy = s.signal === "BUY" || s.signal === "STRONG BUY";
  const p = Object.assign(portDefaults(), store.get("port", {}));
  const rps = L.entry_high - L.sl;
  const lots = rps > 0 ? Math.max(0, Math.floor(Math.min((p.equity * p.risk / 100) / rps, (p.equity * p.maxw / 100) / L.entry_high) / 100)) : 0;
  el.innerHTML = `
  <div class="dhead"><span class="tk">${s.ticker}</span><span>${esc(s.name)}</span><span class="mut">${esc(s.sector)}</span>
    <span class="mid">${num(s.last)}</span><span class="${cls(s.chg_pct)}">${s.chg > 0 ? "+" : ""}${num(s.chg)} (${pct(s.chg_pct)})</span>${sig(s.signal)}
    <span class="mut">komposit</span><b style="color:${scoreColor(s.scores.composite)}">${num(s.scores.composite)}</b>
    <button class="close" data-close>✕ ESC</button></div>
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
      <div class="panel"><h3>Komponen Skor</h3><div class="pb comp-bars">
        ${[["Flow", "flow"], ["Momentum", "momentum"], ["Trend", "trend"], ["Sentimen", "sentiment"], ["Timing", "timing"]].map(([l, k]) =>
          `<span class="mut">${l}</span><div class="bar"><span style="width:${s.scores[k]}%;background:${scoreColor(s.scores[k])}"></span></div><b class="r">${num(s.scores[k])}</b>`).join("")}
      </div></div>
      <div class="panel"><h3>Kenapa?</h3><div class="pb">${s.reasons.map(chip).join("") || `<span class="mut">–</span>`}</div></div>
      <div class="panel"><h3>Data Kunci</h3><div class="pb"><dl class="kv small">
        <dt>Flow 1H / 5H / 20H</dt><dd><span class="${cls(s.flow.nf1)}">${rp(s.flow.nf1)}</span> / <span class="${cls(s.flow.nf5)}">${rp(s.flow.nf5)}</span> / <span class="${cls(s.flow.nf20)}">${rp(s.flow.nf20)}</span></dd>
        ${s.flow.fnet5 != null ? `<dt>Asing 1H / 5H / 20H</dt><dd>${rp(s.flow.fnet1)} / ${rp(s.flow.fnet5)} / ${rp(s.flow.fnet20)}</dd>` : ""}
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
  const [a, b] = v.split(/\s+/);
  const alias = { MKT: "mkt", PASAR: "mkt", FLOW: "flow", SIG: "signal", SIGNAL: "signal", SINYAL: "signal", PORT: "porto", PORTO: "porto", NEWS: "news", BERITA: "news", BT: "btest", BTEST: "btest", BACKTEST: "btest", HELP: "help", METODE: "help" };
  if (a === "PORT" && b) {
    const eq = parseFloat(b.replace(/\./g, "")); if (eq > 0) { store.set("port", Object.assign(store.get("port", {}), { equity: eq })); }
  }
  if (alias[a]) { closeDetail(false); go(alias[a]); if (location.hash === "#" + alias[a]) route(); return; }
  if (stock(a)) { openDetail(a); return; }
  toast("Perintah tidak dikenal: " + a);
}
document.addEventListener("click", (e) => {
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
  const fk = /^F([1-7])$/.exec(e.key);
  const nk = !inInput && /^[1-7]$/.test(e.key) ? +e.key : null;
  if (fk || nk) { e.preventDefault(); closeDetail(false); go(VIEWS[(fk ? +fk[1] : nk) - 1][0]); return; }
  if (e.key === "/" && !inInput) { e.preventDefault(); $("#cmd").focus(); }
});
$("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") { runCmd(e.target.value); e.target.value = ""; e.target.blur(); } });
window.addEventListener("hashchange", () => { if (S.d) route(); });
document.addEventListener("input", (e) => {
  if (e.target.id !== "q") return;
  S.q = e.target.value; S.cap = 200;
  clearTimeout(S.qt); S.qt = setTimeout(() => { S.refocus = true; renderView(); }, 220);
});

/* ---------------- boot ---------------- */
S.view = (location.hash.replace("#", "") || "mkt");
if (!VIEWS.some((v) => v[0] === S.view)) S.view = S.view.startsWith("t-") ? "mkt" : "mkt";
load(true);
setInterval(tick, 1000);
if (!window.__DATA__) setInterval(() => load(false), 5 * 60 * 1000);
if ("serviceWorker" in navigator && location.protocol === "https:" && !window.__DATA__) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* tidak didukung */ });
}
})();
