"""Emit the PWA primitives consumed by GitHub Pages:

- ``manifest.webmanifest`` -- Web App Manifest at the workspace root.
- ``service-worker.js``    -- offline-first cache + auto-update plumbing.
- ``robots.txt``           -- search-engine suppression (the trip site is public
  by URL but we don't want it indexed).
- ``assets/qr.png``        -- QR code that resolves to the landing URL (used by
  ``index.html`` and the README install section).

The ``BUILD_VERSION`` baked into ``service-worker.js`` is the cache namespace.
Bumping it forces installed clients to re-download on next visit. We derive it
from ``planning/trip_data.json`` (``generated_at`` + content hash) **and** the
Markdown sources for the standalone PWA pages, so edits invalidate the cache
even when ``trip_data.json`` is unchanged.

The site's public URL is read from the ``SITE_URL`` env var (set by the GitHub
Actions workflow). For local builds we fall back to a sensible
relative-path-only configuration; the manifest's ``start_url`` is left
relative (``./trip-itinerary.html``) so the same artifact works on any host.

QR generation requires the ``qrcode[pil]`` extra; if missing, we skip the QR
write with a warning so local builds without the optional dep still succeed.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402

BASE = _SCRIPTS.parent
PLAN = BASE / 'planning'
ASSETS = BASE / 'assets'

TRIP_DATA = PLAN / 'trip_data.json'
MANIFEST_OUT = BASE / 'manifest.webmanifest'
SW_OUT = BASE / 'service-worker.js'
ROBOTS_OUT = BASE / 'robots.txt'
QR_OUT = ASSETS / 'qr.png'

APP_NAME = f'{cfg.TRIP_TITLE} {cfg.TRIP_DATE_START[:4]}'
# Cache namespace prefix. Distinct per trip so a phone that still has the
# previous trip's PWA installed can't serve its cached pages for this one.
CACHE_SLUG = cfg.JS_PREFIX.lower() + '-trip'
APP_SHORT = cfg.PWA_SHORT_NAME
APP_DESC = cfg.META_DESCRIPTION
THEME_COLOR = '#0d1117'
BACKGROUND_COLOR = '#0d1117'

SITE_URL = os.environ.get('SITE_URL', '').rstrip('/')


def _build_version() -> str:
    """Cache namespace = trip_data.json + the sources of every standalone page.

    Anything that can change the shipped HTML without touching trip_data.json
    needs to be hashed here, otherwise installed PWAs keep serving stale pages.
    """
    raw = TRIP_DATA.read_bytes() if TRIP_DATA.exists() else b'no-data'
    extra_raw = b''
    for name in ('fuel_plan.md', 'fire_and_closures.md', 'camping_plan.md',
                 'lava_caves.md',
                 'weather_forecast_points.json', 'highway_tracks.json'):
        pth = PLAN / name
        extra_raw += pth.read_bytes() if pth.exists() else b''
    for name in ('weather.html', 'weather-client.js', 'index.html'):
        pth = BASE / name
        extra_raw += pth.read_bytes() if pth.exists() else b''
    short = hashlib.sha1(raw + extra_raw).hexdigest()[:10]
    try:
        gen = json.loads(raw.decode('utf-8')).get('generated_at', '')
    except Exception:
        gen = ''
    return f'{gen}-{short}' if gen else short


BUILD_VERSION = _build_version()


# Files the service worker pre-caches on install. Anything not in this list will
# still be cached on first online fetch (stale-while-revalidate), so this is
# the "must work offline from the very first launch" set.
PRECACHE = [
    './',
    'index.html',
    'trip-itinerary.html',
    'trip-reference.html',
    'fuel-plan.html',
    'fire-and-closures.html',
    'camping-plan.html',
    'lava-caves.html',
    'weather.html',
    'weather-client.js',
    'trip-plan.gpx',
    'manifest.webmanifest',
    'icons/icon-192.png',
    'icons/icon-512.png',
    'icons/icon-512-maskable.png',
    'icons/apple-touch-icon.png',
]


def write_manifest() -> None:
    manifest = {
        'name': APP_NAME,
        'short_name': APP_SHORT,
        'description': APP_DESC,
        'start_url': './trip-itinerary.html',
        'scope': './',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': BACKGROUND_COLOR,
        'theme_color': THEME_COLOR,
        'icons': [
            {
                'src': 'icons/icon-192.png',
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': 'icons/icon-512.png',
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'any',
            },
            {
                'src': 'icons/icon-512-maskable.png',
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'maskable',
            },
        ],
        # Long-press / right-click app icon (where supported): deep links into the PWA.
        'shortcuts': [
            {
                'name': 'Daily itinerary',
                'short_name': 'Itinerary',
                'description': 'Day-by-day route, maps, and weather strips',
                'url': './trip-itinerary.html',
                'icons': [{'src': 'icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}],
            },
            {
                'name': 'Trip weather',
                'short_name': 'Weather',
                'description': 'Dual NWS and Open-Meteo forecast for every camp',
                'url': './weather.html',
                'icons': [{'src': 'icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}],
            },
            {
                'name': 'Fire & closures',
                'short_name': 'Fire',
                'description': 'Go/no-go checks: forest alerts, restrictions, smoke',
                'url': './fire-and-closures.html',
                'icons': [{'src': 'icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}],
            },
            {
                'name': 'Lava caves',
                'short_name': 'Caves',
                'description': 'Falls Creek lava tube: permits, gear, how to find them',
                'url': './lava-caves.html',
                'icons': [{'src': 'icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}],
            },
            {
                'name': 'Full reference',
                'short_name': 'Reference',
                'description': 'Camps, fuel, hikes, emergency contacts, links',
                'url': './trip-reference.html',
                'icons': [{'src': 'icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}],
            },
        ],
    }
    MANIFEST_OUT.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    print(f'Wrote {MANIFEST_OUT.relative_to(BASE)}')


def write_service_worker() -> None:
    precache_js = json.dumps(PRECACHE, indent=2)
    cache_slug = CACHE_SLUG
    sw = f"""// Generated by scripts/build_pwa_assets.py -- do not hand-edit.
// Bump BUILD_VERSION (auto, derived from trip_data.json) to force a refresh on installed clients.

const BUILD_VERSION = {json.dumps(BUILD_VERSION)};
const CACHE_NAME = '{cache_slug}-' + BUILD_VERSION;
const PRECACHE = {precache_js};

self.addEventListener('install', (event) => {{
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
}});

self.addEventListener('activate', (event) => {{
  event.waitUntil((async () => {{
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
    await self.clients.claim();
  }})());
}});

self.addEventListener('message', (event) => {{
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
}});

// Fetch strategy:
// - Navigation requests: network-first with cache fallback (so a fresh visit
//   while online picks up new HTML; offline still works).
// - Other GETs: cache-first with background revalidate; fetched-fresh entries
//   are written back into the cache so subsequent offline opens have them.
self.addEventListener('fetch', (event) => {{
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // don't cache cross-origin map tiles

  if (req.mode === 'navigate') {{
    event.respondWith((async () => {{
      try {{
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, fresh.clone());
        return fresh;
      }} catch (e) {{
        let cached = await caches.match(req);
        // Precache stores weather.html; nav from itinerary uses weather.html?variant=…
        // which does not match the cache key unless we normalize.
        if (!cached) {{
          const leaf = (url.pathname || '').split('/').pop() || '';
          if (leaf === 'weather.html') {{
            cached = await caches.match('weather.html');
          }}
        }}
        if (!cached) cached = await caches.match('index.html');
        if (cached) return cached;
        throw e;
      }}
    }})());
    return;
  }}

  event.respondWith((async () => {{
    const cached = await caches.match(req);
    if (cached) {{
      // Revalidate in the background; ignore failures (offline is fine).
      fetch(req).then((fresh) => {{
        if (fresh && fresh.ok) caches.open(CACHE_NAME).then((c) => c.put(req, fresh));
      }}).catch(() => {{}});
      return cached;
    }}
    try {{
      const fresh = await fetch(req);
      if (fresh && fresh.ok) {{
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, fresh.clone());
      }}
      return fresh;
    }} catch (e) {{
      throw e;
    }}
  }})());
}});
"""
    SW_OUT.write_text(sw, encoding='utf-8')
    print(f'Wrote {SW_OUT.relative_to(BASE)} (BUILD_VERSION={BUILD_VERSION})')


def write_robots() -> None:
    ROBOTS_OUT.write_text(
        'User-agent: *\nDisallow: /\n',
        encoding='utf-8',
    )
    print(f'Wrote {ROBOTS_OUT.relative_to(BASE)}')


def write_qr() -> None:
    if not SITE_URL:
        print('Skipping QR (SITE_URL env var not set; safe for local builds)')
        return
    try:
        import qrcode  # type: ignore
    except ImportError:
        print('Skipping QR (qrcode[pil] not installed; pip install "qrcode[pil]")')
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    img = qrcode.make(SITE_URL + '/')
    img.save(QR_OUT)
    print(f'Wrote {QR_OUT.relative_to(BASE)} -> {SITE_URL}/')


def main() -> None:
    write_manifest()
    write_service_worker()
    write_robots()
    write_qr()


if __name__ == '__main__':
    main()
