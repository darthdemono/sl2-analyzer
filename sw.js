// Offline support. The app already does all its work locally once loaded — the only
// reason it needs the network at all is to fetch itself and its item tables — so
// caching those makes it work with no connection, which suits a save analyzer.
//
// Deliberately NOT cached: the fextralife item thumbnails. They are cross-origin,
// they are the one request that leaves the browser, and quietly persisting them
// would make that leak outlive the tab.

const VERSION = "v5";
const CACHE = `sl2-analyzer-${VERSION}`;

// The app shell. Item tables are not listed: there are 40 of them across four games
// and a visitor needs one game's worth, so they are cached as they are actually
// requested rather than all downloaded up front.
const SHELL = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "icon.svg",
  "app/main.js",
  "app/worker.js",
  "app/parser.js",
  "app/render.js",
  "app/markdown.js",
  "app/jsonout.js",
  "app/tables.js",
  "app/reader.js",
  "app/aes.js",
  "app/db.js",
];

self.addEventListener("install", (e) => {
  // One missing file must not fail the whole install, so they are added
  // individually rather than with the all-or-nothing addAll.
  e.waitUntil(caches.open(CACHE)
    .then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {}))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const isDb = (url) => /\/db_(ds1|ds2|ds3|er)\//.test(url.pathname);

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;   // never touch the wiki images

  // Item tables are content-addressed in practice — a name/id table only changes
  // when the repo does — so serve them from cache and only hit the network on a
  // miss. This is what makes a second save of the same game load instantly.
  if (isDb(url)) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })));
    return;
  }

  // Everything else (the page and its modules) is network-first, so a deploy is
  // picked up on the next load instead of being pinned by the cache. Falling back
  // to the cache is what keeps the app working offline.
  e.respondWith(fetch(req)
    .then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })
    .catch(() => caches.match(req).then((hit) => hit || caches.match("index.html"))));
});
