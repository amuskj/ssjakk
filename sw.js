// SSJakk leaderboard service worker.
//
// Only makes the app *installable* and usable offline for its own shell
// (HTML/CSS/JS/icons) -- it deliberately never caches the *.json data
// files, since freshness matters far more here than offline access to
// last week's numbers. Bump CACHE_NAME whenever index.html changes so
// installed copies pick up the new shell instead of serving a stale one.
const CACHE_NAME = 'ssjakk-shell-v1';
const SHELL_FILES = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache data files or cross-origin requests (d3.js CDN, fonts,
  // Chess.com avatars) -- always go to the network for those.
  if (url.pathname.endsWith('.json') || url.origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
