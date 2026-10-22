// Offline support: after the first visit the page, the runtime and the model come from this cache.
// Model files are requested with ?v=<sha256 prefix> from models/manifest.json, so new weights get new
// cache keys (cache-first is safe for them); everything else is network-first with the cache as fallback.
// COI = true also adds COOP/COEP headers, which makes the page cross-origin isolated on hosts that do not
// send them (static Spaces), so ONNX Runtime Web may use threads; it costs one reload on the first visit.
const CACHE = "antalia-mini-v1";
const COI = true;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

function withCoi(res) {
  if (!COI || res.status === 0 || res.type === "opaque") return res;
  const h = new Headers(res.headers);
  h.set("Cross-Origin-Opener-Policy", "same-origin");
  h.set("Cross-Origin-Embedder-Policy", "require-corp");
  // cross-origin, not same-origin: the page is embedded by huggingface.co, which is itself cross-origin
  // isolated, and an embedded document must allow that (same-origin made Chrome refuse to load the frame)
  h.set("Cross-Origin-Resource-Policy", "cross-origin");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

async function cacheFirst(req) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

async function networkFirst(req) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: req.mode === "navigate" });
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  const immutable = (sameOrigin && (/\/models\/.+\.onnx$/.test(url.pathname) && url.searchParams.has("v")))
    || (sameOrigin && url.pathname.includes("/vendor/"))
    || url.hostname === "fonts.gstatic.com";
  const p = immutable ? cacheFirst(req) : networkFirst(req);
  e.respondWith(sameOrigin ? p.then(withCoi) : p);
});
