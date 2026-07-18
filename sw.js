/* 旅日和 PWA Service Worker
   策略:
   - 導覽/index.html:網路優先(確保拿到最新版),離線退快取
   - 圖示/manifest:快取優先
   - data/osm 分區檔:不經 SW(前端已有 IndexedDB 快取)
   - 外部資源(圖磚/CDN/API):不攔截 */
const VER = "wayu-v1";
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
  if (url.pathname.includes("/data/osm/")) return;         // 資料檔交給 IndexedDB
  if (e.request.mode === "navigate" || url.pathname.endsWith("index.html")) {
    // 網路優先:部署新版立即生效;離線時退快取殼層
    e.respondWith(
      fetch(e.request).then(r => {
        const cp = r.clone();
        caches.open(VER).then(c => c.put("./index.html", cp));
        return r;
      }).catch(() => caches.match("./index.html"))
    );
    return;
  }
  // 其他同源(圖示/manifest):快取優先
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      const cp = r.clone();
      caches.open(VER).then(c => c.put(e.request, cp));
      return r;
    }))
  );
});
