/* 旅日和 PWA Service Worker  (r150)
   策略:
   - 導覽/index.html:網路優先(確保拿到最新版),離線退快取
   - 圖示/manifest:快取優先
   - data/ 全部資料檔:不經 SW(★r150 修正:以前只放行 data/osm,
     導致 photos.json / photo_fixes.json / spots_extra.json 被快取住永遠陳舊)
   - 外部資源(圖磚/CDN/API):不攔截 */
const VER = "wayu-v2";
const SHELL = ["./", "./index.html", "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/icon-maskable-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VER).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== VER).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;              // 外部資源不攔
  if (url.pathname.includes("/data/")) return;             // ★資料檔全部直連網路(前端各自有快取策略)
  if (e.request.mode === "navigate" || url.pathname.endsWith("index.html")) {
    e.respondWith(
      fetch(e.request).then(r => {
        const cp = r.clone();
        caches.open(VER).then(c => c.put("./index.html", cp));
        return r;
      }).catch(() => caches.match("./index.html"))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      const cp = r.clone();
      caches.open(VER).then(c => c.put(e.request, cp));
      return r;
    }))
  );
});
