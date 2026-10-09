/* 홈 화면에 추가했을 때 화면 껍데기만 기억한다 — 항상 네트워크를 먼저 쓰고(새 버전 즉시 반영),
 * 끊겼을 때만 마지막으로 받은 껍데기를 보여 준다. 모은 글(/api/*)은 저장하지 않는다. */
const SHELL = 'osc-shell-v1';
const FILES = ['/', '/app.css', '/app.js', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match('/'))),
  );
});
