'use strict';

/* iptv-auto player service worker
 * Tries to let the HTTPS page play plain-HTTP streams:
 *  1) same-origin endpoint  .../iptv-play?u=<url>  (page requests https, SW fetches upstream)
 *  2) direct http:// requests that reach the SW (browser-dependent)
 * Upstream responses are passed through with CORS headers when readable;
 * opaque (no-cors) responses are returned as-is for media elements.
 */

function passthroughHeaders(up) {
  var h = new Headers();
  ['content-type', 'content-length', 'content-range', 'accept-ranges'].forEach(function (k) {
    var v = up.headers.get(k);
    if (v) h.set(k, v);
  });
  h.set('Access-Control-Allow-Origin', '*');
  h.set('Cache-Control', 'no-store');
  return h;
}

async function proxy(target, req, useNoCors) {
  var headers = {};
  var range = req.headers.get('Range');
  if (range) headers.Range = range;
  var up;
  try {
    up = await fetch(target, {
      headers: headers,
      redirect: 'follow',
      mode: useNoCors ? 'no-cors' : 'cors'
    });
  } catch (e1) {
    if (!useNoCors) return proxy(target, req, true);
    return new Response('proxy fetch failed: ' + e1.message, {
      status: 502,
      headers: { 'Access-Control-Allow-Origin': '*' }
    });
  }
  if (up.type === 'opaque') {
    // media elements can consume opaque no-cors responses
    return up;
  }
  return new Response(up.body, {
    status: up.status,
    statusText: up.statusText,
    headers: passthroughHeaders(up)
  });
}

self.addEventListener('fetch', function (event) {
  var url;
  try { url = new URL(event.request.url); } catch (e) { return; }

  if (url.pathname.indexOf('/iptv-play') !== -1) {
    var target = url.searchParams.get('u');
    if (target && /^https?:\/\//i.test(target)) {
      event.respondWith(proxy(target, event.request, false));
      return;
    }
  }

  if (url.protocol === 'http:') {
    event.respondWith(proxy(event.request.url, event.request, false));
  }
});

self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) { event.waitUntil(self.clients.claim()); });
