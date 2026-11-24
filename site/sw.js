/* Service worker: app shell cache-first, data network-first (offline tetap tampil data terakhir). */
const CACHE = "idxq-v28";
const SHELL = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest",
  "vendor/lightweight-charts.standalone.production.js", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.endsWith("/data/latest.json")) {
    e.respondWith(fetch(e.request).then((r) => {
      const copy = r.clone();
      caches.open(CACHE).then((c) => c.put("data/latest.json", copy));
      return r;
    }).catch(() => caches.match("data/latest.json")));
    return;
  }
  // shell: network-first (selalu versi terbaru), cache hanya untuk offline
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
