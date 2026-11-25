const CACHE = "job-watcher-v2";
const APP_SHELL = ["./", "index.html", "browse.html", "market.html", "styles.css", "app.js", "manifest.webmanifest", "icon.svg", "data/status.json", "data/history.csv"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const requestURL = new URL(event.request.url);
  const isNetworkFirst = event.request.mode === "navigate"
    || requestURL.pathname.endsWith("/data/status.json")
    || requestURL.pathname.endsWith("/data/history.csv")
    || /\.(?:html|js|css|webmanifest|svg)$/.test(requestURL.pathname);
  if (isNetworkFirst) {
    event.respondWith(fetch(event.request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      return response;
    }).catch(() => caches.match(event.request)));
    return;
  }
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(event.request, copy));
    return response;
  })));
});
