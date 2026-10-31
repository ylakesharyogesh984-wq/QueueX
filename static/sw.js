const CACHE_NAME = 'queuex-v4';
const APP_SHELL = [
  '/',
  '/student',
  '/offline',
  '/static/css/style.css',
  '/static/js/navbar.js',
  '/static/js/landing.js',
  '/static/js/student.js',
  '/static/js/pwa.js',
  '/static/img/icon.svg',
  '/static/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const requestUrl = new URL(event.request.url);
  if (
    requestUrl.pathname.startsWith('/socket.io/') ||
    requestUrl.pathname.startsWith('/api/') ||
    requestUrl.pathname.startsWith('/admin') ||
    requestUrl.pathname.startsWith('/operator') ||
    requestUrl.pathname.startsWith('/my-tokens') ||
    requestUrl.pathname.includes('/logout')
  ) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response && response.status === 200 && response.type === 'basic') {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then(cached => cached || caches.match('/offline')))
  );
});
