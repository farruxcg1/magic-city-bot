/* Magic City rahbar ilovasi: sahifa va belgilar keshda (tez ochilishi uchun), ma'lumot har doim serverdan. */
const V = "mc-rahbar-v1";
const SHELL = ["/rahbar/", "/rahbar/static/icon-192.png", "/rahbar/static/apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  if (u.pathname === "/rahbar/" || u.pathname === "/rahbar") {
    // sahifa: avval tarmoq (yangi versiya), internet bo'lmasa kesh
    e.respondWith(fetch(e.request).then(r => {
      const copy = r.clone(); caches.open(V).then(c => c.put("/rahbar/", copy)); return r;
    }).catch(() => caches.match("/rahbar/")));
    return;
  }
  if (u.pathname.startsWith("/rahbar/static/")) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
