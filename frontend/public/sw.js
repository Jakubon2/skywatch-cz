// Hand-written service worker: offline app shell, live data.
//
// - Page navigations: network first, cached shell when offline. A fresh index.html is
//   cached on every online load, so a new deploy is picked up without bumping anything.
// - /assets/* (hashed by Vite, immutable): cache first; files no longer referenced by the
//   current index.html are pruned.
// - /api/* and anything cross-origin (map tiles): not intercepted at all, always network
//   (tiles keep only the browser's normal HTTP cache, per the OSM tile policy).
//
// Bump CACHE only if this caching scheme itself changes; old caches are deleted on activate.

const CACHE = "skywatch-shell-v1";
const STATIC = ["/manifest.webmanifest", "/favicon.svg", "/icons/icon-192.png", "/icons/apple-touch-icon.png"];

// Hashed bundle URLs referenced by an index.html.
const assetsIn = (html) => [...new Set(html.match(/\/assets\/[^"'\s)]+/g) || [])];

// Store a fresh index.html; on a new deploy also fetch its bundles and drop the old ones.
async function cacheShell(cache, response) {
  const html = await response.clone().text();
  await cache.put("/", response);
  const keep = assetsIn(html);
  const missing = [];
  for (const url of keep) if (!(await cache.match(url))) missing.push(url);
  if (!missing.length) return;
  await cache.addAll(missing);
  for (const req of await cache.keys()) {
    const path = new URL(req.url).pathname;
    if (path.startsWith("/assets/") && !keep.includes(path)) await cache.delete(req);
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      await cache.addAll(STATIC);
      await cacheShell(cache, await fetch("/", { cache: "no-cache" }));
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          const res = await fetch(req);
          if (res.ok && url.pathname === "/") {
            const cache = await caches.open(CACHE);
            event.waitUntil(cacheShell(cache, res.clone()));
          }
          return res;
        } catch {
          return (await caches.match("/")) || Response.error();
        }
      })(),
    );
    return;
  }

  event.respondWith(
    (async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      const res = await fetch(req);
      if (res.ok && url.pathname.startsWith("/assets/")) {
        const copy = res.clone();
        event.waitUntil(caches.open(CACHE).then((cache) => cache.put(req, copy)));
      }
      return res;
    })(),
  );
});

// --- Web Push (backend/push.py). Payload: {title, body, url, tag}. ---

self.addEventListener("push", (event) => {
  let msg = {};
  try {
    msg = event.data ? event.data.json() : {};
  } catch {
    msg = { body: event.data && event.data.text() };
  }
  event.waitUntil(
    self.registration.showNotification(msg.title || "Skywatch CZ", {
      body: msg.body || "",
      tag: msg.tag || undefined,
      data: { url: msg.url || "/" },
      icon: "/icons/icon-192.png",
      lang: "cs",
    }),
  );
});

// Focus an open app window and navigate it to the notification's url (e.g. /?event=123), or open one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const client = windows.find((c) => new URL(c.url).origin === self.location.origin);
      if (client) {
        await client.focus();
        if (client.url !== url) await client.navigate(url).catch(() => {});
        return;
      }
      await self.clients.openWindow(url);
    })(),
  );
});
