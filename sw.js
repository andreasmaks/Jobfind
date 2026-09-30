const SHELL = "jobfind-shell-v4";
const LOGOS = "jobfind-logos-v1";
const PREFIX = "jobfind-";
const CORE = [
  "/", "/assets/app.js?v=6", "/assets/api.js?v=4", "/assets/offline.js?v=4", "/assets/ui.js",
  "/assets/theme.js", "/assets/styles.css?v=5", "/assets/local.css", "/assets/brand-mark.svg", "/favicon.svg",
  "/manifest.webmanifest",
];
const CURATED_LOGOS = [];
const SHELL_PATHS = new Set(CORE.map((path) => new URL(path, self.location.origin).pathname));
const CURATED_PATHS = new Set(CURATED_LOGOS);

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const shell = await caches.open(SHELL);
    for (const path of CORE) {
      const response = await fetch(path, { credentials: "same-origin", cache: "reload" });
      if (!response.ok || response.redirected) throw new Error(`Cannot cache ${path}`);
      await shell.put(path, response);
    }
    const logos = await caches.open(LOGOS);
    const manifest = await fetch("/assets/local-manifest.json", { credentials: "same-origin", cache: "reload" });
    if (!manifest.ok || manifest.redirected) throw new Error("Cannot load local assets");
    const local = await manifest.json();
    const configured = Array.isArray(local.assets) ? local.assets.filter((path) =>
      typeof path === "string" && /^\/(?:assets\/(?:fonts|logos|local)\/[A-Za-z0-9_.-]+|assets\/local\.css|favicon\.(?:svg|ico)|apple-touch-icon\.png|manifest\.webmanifest)$/.test(path)) : [];
    await Promise.all([...CURATED_LOGOS, ...configured].map(async (path) => {
      const response = await fetch(path, { credentials: "same-origin", cache: "reload" });
      if (response.ok && !response.redirected) await logos.put(path, response);
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith(PREFIX) && name !== SHELL && name !== LOGOS)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate" && (url.pathname === "/" || url.pathname === "/index.html")) {
    event.respondWith((async () => {
      try {
        return await fetch(request);
      } catch (_) {
        return await caches.match("/") || Response.error();
      }
    })());
    return;
  }

  const dynamicLogo = /^\/assets\/company-logos\/[0-9a-f]{24}\.png$/.test(url.pathname);
  const localAsset = /^\/assets\/(?:fonts|logos|local)\/[A-Za-z0-9_.-]+$/.test(url.pathname);
  if (!SHELL_PATHS.has(url.pathname) && !CURATED_PATHS.has(url.pathname) && !dynamicLogo && !localAsset) return;
  event.respondWith((async () => {
    const cache = await caches.open(dynamicLogo || localAsset || CURATED_PATHS.has(url.pathname) ? LOGOS : SHELL);
    const cached = await cache.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok && !response.redirected) await cache.put(request, response.clone());
    return response;
  })());
});
