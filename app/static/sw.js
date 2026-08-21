// Keep the app installable, but never intercept authenticated pages or API calls.
// Offline caching and HTTP Basic Auth can otherwise leave a stale, unusable shell.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(
  caches.keys()
    .then(keys=>Promise.all(keys.map(key=>caches.delete(key))))
    .then(()=>self.clients.claim())
));
