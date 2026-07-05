const CACHE_NAME = 'clinic-cache-v1';
const RUNTIME_CACHE = 'clinic-runtime-v1';

const PRECACHE_URLS = [
  '/',
  '/static/manifest.json',
  '/static/apple-touch-icon.png',
  '/static/favicon.ico',
  '/static/style.css',
  '/static/css/layout.css',
  '/static/vendor/bootstrap/bootstrap.min.css',
  '/static/vendor/bootstrap-icons/bootstrap-icons.min.css',
  '/static/vendor/bootstrap/bootstrap.bundle.min.js',
  '/static/js/app.js',
];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(PRECACHE_URLS);
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function(event) {
  const cacheWhitelist = [CACHE_NAME, RUNTIME_CACHE];
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames.map(function(cacheName) {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') return;
  if (event.request.url.includes('/api/')) {
    event.respondWith(networkFirst(event));
  } else {
    event.respondWith(cacheFirst(event));
  }
});

function cacheFirst(event) {
  return caches.match(event.request).then(function(response) {
    if (response) return response;
    return fetch(event.request).then(function(networkResponse) {
      if (networkResponse && networkResponse.status === 200) {
        const copy = networkResponse.clone();
        caches.open(RUNTIME_CACHE).then(function(cache) {
          cache.put(event.request, copy);
        });
      }
      return networkResponse;
    });
  });
}

function networkFirst(event) {
  return fetch(event.request).then(function(response) {
    if (response && response.status === 200) {
      const copy = response.clone();
      caches.open(RUNTIME_CACHE).then(function(cache) {
        cache.put(event.request, copy);
      });
    }
    return response;
  }).catch(function() {
    return caches.match(event.request);
  });
}
