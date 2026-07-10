const CACHE_NAME = "openpartsflow-static-v2";
const OFFLINE_URL = "/offline.html";
const CORE_ASSETS = ["/", "/offline.html", "/manifest.json", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

function isSameOriginApiCacheable(url, request) {
  if (url.origin !== self.location.origin) return false;
  if (request.method !== "GET") return false;
  const p = url.pathname;
  if (p.startsWith("/api")) return false;
  if (p.includes("hot-update")) return false;
  return true;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (!isSameOriginApiCacheable(url, event.request)) {
    event.respondWith(
      fetch(event.request).catch(() => {
        if (event.request.mode === "navigate") {
          return caches.match(OFFLINE_URL).then((page) => page || new Response("Offline", { status: 503 }));
        }
        return new Response("Network unavailable", { status: 503, statusText: "Network Error" });
      })
    );
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        if (event.request.mode === "navigate") {
          const offline = await caches.match(OFFLINE_URL);
          if (offline) return offline;
        }
        return new Response("Offline", { status: 503, statusText: "Offline" });
      })
  );
});
