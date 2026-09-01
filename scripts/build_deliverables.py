"""Generate trip-itinerary.html, trip-reference.html, and trip-plan.gpx from trip_data.json.

All HTML is offline-first: content is usable without internet. Leaflet's JS/CSS are inlined
from planning/vendor/leaflet/ and a low-res OpenStreetMap tile cache is base64-embedded from
planning/offline_tiles/, so the map renders with a pixelated-but-recognizable background even
when the page is viewed fully offline. When online, Esri tiles load on top of the offline
baseline. Run scripts/download_offline_tiles.py once to populate both caches.
"""
from __future__ import annotations
import base64
import html
import json
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402

BASE = _SCRIPTS.parent
PLAN = BASE / 'planning'
OUT_DIR = BASE
TILE_DIR = PLAN / 'offline_tiles'
VENDOR_DIR = PLAN / 'vendor' / 'leaflet'

# -----------------------------------------------------------------------------
# Variant registry. This trip has a single itinerary; the list is kept so the
# render loop stays generic if a future trip needs alternates again.
# All trip-identity strings come from trip_config.
# -----------------------------------------------------------------------------
MAIN_DATA_PATH = PLAN / 'trip_data.json'
MAIN_GPX_FILENAME = 'trip-plan.gpx'

_HEADER_META = (
    f'{cfg.TRIP_DATES_HUMAN} &middot; '
    f'{cfg.GROUP_COUNTS["vehicles"]} vehicles &middot; '
    f'Route: ~325 mi loop'
)

VARIANT_MAIN = {
    'key':                'main',
    'data_path':          MAIN_DATA_PATH,
    'html_path':          OUT_DIR / 'trip-itinerary.html',
    'gpx_path':           OUT_DIR / 'trip-plan.gpx',
    'gpx_filename':       'trip-plan.gpx',
    'page_title':         f'{cfg.TRIP_TITLE} - Itinerary',
    'header_h1':          cfg.TRIP_TITLE,
    'header_meta':        _HEADER_META,
    'nav_key':            'itinerary',
    'show_reference_link': True,
    'overview_title':     'Full route (325 mi loop)',
    'overview_desc_html': (
        'The stitched <strong>GPX driving corridor</strong> for all four route days, plus every '
        '<strong>POI and campground</strong> along it. The Sep 8 drive out from Nampa and the '
        'Sep 13 drive home are highway legs, not part of this polyline \u2014 '
        'use the per-day tabs for those.'
    ),
    'gpx_metadata_name':  f'{cfg.TRIP_TITLE} Trip Plan',
    'gpx_metadata_desc':  (
        f'Day-split tracks, POIs, and primary/backup campgrounds for the '
        f'{cfg.TRIP_DATES_HUMAN} trip.'
    ),
    'weather_key':        'main',
}

ALL_VARIANTS = [VARIANT_MAIN]


# Module-level `data`, `overview_track`, `ov_markers` get reassigned per
# variant inside `render_variant()`. They stay as module globals so the
# large build_itinerary_html / build_gpx / build_reference_html functions
# (and their helpers) don't need data threaded through every call site.
data = json.loads(MAIN_DATA_PATH.read_text(encoding='utf-8'))
overview_track = []  # filled by prepare_variant_context()
_WEATHER_FORECAST_PATH = PLAN / 'weather_forecast_points.json'
WEATHER_FORECAST = (
    json.loads(_WEATHER_FORECAST_PATH.read_text(encoding='utf-8'))
    if _WEATHER_FORECAST_PATH.exists()
    else {'variants': {}}
)


# -----------------------------------------------------------------------------
# Load locally-vendored Leaflet JS + CSS (downloaded by
# scripts/download_offline_tiles.py). Inlining them into the HTML makes the
# map work with zero internet -- otherwise the tile cache is useless because
# leaflet.js itself wouldn't load.
# -----------------------------------------------------------------------------
def _read_vendor(name, fallback=''):
    p = VENDOR_DIR / name
    return p.read_text(encoding='utf-8') if p.exists() else fallback


def _inline_css_images(css: str) -> str:
    """Rewrite leaflet.css's relative image URLs to base64 data URIs.

    The CSS is inlined into the HTML, so `url(images/layers.png)` resolves
    against the page path rather than a stylesheet directory and 404s. Inlining
    keeps the layers control and default marker working with zero requests,
    which is the whole point of an offline-first page.
    """
    for name in ('layers.png', 'layers-2x.png', 'marker-icon.png'):
        img = VENDOR_DIR / 'images' / name
        if not img.exists():
            print(f'Warning: {img.relative_to(BASE)} missing; '
                  f'leaflet.css will still request it and 404. '
                  f'Run scripts/download_offline_tiles.py.')
            continue
        uri = 'data:image/png;base64,' + base64.b64encode(img.read_bytes()).decode('ascii')
        css = css.replace(f'url(images/{name})', f'url({uri})')
    return css


LEAFLET_JS = _read_vendor('leaflet.js')
LEAFLET_CSS = _inline_css_images(_read_vendor('leaflet.css'))


# -----------------------------------------------------------------------------
# Shared PWA <head> block + service-worker registration. Injected into BOTH
# trip-itinerary.html and trip-reference.html so the two pages enroll in the
# same installed PWA (same manifest, same SW). Keeping a single source-of-
# truth here means the manifest link, theme color, and iOS metadata can never
# drift between the two pages.
#
# Both constants are plain strings that get spliced into the f-string HTML
# templates as variable substitutions ({PWA_HEAD} / {PWA_REGISTER_JS}); the
# f-string never reparses their contents, so JS object literals inside them
# do NOT need doubled braces.
# -----------------------------------------------------------------------------
PWA_HEAD = f"""<meta name="theme-color" content="#0d1117">
<meta name="description" content="{cfg.META_DESCRIPTION}">
<meta name="robots" content="noindex,nofollow">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="icons/icon-192.png">
<link rel="icon" type="image/png" sizes="512x512" href="icons/icon-512.png">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{cfg.PWA_TITLE}">
<meta name="mobile-web-app-capable" content="yes">"""


PWA_REGISTER_JS = """<script>
(function(){
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', function(){
    navigator.serviceWorker.register('service-worker.js').then(function(reg){
      reg.addEventListener('updatefound', function(){
        var nw = reg.installing;
        if (!nw) return;
        nw.addEventListener('statechange', function(){
          if (nw.state === 'installed' && navigator.serviceWorker.controller) {
            showUpdateToast(reg);
          }
        });
      });
    }).catch(function(){});
    var refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', function(){
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    });
  });
  function showUpdateToast(reg){
    if (document.getElementById('pwa-update-toast')) return;
    var t = document.createElement('div');
    t.id = 'pwa-update-toast';
    t.setAttribute('role', 'status');
    t.style.cssText = 'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#1f6feb;color:#fff;padding:12px 16px;border-radius:8px;font:14px/1.4 system-ui,sans-serif;z-index:9999;box-shadow:0 4px 14px rgba(0,0,0,.35);max-width:90vw;text-align:center;cursor:pointer';
    t.innerHTML = 'New trip data available. <strong>Tap to reload</strong>.';
    t.addEventListener('click', function(){
      if (reg.waiting) reg.waiting.postMessage({type: 'SKIP_WAITING'});
    });
    document.body.appendChild(t);
  }
})();
</script>"""


# localStorage keys for spoken-notes settings. JS_PREFIX keeps them unique per trip.
_SPEAK_KEY = cfg.JS_PREFIX.lower() + '-speak-notes'

# Shared read/write helper. Plain string spliced into itinerary, reference, and
# settings pages (same pattern as PWA_REGISTER_JS — no extra brace escaping).
SPEAK_SETTINGS_JS = f"""<script>
(function(global) {{
  var KEYS = {{
    enabled: '{_SPEAK_KEY}',
    scope: '{_SPEAK_KEY}-scope',
    landmarks: '{_SPEAK_KEY}-landmarks',
    repeat: '{_SPEAK_KEY}-repeat',
    voice: '{_SPEAK_KEY}-voice'
  }};
  function defaults() {{
    return {{ enabled: false, scope: 'all', landmarks: true, repeat: false, voice: '' }};
  }}
  function readBool(key, fallback) {{
    try {{
      var v = localStorage.getItem(key);
      if (v === null) return fallback;
      return v === '1' || v === 'true';
    }} catch (e) {{ return fallback; }}
  }}
  function readStr(key, fallback) {{
    try {{
      var v = localStorage.getItem(key);
      return (v == null || v === '') ? fallback : v;
    }} catch (e) {{ return fallback; }}
  }}
  function write(key, val) {{
    try {{ localStorage.setItem(key, val); }} catch (e) {{}}
  }}
  global.WcaSpeakSettings = {{
    keys: KEYS,
    sampleText: 'Washington Cascades. This is how notes will sound as you approach a stop.',
    read: function() {{
      var d = defaults();
      return {{
        enabled: readBool(KEYS.enabled, d.enabled),
        scope: readStr(KEYS.scope, d.scope) === 'included' ? 'included' : 'all',
        landmarks: readBool(KEYS.landmarks, d.landmarks),
        repeat: readBool(KEYS.repeat, d.repeat),
        voice: readStr(KEYS.voice, d.voice)
      }};
    }},
    write: function(partial) {{
      var cur = this.read();
      var next = Object.assign(cur, partial || {{}});
      write(KEYS.enabled, next.enabled ? '1' : '0');
      write(KEYS.scope, next.scope === 'included' ? 'included' : 'all');
      write(KEYS.landmarks, next.landmarks ? '1' : '0');
      write(KEYS.repeat, next.repeat ? '1' : '0');
      write(KEYS.voice, next.voice || '');
      return next;
    }},
    // Android Chrome often leaves voiceURI blank or identical across voices.
    // Name + lang is the stable identity; URI is only a tie-breaker.
    voiceKey: function(v) {{
      if (!v) return '';
      return [v.name || '', v.lang || '', v.voiceURI || ''].join('|');
    }},
    findVoice: function(key) {{
      if (!window.speechSynthesis) return null;
      var voices = speechSynthesis.getVoices() || [];
      if (!voices.length) return null;
      var i, v;
      if (key) {{
        for (i = 0; i < voices.length; i++) {{
          if (this.voiceKey(voices[i]) === key) return voices[i];
        }}
        var parts = String(key).split('|');
        var name = parts[0] || '';
        var lang = parts[1] || '';
        var uri = parts.slice(2).join('|');
        if (name || lang) {{
          for (i = 0; i < voices.length; i++) {{
            v = voices[i];
            if ((v.name || '') === name && (v.lang || '') === lang) return v;
          }}
        }}
        if (uri) {{
          var hits = [];
          for (i = 0; i < voices.length; i++) {{
            if (voices[i].voiceURI === uri) hits.push(voices[i]);
          }}
          if (hits.length === 1) return hits[0];
        }}
      }}
      var localEn = voices.filter(function(v) {{
        return v.localService && /^en/i.test(v.lang || '');
      }});
      if (localEn.length) {{
        return localEn.find(function(v) {{ return /en-US/i.test(v.lang || ''); }}) || localEn[0];
      }}
      var anyEn = voices.filter(function(v) {{ return /^en/i.test(v.lang || ''); }});
      if (anyEn.length) return anyEn[0];
      return voices.find(function(v) {{ return v.default; }}) || voices[0] || null;
    }},
    applyVoice: function(utterance, voice) {{
      if (!utterance || !voice) return;
      utterance.voice = voice;
      if (voice.lang) utterance.lang = voice.lang;
    }}
  }};
}})(window);
</script>"""


# Itinerary HTML pages use nav_key 'itinerary' — first nav item is "you are here".
ITINERARY_NAV_KEYS = frozenset({'itinerary'})

# Default sticky title row for satellite trip pages (weather, fuel, fire).
TRIP_BRAND_SHARED_HTML = (
    f'<h1>{cfg.TRIP_TITLE}</h1>'
    f'<div class="meta">{_HEADER_META}</div>'
)

# Shared trip nav: optional title row (brand left, Menu right) + link row (desktop below) or overlay (mobile).
# Nav links use the same orange as itinerary body links (:root --accent #ff9d45) without requiring :root on every page.
TOP_NAV_CSS = """
[data-trip-nav]{--trip-nav-link:#ff9d45}
/* --- Link-only bar (markdown / weather pages): no title row --- */
.top-nav[data-trip-nav]{position:sticky;top:0;z-index:10050;background:#161b22;border-bottom:1px solid #30363d;box-sizing:border-box}
.top-nav-menu-btn{display:none;align-items:center;justify-content:center;gap:8px;min-height:44px;min-width:88px;
  padding:0 16px;border:1px solid #484f58;border-radius:6px;background:#21262d;color:#f0f6fc;
  font:600 15px/1 system-ui,sans-serif;cursor:pointer;flex-shrink:0}
.top-nav-menu-btn:hover{border-color:#58a6ff;color:#58a6ff}
.top-nav-backdrop{display:none;position:fixed;left:0;right:0;top:48px;bottom:0;background:rgba(1,4,9,.55);z-index:10048}
.top-nav-list{list-style:none;margin:0;padding:0}
.top-nav-list>li{margin:0;padding:0}
.top-nav-list .top-nav-current{color:#f0f6fc;font-weight:600}
/* --- Branded chrome (itinerary / reference): title + meta | Menu, then links --- */
.trip-chrome[data-trip-nav]{position:sticky;top:0;z-index:10050;background:#0d1117;border-bottom:1px solid #30363d;box-sizing:border-box}
.trip-chrome-row1{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:14px 18px 10px}
.trip-chrome-brand{flex:1;min-width:0}
.trip-chrome-brand h1{margin:0 0 4px;font-size:22px;line-height:1.2;color:var(--text,#f0f6fc)}
.trip-chrome-brand .meta{color:var(--muted,#8b949e);font-size:13px;line-height:1.45}
.trip-chrome[data-trip-nav] .top-nav-menu-btn{margin:0;align-self:center}
.trip-chrome[data-trip-nav] .top-nav-backdrop{display:none;position:fixed;left:0;right:0;background:rgba(1,4,9,.55);z-index:10048}
@media (min-width:721px){
  .top-nav[data-trip-nav]{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:10px 18px;font-size:14px}
  .top-nav[data-trip-nav] .top-nav-menu-btn{display:none!important}
  .top-nav[data-trip-nav] .top-nav-backdrop{display:none!important}
  .top-nav[data-trip-nav] .top-nav-list{display:flex!important;flex-wrap:wrap;align-items:center;gap:4px 4px;flex:1;min-width:0}
  .top-nav[data-trip-nav] .top-nav-list>li{display:inline-block}
  .top-nav[data-trip-nav] .top-nav-list a,.top-nav[data-trip-nav] .top-nav-list .top-nav-current{display:inline;padding:6px 4px;margin-right:8px;font-size:14px;line-height:1.5}
  .top-nav[data-trip-nav] .top-nav-list .top-nav-current{color:#f0f6fc;font-weight:600}
  .top-nav[data-trip-nav] .top-nav-list a{text-decoration:none;color:var(--trip-nav-link)}
  .top-nav[data-trip-nav] .top-nav-list a:hover{text-decoration:underline}
  .trip-chrome[data-trip-nav] .top-nav-menu-btn{display:none!important}
  .trip-chrome[data-trip-nav] .top-nav-backdrop{display:none!important}
  .trip-chrome[data-trip-nav] .top-nav-list{display:flex!important;flex-wrap:wrap;align-items:center;gap:4px 8px;
    margin:0;padding:8px 18px 12px;border-top:1px solid #30363d;background:#161b22;font-size:14px}
  .trip-chrome[data-trip-nav] .top-nav-list>li{display:inline-block}
  .trip-chrome[data-trip-nav] .top-nav-list a,.trip-chrome[data-trip-nav] .top-nav-list .top-nav-current{display:inline;padding:6px 4px;margin-right:8px;line-height:1.5}
  .trip-chrome[data-trip-nav] .top-nav-list .top-nav-current{color:#f0f6fc;font-weight:600}
  .trip-chrome[data-trip-nav] .top-nav-list a{text-decoration:none;color:var(--trip-nav-link)}
  .trip-chrome[data-trip-nav] .top-nav-list a:hover{text-decoration:underline}
}
@media (max-width:720px){
  .top-nav[data-trip-nav]{display:flex;align-items:center;justify-content:flex-end;padding:8px 12px;min-height:48px}
  .top-nav[data-trip-nav] .top-nav-menu-btn{display:inline-flex!important;margin:0 0 0 auto}
  .top-nav:not(.is-open) .top-nav-list{display:none!important}
  .top-nav.is-open .top-nav-backdrop{display:block!important}
  .top-nav.is-open .top-nav-list{display:block!important;position:fixed;left:0;right:0;top:48px;bottom:0;overflow-y:auto;
    z-index:10052;background:#0d1117;border-top:1px solid #30363d;padding:8px 0 32px;box-shadow:0 8px 24px rgba(0,0,0,.45)}
  .top-nav.is-open .top-nav-list>li{border-bottom:1px solid #21262d}
  .top-nav.is-open .top-nav-list a,.top-nav.is-open .top-nav-list .top-nav-current{display:block;padding:16px 20px;min-height:48px;font-size:16px;line-height:1.35;text-decoration:none}
  .top-nav.is-open .top-nav-list a{color:var(--trip-nav-link)}
  .top-nav.is-open .top-nav-list .top-nav-current{color:#f0f6fc;font-weight:600;background:#161b22}
  .top-nav.is-open .top-nav-list a:active{background:#21262d}
  .trip-chrome-row1{padding:10px 14px}
  .trip-chrome-brand h1{font-size:18px}
  .trip-chrome-brand .meta{font-size:12px}
  .trip-chrome[data-trip-nav] .top-nav-menu-btn{display:inline-flex!important}
  .trip-chrome:not(.is-open) .top-nav-list{display:none!important}
  .trip-chrome.is-open .top-nav-backdrop{display:block!important}
  .trip-chrome.is-open .top-nav-list{display:block!important;position:fixed;left:0;right:0;bottom:0;overflow-y:auto;
    z-index:10052;background:#0d1117;border-top:1px solid #30363d;padding:8px 0 32px;box-shadow:0 8px 24px rgba(0,0,0,.45)}
  .trip-chrome.is-open .top-nav-list>li{border-bottom:1px solid #21262d}
  .trip-chrome.is-open .top-nav-list a,.trip-chrome.is-open .top-nav-list .top-nav-current{display:block;padding:16px 20px;min-height:48px;font-size:16px;line-height:1.35;text-decoration:none}
  .trip-chrome.is-open .top-nav-list a{color:var(--trip-nav-link)}
  .trip-chrome.is-open .top-nav-list .top-nav-current{color:#f0f6fc;font-weight:600;background:#161b22}
  .trip-chrome.is-open .top-nav-list a:active{background:#21262d}
}
"""

TRIP_NAV_MENU_JS = """
<script>
(function(){
function init(){
  var nav=document.querySelector('[data-trip-nav]');
  if(!nav)return;
  var btn=nav.querySelector('.top-nav-menu-btn');
  var list=nav.querySelector('.top-nav-list');
  var bd=nav.querySelector('.top-nav-backdrop');
  var row1=nav.querySelector('.trip-chrome-row1');
  if(!btn||!list)return;
  function syncOverlayGeom(){
    if(!nav.classList.contains('is-open'))return;
    var topPx=48;
    if(row1){
      var r=row1.getBoundingClientRect();
      topPx=Math.max(0,Math.floor(r.bottom));
      list.style.top=topPx+'px';
      list.style.maxHeight=(window.innerHeight-topPx)+'px';
      if(bd){
        bd.style.top=topPx+'px';
        bd.style.height=(window.innerHeight-topPx)+'px';
      }
    }else{
      var rn=nav.getBoundingClientRect();
      topPx=Math.max(0,Math.floor(rn.bottom));
      list.style.top=topPx+'px';
      list.style.maxHeight=(window.innerHeight-topPx)+'px';
      if(bd){bd.style.top=topPx+'px';bd.style.height=(window.innerHeight-topPx)+'px';}
    }
  }
  function clearOverlayGeom(){
    list.style.top='';list.style.maxHeight='';
    if(bd){bd.style.top='';bd.style.height='';}
  }
  function setOpen(o){
    nav.classList.toggle('is-open',o);
    btn.setAttribute('aria-expanded',o?'true':'false');
    if(bd)bd.hidden=!o;
    document.body.style.overflow=o?'hidden':'';
    if(o){
      syncOverlayGeom();
      window.addEventListener('resize',syncOverlayGeom);
    }else{
      window.removeEventListener('resize',syncOverlayGeom);
      clearOverlayGeom();
    }
  }
  btn.addEventListener('click',function(){
    setOpen(!nav.classList.contains('is-open'));
  });
  if(bd)bd.addEventListener('click',function(){setOpen(false);});
  var links=list.querySelectorAll('a');
  for(var i=0;i<links.length;i++){
    links[i].addEventListener('click',function(){setOpen(false);});
  }
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&nav.classList.contains('is-open'))setOpen(false);
  });
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);
else init();
})();
</script>
"""


def _top_nav_html(
    current: str,
    *,
    brand_html: str | None = None,
    weather_href: str | None = None,
    itinerary_href: str | None = None,
    gpx_href: str | None = None,
) -> str:
    """Trip-wide nav with mobile Menu + full-height link sheet.

    If ``brand_html`` is set (itinerary / reference), it is rendered in the left column
    of the sticky chrome row with the Menu button on the right; on wide screens the
    link list appears on a second row below. Markdown pages pass ``brand_html=None`` for
    a compact link-only bar.

    current highlights one page: 'itinerary' | 'reference' | 'weather' | 'fuel' |
    'fire' | 'camping' | 'caves' | 'settings' | 'none'.

    itinerary_href / weather_href / gpx_href override defaults for variant-specific pages.
    """
    weather_href = weather_href or 'weather.html'
    itinerary_href = itinerary_href or 'trip-itinerary.html'
    gpx_href = gpx_href or 'trip-plan.gpx'

    def li_itinerary() -> str:
        if current in ITINERARY_NAV_KEYS:
            return '<li class="top-nav-li-active"><span class="top-nav-current" aria-current="page">Daily itinerary</span></li>'
        return f'<li><a href="{esc(itinerary_href)}">Daily itinerary</a></li>'

    def li_link(href: str, label: str, key: str, *, download: bool = False) -> str:
        if current == key:
            return (
                f'<li class="top-nav-li-active"><span class="top-nav-current" aria-current="page">'
                f'{esc(label)}</span></li>'
            )
        dl = ' download' if download else ''
        return f'<li><a href="{esc(href)}"{dl}>{esc(label)}</a></li>'

    lis = [
        li_itinerary(),
        li_link('fuel-plan.html', 'Fuel plan', 'fuel'),
        li_link(weather_href, 'Weather', 'weather'),
        li_link('fire-and-closures.html', 'Fire & closures', 'fire'),
        li_link('camping-plan.html', 'Camping plan', 'camping'),
        li_link('lava-caves.html', 'Lava caves', 'caves'),
        li_link('trip-reference.html', 'Full reference', 'reference'),
        li_link('settings.html', 'Settings', 'settings'),
        li_link(gpx_href, 'GPX', '_gpx', download=True),
    ]
    ul = '<ul class="top-nav-list" id="top-nav-list">' + ''.join(lis) + '</ul>'
    btn = (
        '<button type="button" class="top-nav-menu-btn" aria-expanded="false" '
        'aria-controls="top-nav-list">Menu</button>'
    )
    backdrop = '<div class="top-nav-backdrop" hidden aria-hidden="true"></div>'
    if brand_html:
        return (
            '<header class="trip-chrome" data-trip-nav aria-label="Trip pages">'
            '<div class="trip-chrome-row1">'
            '<div class="trip-chrome-brand">' + brand_html + '</div>'
            + btn
            + '</div>'
            + backdrop
            + ul
            + '</header>'
        ) + TRIP_NAV_MENU_JS
    return (
        '<nav class="top-nav" data-trip-nav aria-label="Trip pages">'
        + btn
        + backdrop
        + ul
        + '</nav>'
    ) + TRIP_NAV_MENU_JS


# Compact styles for standalone markdown pages (slot guide, fuel plan; no map widgets).
STATIC_MD_PAGE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: #0d1117;
  color: #c9d1d9;
  padding: 0 0 48px;
  min-height: 100vh;
}
a { color: #58a6ff; }
""" + TOP_NAV_CSS + """
article.md-page {
  max-width: 920px;
  margin: 0 auto;
  padding: 20px 18px 40px;
}
article.md-page h1 {
  font-size: clamp(22px, 4vw, 28px);
  color: #f0f6fc;
  margin: 8px 0 12px;
}
article.md-page h2 {
  font-size: 18px;
  color: #f0f6fc;
  margin: 28px 0 12px;
  padding-top: 12px;
  border-top: 1px solid #21262d;
}
article.md-page h2:first-of-type { border-top: none; padding-top: 0; }
article.md-page h3 { font-size: 16px; color: #f0f6fc; margin: 18px 0 8px; }
article.md-page p { margin: 10px 0; }
article.md-page ul { padding-left: 22px; }
article.md-page li { margin: 6px 0; }
article.md-page pre {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 12px 14px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.45;
}
article.md-page table {
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 14px;
}
article.md-page th, article.md-page td {
  border: 1px solid #30363d;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
article.md-page th { background: #161b22; color: #f0f6fc; }
article.md-page code {
  background: #21262d;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}
article.md-page hr { border: none; border-top: 1px solid #30363d; margin: 22px 0; }
@media (max-width: 640px) {
  article.md-page { padding-left: 12px; padding-right: 12px; }
  article.md-page table { display: block; overflow-x: auto; max-width: 100vw; }
}
"""
def write_planning_markdown_pages():
    """Emit the standalone companion pages from planning/*.md (PWA-offline)."""
    try:
        import markdown
    except ImportError as e:
        raise SystemExit(
            'The "markdown" package is required to build standalone markdown HTML pages. '
            'Install with: pip install markdown'
        ) from e
    ext = ['tables', 'fenced_code']
    pages = [
        (
            PLAN / 'fuel_plan.md',
            OUT_DIR / 'fuel-plan.html',
            f'Fuel plan - {cfg.PWA_TITLE}',
            'fuel',
        ),
        (
            PLAN / 'fire_and_closures.md',
            OUT_DIR / 'fire-and-closures.html',
            f'Fire & closures - {cfg.PWA_TITLE}',
            'fire',
        ),
        (
            PLAN / 'camping_plan.md',
            OUT_DIR / 'camping-plan.html',
            f'Camping plan - {cfg.PWA_TITLE}',
            'camping',
        ),
        (
            PLAN / 'lava_caves.md',
            OUT_DIR / 'lava-caves.html',
            f'Lava caves - {cfg.PWA_TITLE}',
            'caves',
        ),
    ]
    for md_path, out_path, title, nav_key in pages:
        if not md_path.exists():
            print(f'Warning: {md_path.relative_to(BASE)} missing; skipping {out_path.name}')
            continue
        raw = md_path.read_text(encoding='utf-8')
        body = markdown.markdown(raw, extensions=ext)
        nav = _top_nav_html(nav_key, brand_html=TRIP_BRAND_SHARED_HTML)
        html_page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{PWA_HEAD}
<style>{STATIC_MD_PAGE_CSS}</style>
</head><body>
{nav}
<article class="md-page">
{body}
</article>
{PWA_REGISTER_JS}
</body></html>
"""
        out_path.write_text(html_page, encoding='utf-8')
        print(f'Wrote {out_path.name} ({len(html_page) / 1024:.1f} KB)')


# -----------------------------------------------------------------------------
# Load pre-downloaded OSM tiles (see scripts/download_offline_tiles.py) and
# encode them as base64 data URIs keyed by "z/x/y". This lets the Leaflet map
# render a low-res background when the page is viewed offline in the field.
# -----------------------------------------------------------------------------
def load_offline_tiles():
    tiles = {}
    if not TILE_DIR.exists():
        return tiles, 0
    total_bytes = 0
    for p in sorted(TILE_DIR.rglob('*.png')):
        parts = p.relative_to(TILE_DIR).parts
        if len(parts) != 3:
            continue
        z, x, yfile = parts
        y = yfile.rsplit('.', 1)[0]
        raw = p.read_bytes()
        total_bytes += len(raw)
        tiles[f'{z}/{x}/{y}'] = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
    return tiles, total_bytes


OFFLINE_TILES, OFFLINE_TILES_BYTES = load_offline_tiles()


# -----------------------------------------------------------------------------
# Decimate track points for HTML map display. Full precision remains for GPX.
# -----------------------------------------------------------------------------
def decimate(points, every_n):
    if not points:
        return []
    return [p for i, p in enumerate(points) if i % every_n == 0 or i == len(points) - 1]


# First itinerary tab: full route GPX corridor + aggregated stops (not a trip_data day).
ROUTE_OVERVIEW_ID = 'route_overview'


def prepare_variant_context(payload):
    """Decimate per-day and overview track points for HTML rendering.

    Mutates each day dict in `payload` by adding a `_map_points` key (the
    rendered HTML map uses these downsampled points; full-precision tracks
    stay available for GPX output). Returns the overview polyline so the
    caller can assign it to the module global."""
    for d in payload['days']:
        n_pts = len(d.get('track_points') or [])
        if n_pts > 0:
            d['_map_points'] = decimate(d['track_points'], max(1, n_pts // 120))
        else:
            d['_map_points'] = []
        extra = d.get('extra_track_points') or []
        # The highway leg is far longer than any route segment, so thin it just
        # as hard to keep the embedded payload small.
        d['_map_extra_points'] = decimate(extra, max(1, len(extra) // 120)) if extra else []
    # Overview = full trip, decimated hard (~400 pts total).
    full_track = []
    for d in payload['days']:
        full_track.extend(d.get('track_points') or [])
    every_n = max(1, len(full_track) // 400) if full_track else 1
    return decimate(full_track, every_n)


overview_track = prepare_variant_context(data)


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------
def esc(s):
    if s is None:
        return ''
    return html.escape(str(s))


def _map_chrome_html(wrap_id: str) -> str:
    """Locate + fullscreen buttons that sit over a Leaflet map.

    iPad Safari will not show a geolocation permission prompt unless the
    request is tied to a tap, and its Fullscreen API is a no-op for non-video
    elements. Both buttons are therefore real <button>s (user gesture) with
    44px touch targets.
    """
    wid = esc(wrap_id)
    return (
        f'<div class="map-chrome">'
        f'<button type="button" class="map-loc-btn" data-target="{wid}" '
        f'title="Show my GPS location on this map" aria-label="Show my location">'
        f'<span class="loc-icon" aria-hidden="true">&#x25CE;</span>'
        f'<span class="loc-label">My location</span></button>'
        f'<button type="button" class="map-fs-btn" data-target="{wid}" '
        f'title="Toggle fullscreen map (Esc to exit)" aria-label="Toggle fullscreen">'
        f'<span class="fs-icon fs-icon-enter" aria-hidden="true">&#x26F6;</span>'
        f'<span class="fs-icon fs-icon-exit" aria-hidden="true">&times;</span>'
        f'<span class="fs-label">Fullscreen</span></button>'
        f'</div>'
    )


def merge_weather_days(weather_key: str, trip_days: list) -> list:
    variants = WEATHER_FORECAST.get('variants') or {}
    template_rows = variants.get(weather_key)
    if not template_rows:
        raise SystemExit(
            f'planning/weather_forecast_points.json: missing or empty variant {weather_key!r}. '
            'Edit the file or fix weather_key on the variant.'
        )
    by_id = {d['id']: d for d in trip_days}
    out = []
    for row in template_rows:
        did = row['day_id']
        t = by_id.get(did)
        if not t:
            raise SystemExit(
                f"Weather day_id {did!r} not found in trip_data for variant {weather_key!r}"
            )
        merged = {**row, 'trip_label': t.get('label', did), 'trip_title': t.get('title', '')}
        out.append(merged)
    return out


def weather_day_section_html(day_id: str) -> str:
    # Option E layout: title row + dynamic block (KPI tiles, teaser, concerns, links, details) filled by weather-client.js
    return (
        '<section class="day-weather" data-day-weather="' + esc(day_id) + '" aria-live="polite">'
        '<div class="wx-head">'
        '<h3>Forecast for this day</h3>'
        '<p class="day-weather-loc"></p>'
        '</div>'
        '<div class="day-weather-dynamic muted">Loading forecasts…</div>'
        '</section>'
    )


def build_all_weather_day_payloads() -> dict:
    """Merged per-day rows for weather.html."""
    pairs = [('main', MAIN_DATA_PATH)]
    out: dict[str, list] = {}
    for wkey, path in pairs:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding='utf-8'))
        out[wkey] = merge_weather_days(wkey, payload['days'])
    return out


def write_weather_html() -> None:
    all_payload = build_all_weather_day_payloads()
    j = json.dumps(all_payload, ensure_ascii=False)
    nav = _top_nav_html('weather', brand_html=TRIP_BRAND_SHARED_HTML)
    extra_css = """
.weather-page-toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:12px 0}
#weather-refresh{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:8px 14px;border-radius:6px;cursor:pointer;font:inherit}
#weather-refresh:hover{border-color:#58a6ff}
.weather-trip-table{width:100%;font-size:14px}
.weather-concerns,.weather-concerns-tight{margin:6px 0;padding-left:1.2em;font-size:13px}
"""
    boot_lines = (
        f'<script>window.__{cfg.JS_PREFIX}_WEATHER_ALL__=' + j + ';</script>\n'
        '<script src="weather-client.js"></script>\n'
        '<script>'
        '(function(){'
        'var q=new URLSearchParams(location.search);'
        "var v=q.get('variant')||'main';"
        f'var all=window.__{cfg.JS_PREFIX}_WEATHER_ALL__||{{}};'
        'var days=all[v]||all.main||[];'
        "if(window.TripWeather)TripWeather.init({variantKey:v,days:days,mode:'weather_page',allVariants:all});"
        '})();'
        '</script>'
    )
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Trip weather — {cfg.PWA_TITLE}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{PWA_HEAD}
<style>{STATIC_MD_PAGE_CSS}</style>
<style>{extra_css}</style>
</head><body>
{nav}
<article class="md-page">
<h1>Trip weather — dual forecast</h1>
<p class="muted">NWS (NOAA) grid forecast and Open-Meteo, matched to each itinerary day and its camp location. Fetched when online and cached in this browser for offline use (about a 90-minute window). This does not replace the <a href="trip-itinerary.html">live NWS Washington alerts</a> strip on the itinerary, or the <a href="fire-and-closures.html">fire and closures</a> checks before departure.</p>
<p class="muted"><strong>September in the Cascades:</strong> the camps on this route sit between 3,900 and 4,400 ft and the passes go higher. Expect large day/night swings, real rain potential on the west side, and an outside chance of an early snow event at elevation. Freezing overnight temperatures at Takhlakh and Walupt are normal in mid-September.</p>
<div class="weather-page-toolbar">
<button type="button" id="weather-refresh">Refresh forecasts</button>
</div>
<p id="weather-status" class="muted"></p>
<table class="weather-trip-table" id="weather-trip-table">
<thead><tr><th>Day</th><th>NWS summary</th><th>Open-Meteo (daily)</th><th>Notable concerns</th></tr></thead>
<tbody id="weather-trip-tbody"></tbody>
</table>
<p class="muted" style="margin-top:16px"><strong>Sources:</strong> <a href="https://www.weather.gov/documentation/services-web-api" target="_blank" rel="noopener">api.weather.gov</a> · <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a> · Offices: <a href="https://www.weather.gov/pqr" target="_blank" rel="noopener">NWS Portland</a> · <a href="https://www.weather.gov/sew" target="_blank" rel="noopener">NWS Seattle</a></p>
</article>
{boot_lines}
{PWA_REGISTER_JS}
</body></html>
"""
    (OUT_DIR / 'weather.html').write_text(page, encoding='utf-8')
    print(f'Wrote weather.html ({len(page) / 1024:.1f} KB)')


def write_settings_html() -> None:
    """Trip settings page. Spoken notes is the first section."""
    nav = _top_nav_html('settings', brand_html=TRIP_BRAND_SHARED_HTML)
    extra_css = """
.settings-section{margin:8px 0 28px;padding:16px 16px 18px;background:#161b22;
  border:1px solid #30363d;border-radius:10px}
.settings-section h2{margin:0 0 8px;padding:0;border:0;font-size:18px;color:#f0f6fc}
.settings-row{display:flex;align-items:flex-start;gap:12px;margin:12px 0;cursor:pointer;
  min-height:44px}
.settings-row input[type=checkbox]{margin-top:4px;width:18px;height:18px;flex:none}
.settings-row span{flex:1;line-height:1.4}
.settings-fieldset{border:1px solid #30363d;border-radius:8px;margin:14px 0;padding:10px 14px 12px}
.settings-fieldset legend{padding:0 6px;color:#f0f6fc;font-weight:600}
.settings-fieldset label{display:flex;align-items:center;gap:10px;min-height:44px;cursor:pointer}
.settings-voice-label{display:block;margin:16px 0 6px;font-weight:600;color:#f0f6fc}
.settings-voice-row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;max-width:640px}
#speak-voice{display:block;flex:1 1 220px;min-height:44px;padding:8px 10px;
  background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;font:inherit}
#speak-voice:focus{outline:2px solid #58a6ff;outline-offset:1px}
#speak-voice-play{min-height:44px;padding:0 14px;background:#21262d;color:#e6edf3;
  border:1px solid #30363d;border-radius:6px;font:inherit;cursor:pointer}
#speak-voice-play:hover{border-color:#58a6ff}
.settings-hint{color:#8b949e;font-size:14px;margin:12px 0 0}
"""
    boot = r"""
<script>
(function(){
  var formEnabled = document.getElementById('speak-enabled');
  var formLandmarks = document.getElementById('speak-landmarks');
  var formRepeat = document.getElementById('speak-repeat');
  var formVoice = document.getElementById('speak-voice');
  var formFallback = document.getElementById('speak-voice-fallback');
  var scopeAll = document.querySelector('input[name="speak-scope"][value="all"]');
  var scopeInc = document.querySelector('input[name="speak-scope"][value="included"]');
  if (!window.WcaSpeakSettings) return;

  function applyForm(s) {
    formEnabled.checked = !!s.enabled;
    formLandmarks.checked = !!s.landmarks;
    formRepeat.checked = !!s.repeat;
    if (s.scope === 'included') scopeInc.checked = true;
    else scopeAll.checked = true;
  }
  applyForm(WcaSpeakSettings.read());

  function persistFromForm() {
    return WcaSpeakSettings.write({
      enabled: formEnabled.checked,
      landmarks: formLandmarks.checked,
      repeat: formRepeat.checked,
      scope: scopeInc.checked ? 'included' : 'all',
      voice: formVoice.value || WcaSpeakSettings.read().voice
    });
  }

  function unlockTts() {
    if (!window.speechSynthesis) return;
    try {
      var u = new SpeechSynthesisUtterance(' ');
      u.volume = 0;
      speechSynthesis.speak(u);
      speechSynthesis.cancel();
    } catch (e) {}
  }

  function defaultVoice(voices) {
    var localEn = voices.filter(function(v){ return v.localService && /^en/i.test(v.lang || ''); });
    if (localEn.length) {
      return localEn.find(function(v){ return /en-US/i.test(v.lang || ''); }) || localEn[0];
    }
    var anyEn = voices.filter(function(v){ return /^en/i.test(v.lang || ''); });
    if (anyEn.length) return anyEn[0];
    return voices.find(function(v){ return v.default; }) || voices[0] || null;
  }

  function fillVoices() {
    if (!window.speechSynthesis) {
      formVoice.hidden = true;
      formFallback.hidden = false;
      return;
    }
    formFallback.hidden = true;
    formVoice.hidden = false;
    var voices = speechSynthesis.getVoices() || [];
    var saved = WcaSpeakSettings.read().voice;
    var scored = voices.map(function(v){
      var local = !!v.localService;
      var en = /^en/i.test(v.lang || '');
      var score = (local && en) ? 0 : (local ? 1 : 2);
      return {v: v, score: score, local: local};
    }).sort(function(a, b){
      if (a.score !== b.score) return a.score - b.score;
      return String(a.v.name).localeCompare(String(b.v.name));
    });
    var keys = [];
    var seen = {};
    scored.forEach(function(item){
      var key = WcaSpeakSettings.voiceKey(item.v);
      if (!key || seen[key]) return;
      seen[key] = true;
      keys.push(key);
    });
    var listSig = keys.join('\n');
    if (formVoice.dataset.voiceKeys !== listSig) {
      var prev = formVoice.value;
      var added = {};
      formVoice.innerHTML = '';
      scored.forEach(function(item){
        var key = WcaSpeakSettings.voiceKey(item.v);
        if (!key || added[key]) return;
        added[key] = true;
        var opt = document.createElement('option');
        opt.value = key;
        opt.textContent = item.v.name + ' (' + (item.v.lang || '?') + ') — ' +
          (item.local ? 'on this device' : 'needs network');
        formVoice.appendChild(opt);
      });
      formVoice.dataset.voiceKeys = listSig;
      if (saved && Array.prototype.some.call(formVoice.options, function(o){ return o.value === saved; })) {
        formVoice.value = saved;
      } else if (prev && Array.prototype.some.call(formVoice.options, function(o){ return o.value === prev; })) {
        formVoice.value = prev;
      } else {
        var pick = defaultVoice(voices);
        if (pick) formVoice.value = WcaSpeakSettings.voiceKey(pick);
      }
    }
  }

  var _sampleTimer = null;
  function playSample() {
    if (!window.speechSynthesis) return;
    var key = formVoice.value;
    WcaSpeakSettings.write({voice: key});
    var voice = WcaSpeakSettings.findVoice(key);
    var busy = false;
    try { busy = !!(speechSynthesis.speaking || speechSynthesis.pending); } catch (e) {}
    try { speechSynthesis.cancel(); } catch (e) {}
    function go() {
      _sampleTimer = null;
      var u = new SpeechSynthesisUtterance(WcaSpeakSettings.sampleText);
      WcaSpeakSettings.applyVoice(u, voice);
      try { speechSynthesis.speak(u); } catch (e) {}
    }
    if (_sampleTimer) clearTimeout(_sampleTimer);
    // cancel() on Android can swallow a same-tick speak(); keep the first
    // tap in the user-gesture turn when nothing is already playing.
    if (busy) _sampleTimer = setTimeout(go, 80);
    else go();
  }

  formEnabled.addEventListener('change', function(){
    persistFromForm();
    if (formEnabled.checked) unlockTts();
    else if (window.speechSynthesis) { try { speechSynthesis.cancel(); } catch (e) {} }
  });
  formLandmarks.addEventListener('change', persistFromForm);
  formRepeat.addEventListener('change', persistFromForm);
  scopeAll.addEventListener('change', persistFromForm);
  scopeInc.addEventListener('change', persistFromForm);
  formVoice.addEventListener('change', function(){
    persistFromForm();
    playSample();
  });
  var playBtn = document.getElementById('speak-voice-play');
  if (playBtn) playBtn.addEventListener('click', playSample);

  fillVoices();
  if (window.speechSynthesis) {
    speechSynthesis.addEventListener('voiceschanged', fillVoices);
  }
})();
</script>
"""
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Settings — {cfg.PWA_TITLE}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{PWA_HEAD}
<style>{STATIC_MD_PAGE_CSS}</style>
<style>{extra_css}</style>
</head><body>
{nav}
<article class="md-page settings-page">
<h1>Settings</h1>
<p class="muted">Preferences stay on this device and work offline.</p>

<section class="settings-section" aria-labelledby="speak-notes-heading">
<h2 id="speak-notes-heading">Spoken notes</h2>
<p>Read a stop’s description out loud as you approach it. Uses voices already on this phone, so it works offline. Keep the itinerary open — the phone will not speak if the app is in the background or the screen is locked.</p>

<label class="settings-row">
  <input type="checkbox" id="speak-enabled">
  <span>Read descriptions as I approach</span>
</label>

<fieldset class="settings-fieldset">
  <legend>Which stops</legend>
  <label><input type="radio" name="speak-scope" value="all"> All POIs with a note or description</label>
  <label><input type="radio" name="speak-scope" value="included"> Only included stops</label>
</fieldset>

<label class="settings-row">
  <input type="checkbox" id="speak-landmarks">
  <span>Include distant landmarks (Rainier, Adams, St Helens, and other summit markers)</span>
</label>

<label class="settings-row">
  <input type="checkbox" id="speak-repeat">
  <span>Repeat when I return (after leaving about 1.2 miles)</span>
</label>

<label class="settings-voice-label" for="speak-voice">Voice</label>
<div class="settings-voice-row">
<select id="speak-voice" aria-describedby="speak-voice-fallback"></select>
<button type="button" id="speak-voice-play">Play sample</button>
</div>
<p id="speak-voice-fallback" class="muted" hidden>This browser cannot speak.</p>
<p class="settings-hint">Auto-read only works while the itinerary is open. Use Listen on a stop row anytime. Tap Stop to cancel a readout. If two list entries sound the same, they are usually the same engine with different language tags.</p>
</section>
</article>
{SPEAK_SETTINGS_JS}
{boot}
{PWA_REGISTER_JS}
</body></html>
"""
    (OUT_DIR / 'settings.html').write_text(page, encoding='utf-8')
    print(f'Wrote settings.html ({len(page) / 1024:.1f} KB)')


STATUS_BADGE = {
    'primary': ('primary', 'Primary'),
    'landmark': ('logistics', 'Landmark'),
    'backup': ('backup', 'Backup'),
    'skip': ('skip', 'Skip'),
    'logistics': ('logistics', 'Logistics'),
    'conditional': ('conditional', 'Conditional'),
    'hike_candidate': ('hike', 'Hike (tactical)'),
    'unclassified': ('unclassified', '--'),
}


def badge_html(status):
    cls, label = STATUS_BADGE.get(status, ('unclassified', status or '--'))
    return f'<span class="badge badge-{cls}">{esc(label)}</span>'


# Companion pages reached from a stop inside the itinerary / reference, not
# only from the top nav. Same-window links so they stay inside the installed PWA.
POI_APP_PAGES = {
    'DP - Falls Creek Lava Caves': {
        'href': 'lava-caves.html',
        'label': 'Cave notes',
    },
}


def poi_page_link_html(name: str) -> str:
    info = POI_APP_PAGES.get(name)
    if not info:
        return ''
    return (
        f' <a class="poi-page-link" href="{esc(info["href"])}">'
        f'{esc(info["label"])}</a>'
    )


def desc_button_html(name, desc):
    """Return an inline 'notes' icon button that opens the POI description dialog,
    or '' if no description is available. The button is keyed by POI name; the
    dialog script looks up descriptions from an embedded JSON map."""
    if not desc:
        return ''
    return (
        ' <button type="button" class="desc-btn" '
        f'data-desc-name="{esc(name)}" '
        'aria-label="Show description" title="Show description">'
        '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
        '<path fill="currentColor" d="M3 1.5h7.293a1 1 0 0 1 .707.293l2.5 2.5a1 1 0 0 1 .293.707V14.5a.5.5 0 0 1-.5.5H3a.5.5 0 0 1-.5-.5v-13a.5.5 0 0 1 .5-.5zM10 2v3h3L10 2zM4.5 7h7v1h-7zm0 2h7v1h-7zm0 2h5v1h-5z"/>'
        '</svg></button>'
    )


def speak_button_html(name, desc, note, speak_id=''):
    """Inline speaker button that reads the POI desc (or note fallback)."""
    if not (desc or '').strip() and not (note or '').strip():
        return ''
    sid = f' data-speak-id="{esc(speak_id)}"' if speak_id else ''
    return (
        ' <button type="button" class="speak-btn" '
        f'data-speak-name="{esc(name)}"{sid} '
        'aria-label="Listen to description" title="Listen">'
        '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
        '<path fill="currentColor" d="M2.5 6.5v3h2.2L8 12.3V3.7L4.7 6.5H2.5zm8.2 1.5a2.2 2.2 0 0 0-1.2-1.95v3.9A2.2 2.2 0 0 0 10.7 8zm1.6 0a3.8 3.8 0 0 0-2.1-3.4v1.1a2.7 2.7 0 0 1 0 4.6v1.1A3.8 3.8 0 0 0 12.3 8z"/>'
        '</svg></button>'
    )


def _scheduled_merged_pois(day):
    """Same merge + sort as the itinerary Stops table (ids must match)."""
    return sorted(
        [p for p in (day.get('pois') or [])
         if p.get('status') in ('primary', 'hike_candidate', 'conditional', 'backup')],
        key=lambda p: p['mile'],
    )


def collect_speakable_pois(trip_data):
    """POIs with a desc or note and coordinates, for approach TTS + Listen.

    Scheduled-table rows use the same ``{dayId}-{idx}`` ids as ``poi_row``.
    Logistics/landmarks that are not in that table get ``{dayId}-extra-{i}``.
    """
    out = []
    seen = set()
    for d in trip_data.get('days') or []:
        day_id = d['id']
        pois = d.get('pois') or []
        merged = _scheduled_merged_pois(d) if d.get('schedule') else []
        merged_ids = {id(p): f'{day_id}-{i}' for i, p in enumerate(merged)}
        for i, p in enumerate(pois):
            if p.get('status') == 'skip':
                continue
            desc = (p.get('desc') or '').strip()
            note = (p.get('note') or '').strip()
            if not desc and not note:
                continue
            lat, lon = p.get('lat'), p.get('lon')
            if lat is None or lon is None:
                continue
            pid = merged_ids.get(id(p), f'{day_id}-extra-{i}')
            if pid in seen:
                continue
            seen.add(pid)
            out.append({
                'id': pid,
                'dayId': day_id,
                'name': p['name'],
                'lat': lat,
                'lon': lon,
                'desc': desc,
                'note': note,
                'status': p.get('status') or '',
                'sched': id(p) in merged_ids,
            })
    return out


# Injected after WcaSpeakSettings. __POIS__ is replaced with JSON.
SPEAK_ENGINE_JS = r"""
const SPEAKABLE_POIS = __POIS__;
const SPEAK_TRIGGER_MI = 0.5;
const SPEAK_LEAVE_MI = 1.2;
let _speakGen = 0;
let _speakQueue = [];
let _speakCurrent = null;
let _speakAnnounced = new Set();
let _speakResumeTimer = null;
let _speakWakeLock = null;

function _speakHavMi(lat1, lon1, lat2, lon2) {
  const R = 3958.7613;
  const tr = x => x * Math.PI / 180;
  const dLa = tr(lat2 - lat1), dLo = tr(lon2 - lon1);
  const a = Math.sin(dLa/2)**2 + Math.cos(tr(lat1))*Math.cos(tr(lat2))*Math.sin(dLo/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
function _speakStripUrls(s) {
  return String(s || '').replace(/https?:\/\/\S+/gi, ' ').replace(/\s+/g, ' ').trim();
}
function _speakParagraphs(text) {
  return String(text || '').split(/\n\s*\n/).map(function(p) {
    return _speakStripUrls(p.replace(/\n/g, ' '));
  }).filter(Boolean);
}
function _speakBodyForPoi(poi) {
  return ((poi && poi.desc) || '').trim() || ((poi && poi.note) || '').trim();
}
function _speakPickVoice(key) {
  if (window.WcaSpeakSettings && typeof WcaSpeakSettings.findVoice === 'function') {
    return WcaSpeakSettings.findVoice(key);
  }
  if (!window.speechSynthesis) return null;
  const voices = speechSynthesis.getVoices() || [];
  const localEn = voices.filter(v => v.localService && /^en/i.test(v.lang || ''));
  if (localEn.length) {
    return localEn.find(v => /en-US/i.test(v.lang || '')) || localEn[0];
  }
  const anyEn = voices.filter(v => /^en/i.test(v.lang || ''));
  if (anyEn.length) return anyEn[0];
  return voices.find(v => v.default) || voices[0] || null;
}
function _speakUnlock() {
  if (!window.speechSynthesis) return;
  try {
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0;
    speechSynthesis.speak(u);
    speechSynthesis.cancel();
  } catch (e) {}
}
function _speakRequestWake() {
  if (!navigator.wakeLock || typeof navigator.wakeLock.request !== 'function') return;
  navigator.wakeLock.request('screen').then(function(lock) {
    _speakWakeLock = lock;
  }).catch(function() {});
}
function _speakReleaseWake() {
  if (_speakWakeLock) {
    try { _speakWakeLock.release(); } catch (e) {}
    _speakWakeLock = null;
  }
}
function _speakShowBar(name) {
  let bar = document.getElementById('wca-speak-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'wca-speak-bar';
    bar.setAttribute('role', 'status');
    bar.innerHTML = '<span class="speak-bar-name"></span>' +
      '<button type="button" class="speak-bar-stop">Stop</button>';
    bar.querySelector('.speak-bar-stop').addEventListener('click', function() {
      const id = _speakCurrent && _speakCurrent.id;
      _speakCancel();
      if (id) _speakAnnounced.add(id);
    });
    document.body.appendChild(bar);
  }
  bar.querySelector('.speak-bar-name').textContent = name || 'Reading…';
  bar.hidden = false;
}
function _hideSpeakBar() {
  const bar = document.getElementById('wca-speak-bar');
  if (bar) bar.hidden = true;
}
function _speakCancel() {
  _speakGen += 1;
  _speakQueue = [];
  _speakCurrent = null;
  if (window.speechSynthesis) {
    try { speechSynthesis.cancel(); } catch (e) {}
  }
  if (_speakResumeTimer) {
    clearInterval(_speakResumeTimer);
    _speakResumeTimer = null;
  }
  _hideSpeakBar();
  _speakReleaseWake();
}
function _speakStartUtterances(poi, texts) {
  if (!window.speechSynthesis || !texts || !texts.length) return;
  _speakCancel();
  const gen = ++_speakGen;
  _speakCurrent = poi;
  const settings = (window.WcaSpeakSettings && WcaSpeakSettings.read()) || {};
  const voice = _speakPickVoice(settings.voice);
  _speakQueue = texts.slice();
  _speakShowBar(poi && poi.name);
  _speakRequestWake();
  if (!_speakResumeTimer) {
    _speakResumeTimer = setInterval(function() {
      try { if (speechSynthesis.paused) speechSynthesis.resume(); } catch (e) {}
    }, 8000);
  }
  function next() {
    if (gen !== _speakGen) return;
    if (!_speakQueue.length) {
      const doneId = _speakCurrent && _speakCurrent.id;
      if (gen === _speakGen) _speakCancel();
      if (doneId) _speakAnnounced.add(doneId);
      return;
    }
    const chunk = _speakQueue.shift();
    const u = new SpeechSynthesisUtterance(chunk);
    if (window.WcaSpeakSettings && WcaSpeakSettings.applyVoice) {
      WcaSpeakSettings.applyVoice(u, voice);
    } else if (voice) {
      u.voice = voice;
      if (voice.lang) u.lang = voice.lang;
    }
    u.rate = 0.95;
    u.onend = function() { if (gen === _speakGen) next(); };
    u.onerror = function() { if (gen === _speakGen) next(); };
    try { speechSynthesis.speak(u); } catch (e) { next(); }
  }
  next();
}
function speakPoi(poi) {
  if (!poi) return;
  const body = _speakBodyForPoi(poi);
  if (!body) return;
  const texts = _speakParagraphs(body);
  texts.unshift((poi.name || 'Stop') + '.');
  if (poi.id) _speakAnnounced.add(poi.id);
  _speakStartUtterances(poi, texts);
}
function _speakFindPoi(id, name) {
  if (id) {
    for (let i = 0; i < SPEAKABLE_POIS.length; i++) {
      if (SPEAKABLE_POIS[i].id === id) return SPEAKABLE_POIS[i];
    }
  }
  if (name) {
    for (let i = 0; i < SPEAKABLE_POIS.length; i++) {
      if (SPEAKABLE_POIS[i].name === name) return SPEAKABLE_POIS[i];
    }
  }
  return null;
}
function _speakIsIncluded(poi) {
  if (!poi || !poi.sched) return false;
  const tr = document.querySelector('tr[data-poi-id="' + poi.id + '"]');
  if (!tr) return false;
  const cb = tr.querySelector('.poi-include');
  return !!(cb && cb.checked);
}
function _speakOnGps(lat, lon) {
  const settings = window.WcaSpeakSettings && WcaSpeakSettings.read();
  if (!settings || !settings.enabled) return;
  if (_speakCurrent) return;
  let best = null;
  let bestD = Infinity;
  for (let i = 0; i < SPEAKABLE_POIS.length; i++) {
    const p = SPEAKABLE_POIS[i];
    if (!settings.landmarks && p.status === 'landmark') continue;
    if (settings.scope === 'included' && !_speakIsIncluded(p)) continue;
    const d = _speakHavMi(lat, lon, p.lat, p.lon);
    if (d > SPEAK_LEAVE_MI && settings.repeat) {
      _speakAnnounced.delete(p.id);
    }
    if (d <= SPEAK_TRIGGER_MI && !_speakAnnounced.has(p.id) && d < bestD) {
      bestD = d;
      best = p;
    }
  }
  if (best) speakPoi(best);
}
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.speak-btn');
  if (!btn) return;
  e.preventDefault();
  _speakUnlock();
  const poi = _speakFindPoi(btn.dataset.speakId, btn.dataset.speakName);
  if (poi) speakPoi(poi);
});
window.addEventListener('storage', function(e) {
  if (!e.key || e.key.indexOf('wca-speak-notes') !== 0) return;
  const settings = window.WcaSpeakSettings && WcaSpeakSettings.read();
  if (!settings || !settings.enabled) _speakCancel();
});
if (window.speechSynthesis) {
  speechSynthesis.addEventListener('voiceschanged', function() {});
}
"""


def _speak_engine_js(trip_data):
    pois_json = json.dumps(collect_speakable_pois(trip_data), ensure_ascii=False)
    return '<script>\n' + SPEAK_ENGINE_JS.replace('__POIS__', pois_json) + '\n</script>'


def collect_poi_descriptions(data):
    """Return a dict keyed by POI name -> {desc, sym, mile, off_m} gathered from
    every day's POIs. Duplicates across days keep the first occurrence; since
    POI names are unique in the source GPX this is effectively name -> info."""
    out = {}
    for d in data['days']:
        for p in (d.get('pois') or []):
            desc = (p.get('desc') or '').strip()
            if not desc or p['name'] in out:
                continue
            entry = {
                'desc': desc,
                'sym':  p.get('sym') or '',
                'mile': p.get('mile'),
                'off':  p.get('dist_to_track_m') or 0,
                'lat':  p.get('lat'),
                'lon':  p.get('lon'),
                'day':  d.get('label') or d.get('id'),
            }
            page = POI_APP_PAGES.get(p['name'])
            if page:
                entry['page'] = page
            out[p['name']] = entry
    return out


# Inserted just before </main> in both deliverable HTMLs
POI_DESC_DIALOG_HTML = """
<dialog id="poi-desc-dialog" aria-labelledby="poi-desc-title">
  <div class="dialog-head">
    <div>
      <h3 id="poi-desc-title">--</h3>
      <div class="dialog-sub" id="poi-desc-sub"></div>
    </div>
    <button type="button" class="dialog-close" aria-label="Close">&times;</button>
  </div>
  <div class="dialog-body" id="poi-desc-body">--</div>
</dialog>
"""


# Inserted inside the page's <script> block. {desc_json} is substituted with the
# embedded description map. Uses double braces because the containing template
# is an f-string.
POI_DESC_DIALOG_JS = """
// ----- POI description dialog (offline-first) -----
const POI_DESCRIPTIONS = {desc_json};
(function() {{
  const dlg   = document.getElementById('poi-desc-dialog');
  if (!dlg) return;
  const title = dlg.querySelector('#poi-desc-title');
  const sub   = dlg.querySelector('#poi-desc-sub');
  const body  = dlg.querySelector('#poi-desc-body');
  const close = dlg.querySelector('.dialog-close');

  function escHTML(s) {{
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  }}
  function render(name) {{
    const info = POI_DESCRIPTIONS[name];
    if (!info) return false;
    title.textContent = name;
    const bits = [];
    if (info.mile != null)
      bits.push('mile <code>' + info.mile.toFixed(1) + '</code>');
    if (info.sym)
      bits.push('type <code>' + escHTML(info.sym) + '</code>');
    if (info.off)
      bits.push(Math.round(info.off) + ' m off-track');
    if (info.lat != null && info.lon != null)
      bits.push('<a href="https://www.google.com/maps/search/?api=1&query=' +
                info.lat + ',' + info.lon + '" target="_blank" rel="noopener">Map It</a>');
    sub.innerHTML = bits.join(' &middot; ');
    const paragraphs = info.desc.split(/\\n\\s*\\n/).map(p => p.trim()).filter(Boolean);
    let pageLink = '';
    if (info.page && info.page.href) {{
      const lbl = escHTML(info.page.label || 'Open notes page');
      pageLink = '<p class="poi-app-page"><a href="' + escHTML(info.page.href) + '">' +
                 lbl + '</a> &mdash; in this app, works offline.</p>';
    }}
    body.innerHTML = pageLink +
                     paragraphs.map(p => '<p>' + escHTML(p).replace(/\\n/g, '<br>') + '</p>').join('') +
                     '<div class="src">Source: original route GPX (On The Go Crew).</div>';
    return true;
  }}
  document.addEventListener('click', function(e) {{
    const btn = e.target.closest('.desc-btn');
    if (!btn) return;
    e.preventDefault();
    const name = btn.dataset.descName;
    if (render(name)) dlg.showModal();
  }});
  close.addEventListener('click', () => dlg.close());
  // Click the backdrop (outside the dialog content) to close.
  dlg.addEventListener('click', function(e) {{
    if (e.target === dlg) {{
      const r = dlg.getBoundingClientRect();
      const inside = e.clientX >= r.left && e.clientX <= r.right
                  && e.clientY >= r.top  && e.clientY <= r.bottom;
      if (!inside) dlg.close();
    }}
  }});
}})();
"""


POI_HEADER = (
    '<thead><tr><th>Mi</th><th>Name</th><th>Status</th><th>Type</th>'
    '<th>Note</th><th>Off-track</th><th>Coords</th></tr></thead>'
)
OVERVIEW_STOPS_HEADER = (
    '<thead><tr><th>Mi</th><th>Day</th><th>Name</th><th>Status</th><th>Type</th>'
    '<th>Note</th><th>Off-track</th><th>Coords</th></tr></thead>'
)
POI_HEADER_SCHEDULED = (
    '<thead><tr><th title="Include in scheduled itinerary">In?</th>'
    '<th>Mi</th><th>Name</th><th>Status</th><th>Type</th>'
    '<th>Note</th><th>Off-track</th><th>Coords</th>'
    '<th title="Estimated time of arrival">ETA</th>'
    '<th title="Estimated time spent at the stop, in minutes">Stop (min)</th></tr></thead>'
)


def poi_row(p, day_id=None, allow_focus=False, scheduled=False, idx=0, day_mph=20):
    lat, lon = p.get('lat'), p.get('lon')
    name_text = esc(p['name'])
    if allow_focus and day_id and lat is not None and lon is not None:
        name_html = (
            f'<a href="#" class="focus-map" data-day="{esc(day_id)}" '
            f'data-lat="{lat}" data-lon="{lon}" '
            f'title="Zoom map to this stop">{name_text}</a>'
        )
    else:
        name_html = name_text
    name_html += desc_button_html(p['name'], p.get('desc'))
    speak_id = f'{day_id}-{idx}' if scheduled and day_id else ''
    name_html += speak_button_html(p['name'], p.get('desc'), p.get('note'), speak_id)
    name_html += poi_page_link_html(p['name'])
    coords_html = ''
    if lat is not None and lon is not None:
        gm = f'https://www.google.com/maps/search/?api=1&query={lat},{lon}'
        coords_html = (
            f'<code>{lat:.5f}, {lon:.5f}</code> &middot; '
            f'<a href="{gm}" target="_blank" rel="noopener">Map It</a>'
        )

    # data-label values surface as row headings in the mobile card layout
    # (see @media (max-width: 720px) in the stylesheet).
    if not scheduled:
        return (
            '<tr>'
            f'<td class="num" data-label="Mile">{p["mile"]:.1f}</td>'
            f'<td class="td-name" data-label="Name">{name_html}</td>'
            f'<td data-label="Status">{badge_html(p["status"])}</td>'
            f'<td data-label="Type">{esc(p.get("sym") or "")}</td>'
            f'<td data-label="Note">{esc(p.get("note") or "")}</td>'
            f'<td class="num" data-label="Off-track" title="distance from main route track">{p.get("dist_to_track_m", 0):.0f} m</td>'
            f'<td class="coords" data-label="Coords">{coords_html}</td>'
            '</tr>'
        )

    # Scheduled-day row: include checkbox, ETA cell, duration input.
    poi_id = f'{day_id}-{idx}'
    default_min = int(p.get('default_minutes', 20))
    default_checked = bool(p.get('default_checked', False))
    checked_attr = ' checked' if default_checked else ''
    spur_mi = float(p.get('spur_mi') or 0.0)
    spur_hint = ''
    if spur_mi > 0:
        # Initial hint uses the day's default mph; the live scheduler recomputes
        # as the mph input changes. Best-effort: the text is a seed, not truth.
        mph_for_hint = max(3, day_mph)
        mins_hint = round(spur_mi / mph_for_hint * 60)
        spur_hint = (
            f'<div class="spur-hint" title="This stop sits at the end of an out-and-back spur. '
            f'Unchecking it subtracts the spur miles from the rest of the day\'s drive time.">'
            f'Spur: ~{spur_mi:.1f} mi &middot; saves ~{mins_hint} min at {mph_for_hint} mph</div>'
        )
    return (
        f'<tr data-poi-id="{esc(poi_id)}" data-mile="{p["mile"]}" '
        f'data-lat="{lat}" data-lon="{lon}" '
        f'data-offtrack="{p.get("dist_to_track_m", 0)}" '
        f'data-spur-mi="{spur_mi}" '
        f'data-status="{esc(p["status"])}" '
        f'data-default-checked="{str(default_checked).lower()}" '
        f'data-default-duration="{default_min}">'
        f'<td class="num td-include" data-label="Include">'
        f'<label class="poi-include-wrap" aria-label="Include this stop">'
        f'<input type="checkbox" class="poi-include"{checked_attr}>'
        f'</label></td>'
        f'<td class="num" data-label="Mile">{p["mile"]:.1f}</td>'
        f'<td class="td-name" data-label="Name">{name_html}{spur_hint}</td>'
        f'<td data-label="Status">{badge_html(p["status"])}</td>'
        f'<td data-label="Type">{esc(p.get("sym") or "")}</td>'
        f'<td data-label="Note">{esc(p.get("note") or "")}</td>'
        f'<td class="num" data-label="Off-track" title="distance from main route track">{p.get("dist_to_track_m", 0):.0f} m</td>'
        f'<td class="coords" data-label="Coords">{coords_html}</td>'
        f'<td class="num poi-eta" data-label="ETA">--</td>'
        f'<td class="num td-duration" data-label="Stop (min)"><input type="number" class="poi-duration" value="{default_min}" min="0" step="5"></td>'
        '</tr>'
    )


def _iter_camp_entries(camps):
    """Yield (tier_key, entry_idx, tier_total, camp_dict) across all camps for a
    day. Each tier value may be a single dict (legacy) or a list of dicts (new
    for days like the Wedge where all backups are equal-tier designated sites).
    entry_idx is 1-based; tier_total is the count within that tier so callers
    can conditionally append an "A/B/C" suffix when there are multiples."""
    if not isinstance(camps, dict):
        return
    for key in ('primary', 'secondary', 'tertiary'):
        val = camps.get(key)
        if not val:
            continue
        items = val if isinstance(val, list) else [val]
        items = [c for c in items if isinstance(c, dict)]
        total = len(items)
        for idx, c in enumerate(items, 1):
            yield key, idx, total, c


def _camp_has_coords(c):
    return isinstance(c, dict) and c.get('lat') and c.get('lon')


def _tier_label(key, idx, total):
    """'Primary', 'Secondary', 'Tertiary' -- append ' A/B/C' only when a tier
    holds multiple equal-rank options."""
    base = key.title()
    if total > 1:
        base += f' {chr(ord("A") + idx - 1)}'
    return base


def _collect_route_overview_markers(days_list):
    """POI + camp pins for travel + overland days; deduped; names include day label."""
    markers = []
    seen = set()

    def add_marker(mk):
        key = (round(mk['lat'], 6), round(mk['lon'], 6), mk['name'])
        if key in seen:
            return
        seen.add(key)
        markers.append(mk)

    for d in days_list:
        if d.get('type') not in ('travel', 'overland'):
            continue
        dl = d['label']
        for p in d.get('pois') or []:
            if p.get('status') == 'skip' or not p.get('lat') or not p.get('lon'):
                continue
            add_marker({
                'lat': p['lat'], 'lon': p['lon'],
                'name': f'{p["name"]} ({dl})',
                'kind': 'poi',
            })
        for key, idx, total, c in _iter_camp_entries(d.get('camps') or {}):
            if not _camp_has_coords(c):
                continue
            label_prefix = _tier_label(key, idx, total)
            add_marker({
                'lat': c['lat'], 'lon': c['lon'],
                'name': f'Camp ({label_prefix.lower()}): {c["name"]} ({dl})',
                'kind': f'camp_{key}',
            })
            if key == 'primary' and isinstance(c.get('cluster_members'), list):
                for m in c['cluster_members']:
                    if _camp_has_coords(m):
                        add_marker({
                            'lat': m['lat'], 'lon': m['lon'],
                            'name': f'Camp (primary cluster): {m["name"]} ({dl})',
                            'kind': 'camp_primary',
                        })
    return markers


def _fee_tag_html(kind: str, cost: str) -> str:
    """Return a small coloured badge indicating whether the site is free, low-fee, or paid."""
    cost_lc = (cost or '').lower()
    if 'free or low fee' in cost_lc:
        return '<span class="fee-tag fee-tag-lowfee">Free / low fee</span>'
    if cost_lc.startswith('free') or cost_lc == 'free':
        return '<span class="fee-tag fee-tag-free">Free</span>'
    kind_lc = (kind or '').lower()
    if 'primitive' in kind_lc and 'free' in cost_lc:
        return '<span class="fee-tag fee-tag-free">Free</span>'
    return '<span class="fee-tag fee-tag-paid">Fee required</span>'


def camp_block(camps, title='Campsites', day_id=None, allow_focus=False, scheduled=False):
    if not camps:
        return ''
    parts = [f'<h3>{esc(title)}</h3><div class="camp-grid">']
    for key, idx, total, c in _iter_camp_entries(camps):
        reserve = ''
        if c.get('reserve_url'):
            reserve = f' &middot; <a href="{esc(c["reserve_url"])}" target="_blank">Reserve</a>'
        lat, lon = c.get('lat'), c.get('lon')
        gmap = f'https://www.google.com/maps/search/?api=1&query={lat},{lon}' if lat and lon else ''
        gmap_link = f' &middot; <a href="{gmap}" target="_blank">Map It</a>' if gmap else ''
        name_text = esc(c.get("name"))
        if allow_focus and day_id and lat and lon:
            name_html = (
                f'<a href="#" class="focus-map" data-day="{esc(day_id)}" '
                f'data-lat="{lat}" data-lon="{lon}" '
                f'title="Zoom map to this campsite">{name_text}</a>'
            )
        else:
            name_html = name_text
        coords_line = ''
        if lat and lon:
            coords_line = f'<div class="camp-coords">GPS: <code>{lat:.5f}, {lon:.5f}</code></div>'
        eta_line = ''
        camp_data_attrs = ''
        if scheduled and lat and lon:
            eta_line = (
                '<div class="camp-eta">ETA at camp: <strong class="camp-eta-val">--</strong> '
                '<span class="muted">(from last included stop)</span></div>'
            )
            camp_data_attrs = (
                f' data-camp-tier="{key}" data-camp-idx="{idx}" data-day="{esc(day_id) if day_id else ""}"'
                f' data-lat="{lat}" data-lon="{lon}"'
            )
        tier_label = _tier_label(key, idx, total)
        fee_tag = _fee_tag_html(c.get('kind', ''), c.get('cost', ''))
        parts.append(
            f'<div class="camp camp-{key}"{camp_data_attrs}>'
            f'<div class="camp-head"><strong>{esc(tier_label)}</strong>: {name_html}{fee_tag}</div>'
            f'<div class="camp-meta">{esc(c.get("kind", ""))} &middot; {esc(c.get("cost", ""))}{reserve}{gmap_link}</div>'
            f'{coords_line}'
            f'{eta_line}'
            f'<div><strong>Facilities:</strong> {esc(c.get("facilities", ""))}</div>'
            f'<div><strong>Access:</strong> {esc(c.get("access", ""))}</div>'
            f'<div>{esc(c.get("notes", ""))}</div>'
            '</div>'
        )
    parts.append('</div>')
    return ''.join(parts)


def schedule_controls_html(d):
    """Top-of-day scheduler controls. Renders nothing for unscheduled days."""
    sched = d.get('schedule')
    if not sched:
        return ''
    return (
        f'<div class="schedule-controls" data-day="{esc(d["id"])}" '
        f'data-default-break="{esc(sched["break_camp_time"])}" '
        f'data-default-mph="{sched["moving_mph"]}" '
        f'data-start-lat="{sched["start_lat"]}" '
        f'data-start-lon="{sched["start_lon"]}" '
        f'data-mi-lo="{sched["mi_lo"]}">'
        '<div class="sched-row">'
        f'<label>Break camp <input type="time" class="sched-start" '
        f'value="{esc(sched["break_camp_time"])}"></label>'
        f'<label>Driving speed <input type="number" class="sched-mph" '
        f'value="{sched["moving_mph"]}" min="3" max="80" step="1"> mph</label>'
        '<button type="button" class="sched-reset" title="Restore defaults; clears your localStorage edits for this day">Reset day</button>'
        '</div>'
        '<div class="sched-summary">'
        '<span><strong class="sched-count">--</strong> stops included</span>'
        ' &middot; <span>Stop time: <strong class="sched-stop-time">--</strong></span>'
        ' &middot; <span>Drive time: <strong class="sched-drive-time">--</strong></span>'
        ' &middot; <span>Day total: <strong class="sched-day-total">--</strong></span>'
        ' &middot; <span>Arrival at primary camp: <strong class="sched-camp-eta">--</strong></span>'
        '</div>'
        '<div class="sched-hint muted">'
        'Uncheck a stop to remove it. Edit Stop (min) inline. ETAs assume pure driving '
        'at the speed above plus 2&times; off-route distance to detour to each stop. '
        'Camp ETAs add a straight-line drive from the last included stop with a 1.3&times; winding factor. '
        'Your edits are saved in this browser.'
        '</div>'
        '</div>'
    )


# -----------------------------------------------------------------------------
# Shared CSS (inlined in both HTML files for offline)
# -----------------------------------------------------------------------------
CSS = """
:root{
  --bg:#1b1f23; --panel:#24292f; --card:#21262d; --text:#e6edf3; --muted:#8b949e;
  --accent:#ff9d45; --border:#30363d;
  --primary:#238636; --backup:#9e6a03; --skip:#57606a;
  --hike:#a371f7; --conditional:#1f6feb; --logistics:#8b949e; --unclassified:#57606a;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
""" + TOP_NAV_CSS + """
main{max-width:1400px;margin:0 auto;padding:12px}
/* Mobile-only native day picker. Hidden on desktop where the .tabs strip
   shines; promoted on narrow screens so users get a familiar OS picker.
   Wrapper + label make the control discoverable for first-time visitors;
   font-size:16px on the <select> stops iOS Safari from zooming on focus. */
.day-picker-wrap{display:none}
.day-picker-label{display:block;font-size:11px;font-weight:700;letter-spacing:0.06em;
  text-transform:uppercase;color:var(--muted);margin:0 0 6px 2px}
.day-picker{display:none;width:100%;margin:0;padding:12px 40px 12px 14px;
  background:var(--card) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path fill='%23ff9d45' d='M3 5l5 6 5-6z'/></svg>") no-repeat right 12px center / 16px;
  color:var(--text);border:1px solid #484f58;border-radius:8px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 1px 3px rgba(0,0,0,.35),0 0 0 1px rgba(255,157,69,.12);
  font:600 16px/1.2 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-appearance:none;-moz-appearance:none;appearance:none;cursor:pointer}
.day-picker:focus{outline:2px solid var(--accent);outline-offset:2px;border-color:var(--accent)}
.tabs{display:flex;flex-wrap:wrap;gap:2px;border-bottom:1px solid var(--border);
  margin-bottom:16px;background:var(--panel);padding:4px;border-radius:6px;}
.tab-btn{background:transparent;color:var(--muted);border:0;padding:9px 14px;cursor:pointer;
  border-radius:4px;font:inherit;font-size:13px;}
.tab-btn:hover{color:var(--text);background:#30363d}
.tab-btn.active{background:var(--accent);color:#000;font-weight:600}
.tab-pane{display:none}
.tab-pane.active{display:block}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:16px;margin-bottom:16px}
.card h2{margin-top:0;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:6px}
.card h3{color:var(--accent);margin:18px 0 8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}
th{background:#0d1117;color:var(--muted);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:0.5px}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:0.3px;color:#fff}
.badge-primary{background:var(--primary)}
.badge-backup{background:var(--backup)}
.badge-skip{background:var(--skip);opacity:0.5}
.badge-hike{background:var(--hike)}
.fee-tag{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:700;
  letter-spacing:0.4px;text-transform:uppercase;vertical-align:middle;margin-left:6px}
.fee-tag-free{background:#0d3b1f;color:#3fb950;border:1px solid #238636}
.fee-tag-lowfee{background:#0d2b3b;color:#58a6ff;border:1px solid #1f6feb}
.fee-tag-paid{background:#2d1a00;color:#e3a008;border:1px solid #9e6a03}
.badge-conditional{background:var(--conditional)}
.badge-logistics{background:var(--logistics)}
.badge-unclassified{background:var(--unclassified);opacity:0.6}
.camp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.camp{background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:12px;font-size:13px}
.camp-head{margin-bottom:4px}
.camp-primary{border-left:4px solid var(--primary)}
.camp-secondary{border-left:4px solid var(--backup)}
.camp-tertiary{border-left:4px solid var(--skip)}
.camp-meta{color:var(--muted);font-size:12px;margin-bottom:6px}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:12px}
.summary-stat{background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:10px 12px;}
.summary-stat .val{font-size:20px;font-weight:600;color:var(--accent)}
.summary-stat .lab{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0.5px}
.map{height:400px;background:#0d1117;border:1px solid var(--border);border-radius:6px;margin:12px 0}
.map-wrap{position:relative;margin:12px 0}
/* Inner stage: map + chrome buttons. OSRM note lives below the stage (not inside)
   so the chrome's position:absolute bottom:* stays over the map, not the disclaimer. */
.map-stage{position:relative}
.map-wrap .map{margin:0}
/* Bottom-right corner, lifted ~24px to clear Leaflet's attribution strip
   (which lives at bottom:0). Top-right is reserved for the layers control
   and top-left for the zoom buttons, so this is the only free corner. */
.map-chrome{position:absolute;bottom:24px;right:10px;z-index:1100;display:flex;gap:6px;align-items:center;
  pointer-events:none}
.map-chrome button{pointer-events:auto;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
  display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:44px;min-width:44px;
  background:rgba(13,17,23,0.88);color:var(--text);border:1px solid var(--border);border-radius:6px;
  padding:8px 12px;font:600 13px/1 system-ui,sans-serif;cursor:pointer;
  box-shadow:0 2px 6px rgba(0,0,0,0.4)}
.map-chrome button:hover,.map-chrome button:focus-visible{background:rgba(31,111,235,0.85);border-color:#1f6feb;color:#fff}
.map-loc-btn.has-fix{border-color:#2f80ff;color:#79b8ff}
.map-loc-btn.is-locating{opacity:0.75}
.map-loc-btn .loc-icon,.map-fs-btn .fs-icon{font-size:16px;line-height:1}
.map-fs-btn .fs-icon-exit{display:none}
.map-wrap.is-fullscreen .map-fs-btn .fs-icon-enter,.map-wrap.is-fullscreen-fallback .map-fs-btn .fs-icon-enter{display:none}
.map-wrap.is-fullscreen .map-fs-btn .fs-icon-exit,.map-wrap.is-fullscreen-fallback .map-fs-btn .fs-icon-exit{display:inline}
.map-wrap.is-fullscreen .map-fs-btn .fs-label::before,.map-wrap.is-fullscreen-fallback .map-fs-btn .fs-label::before{content:"Exit "}
/* Native :fullscreen pseudo-class makes the wrapper and inner map fill the viewport.
   Flex layout: percentage heights on .map need a definite parent chain; map-stage flex:1
   gives Leaflet a real box (fixes black fullscreen on file:// and many browsers).
   100dvh (with 100% fallback) avoids iOS 100vh including the area behind the Safari chrome. */
.map-wrap:fullscreen,.map-wrap:-webkit-full-screen{width:100%;height:100%;height:100dvh;background:#0d1117;padding:0;border-radius:0;
  display:flex;flex-direction:column}
.map-wrap:fullscreen .map-stage,.map-wrap:-webkit-full-screen .map-stage{flex:1;min-height:0;position:relative;display:flex;flex-direction:column}
.map-wrap:fullscreen .map,.map-wrap:-webkit-full-screen .map{flex:1;min-height:0;width:100%;height:auto!important;border-radius:0;border:0;margin:0}
.map-wrap:fullscreen .map-chrome,.map-wrap:-webkit-full-screen .map-chrome{bottom:28px;right:14px}
/* Fallback "max" mode when the browser denies native fullscreen.
   z-index must beat .trip-chrome (10050) or the nav sits on top of the map on iPad. */
.map-wrap.is-fullscreen-fallback{position:fixed;inset:0;z-index:20000;width:100%;height:100%;height:100dvh;margin:0;background:#0d1117;border-radius:0;
  display:flex;flex-direction:column;
  padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
.map-wrap.is-fullscreen-fallback .map-stage{flex:1;min-height:0;position:relative;display:flex;flex-direction:column}
.map-wrap.is-fullscreen-fallback .map{flex:1;min-height:0;width:100%;height:auto!important;border-radius:0;border:0;margin:0}
html.map-fs-open,body.map-fs-open{overflow:hidden;overscroll-behavior:none}
.map-offline-notice{padding:40px;color:var(--muted);text-align:center;font-style:italic}
.link-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:6px}
.link-grid a{display:block;background:#0d1117;border:1px solid var(--border);border-radius:4px;
  padding:8px 10px;font-size:13px}
.cat-head{color:var(--accent);margin-top:12px;margin-bottom:6px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
.warn{background:#4d1a00;border:1px solid #c7450c;border-radius:6px;padding:10px 12px;margin:10px 0;color:#ffd7a8}
.info{background:#0b2239;border:1px solid #1f6feb;border-radius:6px;padding:10px 12px;margin:10px 0}
.muted{color:var(--muted)}
.day-weather{margin-top:14px;padding-top:14px;border-top:1px solid var(--border);background:rgba(13,17,23,.55);border-radius:6px;padding:12px 14px 14px}
.wx-head{display:grid;grid-template-columns:1fr auto;gap:6px 20px;align-items:baseline;margin-bottom:12px}
.wx-head h3{margin:0;font-size:15px;color:var(--accent)}
.wx-head .day-weather-loc{margin:0;font-size:13px;color:var(--muted);text-align:right;line-height:1.35}
@media (max-width:540px){.wx-head{grid-template-columns:1fr}.wx-head .day-weather-loc{text-align:left}}
.wx-kpi{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:4px 0 14px}
@media (max-width:600px){.wx-kpi{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:320px){.wx-kpi{grid-template-columns:1fr}}
.wx-kpi-item{background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:10px 12px;text-align:center}
.wx-kpi-item .k{display:block;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.wx-kpi-item .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;color:var(--accent);line-height:1.15}
.wx-kpi-item .v .mph{font-size:13px;font-weight:600;color:var(--text)}
.wx-teaser{margin:0 0 12px;font-size:14px;line-height:1.45;color:var(--text)}
.wx-concerns{background:#1f2a3a;border:1px solid #2d4a6e;border-left:4px solid var(--accent);border-radius:8px;padding:10px 12px;margin:12px 0;font-size:13px}
.wx-concerns strong{color:var(--accent)}
.wx-concerns ul{margin:6px 0 0;padding-left:1.2em}
.wx-concerns li{margin:4px 0}
.wx-link-row{font-size:13px;color:var(--muted);margin-top:10px;line-height:1.6}
.wx-link-row a{font-weight:600}
.day-weather details.wx-details{margin-top:8px;font-size:13px}
.day-weather details.wx-details summary{cursor:pointer;color:var(--muted)}
.day-weather .wx-details-inner{margin-top:10px;padding-left:12px;border-left:3px solid var(--accent)}
.day-weather .wx-details-inner p{margin:8px 0}
.day-weather .wx-details-inner ul{margin:8px 0 0;padding-left:18px}
.weather-stamp{margin:10px 0 0;font-size:12px;color:var(--muted)}
.two-col{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}
ul.clean{margin:4px 0;padding-left:20px}
ul.clean li{margin:3px 0}
td.coords{font-size:12px;color:var(--muted);white-space:nowrap}
td.coords code{color:var(--text);font-size:11.5px;background:#0d1117;padding:1px 4px;border-radius:3px}
.camp-coords{font-size:12px;color:var(--muted);margin:4px 0 6px}
.camp-coords code{color:var(--text);background:#1b1f23;padding:1px 4px;border-radius:3px}
a.focus-map{color:var(--text);border-bottom:1px dashed var(--accent);text-decoration:none}
a.focus-map:hover{color:var(--accent);text-decoration:none}
.alerts-banner{padding:10px 14px;margin:10px 0 16px;border-radius:6px;border:1px solid var(--border);font-size:13px}
.alerts-loading{background:#1c2a3a;border-color:#1f6feb;color:var(--muted);font-style:italic}
.alerts-ok{background:#0f2918;border-color:#238636;color:#8be9c0}
.alerts-active{background:#4d1a00;border-color:#c7450c;color:#ffd7a8}
.alerts-offline{background:#202428;border-color:#57606a;color:var(--muted)}
.alerts-banner .alert-list{margin:8px 0 0;padding-left:20px;max-height:320px;overflow-y:auto}
.alerts-banner .alert-list li{margin:6px 0;font-size:12.5px;color:#ffe6c7}
.alerts-banner .alert-desc{color:var(--muted);font-size:12px;margin-top:2px}
.alerts-banner a{color:inherit;text-decoration:underline}
.leaflet-control-attribution{font-size:10px!important}
.schedule-controls{background:#0d1117;border:1px solid var(--border);border-left:4px solid var(--accent);
  border-radius:6px;padding:10px 12px;margin:0 0 14px;font-size:13px}
.schedule-controls .sched-row{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-bottom:8px}
.schedule-controls label{display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:0.4px}
.schedule-controls input[type="time"],.schedule-controls input[type="number"]{
  background:#1b1f23;color:var(--text);border:1px solid var(--border);border-radius:4px;
  padding:4px 6px;font:inherit;font-size:13px;width:84px}
.sched-mph{width:56px!important}
.sched-reset{background:#30363d;color:var(--text);border:1px solid var(--border);border-radius:4px;
  padding:4px 10px;font:inherit;font-size:12px;cursor:pointer}
.sched-reset:hover{background:#3d444c}
.sched-summary{font-size:13px;color:var(--text)}
.sched-summary strong{color:var(--accent)}
.sched-hint{margin-top:6px;font-size:11.5px;line-height:1.4}
/* Default (desktop) checkbox styling. The wrapping <label> is rendered
   inline-flex so the tap area equals the visible checkbox; mobile gets
   a much larger touch target via the @media block below. */
label.poi-include-wrap{display:inline-flex;align-items:center;justify-content:center;cursor:pointer}
input.poi-include{transform:scale(1.15);cursor:pointer;margin:0}
input.poi-duration{width:56px;background:#1b1f23;color:var(--text);border:1px solid var(--border);
  border-radius:4px;padding:2px 4px;font:inherit;font-size:12px;text-align:right}
td.poi-eta strong{color:var(--accent)}
tr.skipped-row td:not(:first-child){opacity:0.45}
tr.skipped-row td.poi-eta{color:var(--muted)}
.spur-hint{font-size:11.5px;color:#ff9d45;margin-top:3px;font-style:italic;line-height:1.3}
tr.skipped-row .spur-hint{color:#8be9c0;font-style:normal}
tr.skipped-row .spur-hint::before{content:"[Saving] "}
.camp-eta{margin:6px 0;font-size:13px;color:var(--text)}
.camp-eta strong{color:var(--accent)}
.desc-btn,.speak-btn{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;
  margin-left:4px;padding:0;border:1px solid var(--border);border-radius:4px;
  background:#1b1f23;color:var(--muted);cursor:pointer;vertical-align:-3px;
  transition:background 0.1s,color 0.1s,border-color 0.1s}
.desc-btn:hover,.speak-btn:hover{background:#1f6feb;border-color:#1f6feb;color:#fff}
.desc-btn:focus-visible,.speak-btn:focus-visible{outline:2px solid #1f6feb;outline-offset:1px}
.desc-btn svg,.speak-btn svg{display:block}
#wca-speak-bar{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);
  background:#21262d;color:#e6edf3;padding:10px 12px;border-radius:8px;
  font:14px/1.4 system-ui,sans-serif;z-index:10000;
  box-shadow:0 4px 14px rgba(0,0,0,.35);max-width:92vw;
  display:flex;align-items:center;gap:12px;border:1px solid var(--border)}
#wca-speak-bar[hidden]{display:none!important}
#wca-speak-bar .speak-bar-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#wca-speak-bar .speak-bar-stop{min-height:44px;min-width:64px;padding:0 14px;
  background:#da3633;border:0;border-radius:6px;color:#fff;
  font:600 14px/1 system-ui,sans-serif;cursor:pointer}
#wca-speak-bar .speak-bar-stop:hover{filter:brightness(1.08)}
.poi-page-link{display:inline;margin-left:6px;font-size:12px;font-weight:600;white-space:nowrap}
#poi-desc-dialog .dialog-body .poi-app-page{margin:0 0 12px;padding:10px 12px;
  background:#161b22;border:1px solid var(--border);border-radius:6px;font-weight:600}
#poi-desc-dialog{max-width:640px;width:90vw;padding:0;background:#24292f;color:var(--text);
  border:1px solid var(--border);border-radius:8px;box-shadow:0 12px 48px rgba(0,0,0,0.75)}
#poi-desc-dialog::backdrop{background:rgba(0,0,0,0.82);backdrop-filter:blur(3px)}
#poi-desc-dialog .dialog-head{display:flex;align-items:flex-start;gap:12px;
  padding:14px 16px;border-bottom:1px solid var(--border);background:#161b22}
#poi-desc-dialog .dialog-head h3{margin:0;font-size:16px;flex:1;color:var(--text);line-height:1.3}
#poi-desc-dialog .dialog-head .dialog-close{flex:none;background:transparent;border:0;color:var(--muted);
  font-size:22px;line-height:1;cursor:pointer;padding:0 4px}
#poi-desc-dialog .dialog-head .dialog-close:hover{color:var(--text)}
#poi-desc-dialog .dialog-sub{color:var(--muted);font-size:12px;margin-top:4px}
#poi-desc-dialog .dialog-sub code{font-size:11.5px}
#poi-desc-dialog .dialog-body{padding:14px 16px;max-height:60vh;overflow-y:auto;line-height:1.55;font-size:14px}
#poi-desc-dialog .dialog-body p{margin:0 0 10px}
#poi-desc-dialog .dialog-body p:last-child{margin-bottom:0}
#poi-desc-dialog .dialog-body .src{margin-top:14px;padding-top:10px;border-top:1px dashed var(--border);
  color:var(--muted);font-size:11.5px;font-style:italic}
.leaflet-div-icon.marker-icon{background:transparent!important;border:0!important}
.map-legend{background:rgba(13,17,23,0.88);border:1px solid var(--border);border-radius:6px;
  padding:6px 9px;color:var(--text);font-size:12px;line-height:1.4;backdrop-filter:blur(4px)}
.map-legend .legend-row{display:flex;align-items:center;gap:8px;margin:2px 0}
.map-legend .legend-swatch{display:inline-flex;align-items:center;justify-content:center;width:18px}
.map-legend .legend-dot{display:inline-block;width:12px;height:12px;border-radius:50%;
  box-shadow:0 1px 2px rgba(0,0,0,0.6)}
.map-legend .legend-line{display:inline-block;width:16px;height:3px;border-radius:2px}
.map-legend svg{display:block}

/* ----------------------------------------------------------------
 * Mobile / narrow-screen layout (phones up to ~iPhone Pro Max).
 * Key change: POI "stops" tables collapse into stacked cards since
 * 7-10 columns will not fit on a 375-430px wide screen. Each <td>
 * exposes its column name via the data-label attribute, which we
 * surface with a ::before pseudo-element. No JS changes required.
 * ---------------------------------------------------------------- */
@media (max-width:720px){
  /* Page chrome: tighter trip chrome + main padding */
  main{padding:8px}
  .card{padding:12px}
  .card h2{font-size:17px}
  .card h3{font-size:14px;margin-top:14px}

  /* Day navigation on phones: swap the easy-to-miss horizontal scroll
     strip for a native <select>. The picker shows the current day in
     full and opens the OS-native list of all days on tap. Scroll-strip
     CSS is kept (overflow-x:auto + edge mask) for the rare case the
     select is unavailable, but it's hidden by default at this width. */
  .tabs{display:none}
  .day-picker-wrap{display:block;margin:4px 0 14px}
  .day-picker{display:block}

  /* POI tables: table -> stacked cards. We hide the <thead>, convert each
     <tr> into a card, and each <td> becomes a "Label: value" row using
     the data-label attribute. .td-name is promoted to a card title and
     .td-include / .td-duration float to the top-right as controls. */
  table.stops-table,
  table.stops-table tbody,
  table.stops-table tr,
  table.stops-table td{display:block;width:100%}
  table.stops-table{font-size:14px;border-collapse:separate}
  table.stops-table thead{display:none}
  table.stops-table tr{background:#0d1117;border:1px solid var(--border);
    border-radius:8px;padding:10px 12px;margin-bottom:10px;position:relative}
  table.stops-table td{padding:3px 0;border:0;text-align:left;white-space:normal}
  table.stops-table td.num{text-align:left}
  table.stops-table td::before{content:attr(data-label) ": ";color:var(--muted);
    font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.4px;
    margin-right:6px;display:inline-block}
  /* Prominent card title (Name). No label prefix. */
  table.stops-table td.td-name{font-size:16px;font-weight:600;line-height:1.35;
    margin:0 0 6px;padding-right:52px /* reserve space for .td-include float */ }
  table.stops-table td.td-name::before{display:none}
  table.stops-table td.td-name .focus-map{color:var(--text)}
  /* Checkbox floats to top-right corner of the card for easy thumb reach.
     The cell carries explicit 44x44 dimensions (Apple HIG / Material
     touch-target minimum) and the input lives inside a <label> that fills
     the cell, so tapping anywhere in the corner toggles the checkbox.
     z-index keeps it above any sibling that gets opacity:0.45 (which on
     iOS Safari can promote a new stacking context that occludes
     absolutely-positioned siblings). No transform-scale here -- iOS
     Safari can mis-size the tap hit-box vs. the visual when transform
     is combined with width:auto + position:absolute. Explicit width on
     the input keeps the hit-box honest. */
  table.stops-table td.td-include{position:absolute;top:0;right:0;
    width:44px;height:44px;padding:0;margin:0;z-index:2}
  table.stops-table td.td-include::before{display:none}
  table.stops-table td.td-include label.poi-include-wrap{
    width:100%;height:100%;display:inline-flex;align-items:center;justify-content:center}
  table.stops-table td.td-include input.poi-include{transform:none;width:22px;height:22px;margin:0}
  /* Duration input stays inline with its label, but a touch bigger. */
  table.stops-table td.td-duration input{width:72px;font-size:14px;padding:4px 6px}
  /* Empty cells (no value) -> hide entirely on mobile to reduce noise. */
  table.stops-table td:empty{display:none}
  /* Coord cell wraps naturally on mobile. */
  table.stops-table td.coords{white-space:normal}
  table.stops-table td.coords code{white-space:nowrap}
  /* Spur hint sits under the name title, no extra indent. */
  table.stops-table td.td-name .spur-hint{margin-top:4px}

  /* Other tables (fuel stations, quick-ref) stay tabular
     but get a little denser. */
  table:not(.stops-table){font-size:12px}
  table:not(.stops-table) th,
  table:not(.stops-table) td{padding:5px 6px}

  /* Grids: let cards flow one-per-row at narrower widths. */
  .camp-grid{grid-template-columns:1fr}
  .summary-grid{grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}
  .summary-stat{padding:8px 10px}
  .summary-stat .val{font-size:17px}

  /* Schedule controls: tighter gap, wrap label+input pairs together. */
  .schedule-controls{padding:8px 10px}
  .schedule-controls .sched-row{gap:10px;margin-bottom:6px}
  .schedule-controls label{font-size:11px}

  /* Map a touch shorter so more route-context fits above the fold. */
  .map{height:300px}
}

@media print{
  .tabs,.tab-btn,.day-picker-wrap,.day-picker{display:none}
  .tab-pane{display:block!important;page-break-before:always}
  .tab-pane:first-child{page-break-before:auto}
  body{background:#fff;color:#000}
  .card{background:#fff;border-color:#ccc;page-break-inside:avoid}
}
"""


# -----------------------------------------------------------------------------
# Day-Tabbed ITINERARY HTML
# -----------------------------------------------------------------------------
def build_itinerary_html(variant=None):
    """Render the tabbed itinerary page for the given variant.

    `variant` is a dict (see VARIANT_* at top of module) controlling page
    title, header strings, GPX download filename, nav highlight, and the
    route-overview tab header. Defaults to VARIANT_MAIN."""
    variant = variant or VARIANT_MAIN
    days = data['days']
    wkey = variant.get('weather_key') or 'main'
    weather_boot_json = json.dumps(
        {'variantKey': wkey, 'days': merge_weather_days(wkey, days)},
        ensure_ascii=False,
    )
    # Every line that interpolates JS_PREFIX must be an f-string. A plain string
    # here silently ships the literal "{cfg.JS_PREFIX}" into the page, which is a
    # syntax error that kills the whole block and leaves the per-day forecasts
    # stuck on "Loading forecasts...".
    boot_global = f'window.__{cfg.JS_PREFIX}_WEATHER_BOOT__'
    weather_scripts = (
        f'<script>{boot_global}={weather_boot_json};</script>\n'
        '<script src="weather-client.js"></script>\n'
        '<script>'
        f'if(window.TripWeather&&{boot_global})'
        f"TripWeather.init(Object.assign({{mode:'itinerary'}},{boot_global}));"
        '</script>'
    )

    # ----- Full-route overview (first tab): stitched GPX + aggregated pins -----
    ov_markers = _collect_route_overview_markers(days)
    ov_stop_rows = []
    for d in days:
        if d.get('type') not in ('travel', 'overland'):
            continue
        for p in d.get('pois') or []:
            if p.get('status') == 'skip':
                continue
            ov_stop_rows.append((float(p.get('mile') or 0), d, p))
    ov_stop_rows.sort(key=lambda x: (x[0], x[1]['id'], x[2]['name']))
    ov_rows_html = []
    allow_ov_focus = bool(overview_track or ov_markers)
    for mile, d, p in ov_stop_rows:
        lat, lon = p.get('lat'), p.get('lon')
        name_text = esc(p['name'])
        if allow_ov_focus and lat is not None and lon is not None:
            name_html = (
                f'<a href="#" class="focus-map" data-day="{esc(ROUTE_OVERVIEW_ID)}" '
                f'data-lat="{lat}" data-lon="{lon}" '
                f'title="Zoom map to this stop">{name_text}</a>'
            )
        else:
            name_html = name_text
        name_html += desc_button_html(p['name'], p.get('desc'))
        name_html += speak_button_html(p['name'], p.get('desc'), p.get('note'))
        name_html += poi_page_link_html(p['name'])
        if lat is not None and lon is not None:
            gm = f'https://www.google.com/maps/search/?api=1&query={lat},{lon}'
            coords_html = (
                f'<code>{lat:.5f}, {lon:.5f}</code> &middot; '
                f'<a href="{gm}" target="_blank" rel="noopener">Map It</a>'
            )
        else:
            coords_html = ''
        ov_rows_html.append(
            '<tr>'
            f'<td class="num" data-label="Mi">{mile:.1f}</td>'
            f'<td data-label="Day">{esc(d["label"])}</td>'
            f'<td class="td-name" data-label="Name">{name_html}</td>'
            f'<td data-label="Status">{badge_html(p["status"])}</td>'
            f'<td data-label="Type">{esc(p.get("sym") or "")}</td>'
            f'<td data-label="Note">{esc(p.get("note") or "")}</td>'
            f'<td class="num" data-label="Off-track" title="distance from main route track">{p.get("dist_to_track_m", 0):.0f} m</td>'
            f'<td class="coords" data-label="Coords">{coords_html}</td>'
            '</tr>'
        )
    ov_table_body = ''.join(ov_rows_html)
    n_trk_seg = sum(1 for x in days if len(x.get('track_points') or []) > 0)
    ov_stat_html = ''.join((
        f'<div class="summary-stat"><div class="val">{n_trk_seg}</div><div class="lab">GPX track segments</div></div>',
        f'<div class="summary-stat"><div class="val">{len(ov_stop_rows)}</div><div class="lab">POI rows (skips out)</div></div>',
        f'<div class="summary-stat"><div class="val">{len(ov_markers)}</div><div class="lab">Map pins (POIs + camps)</div></div>',
    ))
    ov_has_map = bool(overview_track) or bool(ov_markers)
    ov_map_id = f'map-{ROUTE_OVERVIEW_ID}'
    if ov_has_map:
        ov_wrap_id = f'map-wrap-{ROUTE_OVERVIEW_ID}'
        ov_map_html = (
            f'<div class="map-wrap" id="{ov_wrap_id}">'
            f'<div class="map-stage">'
            f'{_map_chrome_html(ov_wrap_id)}'
            f'<div id="{ov_map_id}" class="map" data-day-id="{ROUTE_OVERVIEW_ID}"><div class="map-offline-notice">'
            'Loading map... (requires internet for tiles; falls back to coordinates list if offline)'
            '</div></div></div></div>'
        )
    else:
        ov_map_html = '<div class="info">No map data for full-route view.</div>'

    ov_intro_html = data.get('intro_html') or ''
    ov_pane = (
        f'<div class="tab-pane active" id="pane-{ROUTE_OVERVIEW_ID}">'
        '<div class="card">'
        f'<h2>{esc(variant["overview_title"])}</h2>'
        f'<div class="muted">{variant["overview_desc_html"]}</div>'
        f'{ov_intro_html}'
        f'<div class="summary-grid">{ov_stat_html}</div>'
        f'{ov_map_html}'
        '<h3>All stops (route mile order)</h3>'
        f'<table class="stops-table">{OVERVIEW_STOPS_HEADER}<tbody>{ov_table_body}</tbody></table>'
        '</div></div>'
    )

    # Tab buttons (desktop scroll strip) + native <option> list (mobile picker).
    # Both are emitted; CSS at <=700px hides .tabs and shows .day-picker. The
    # JS keeps both in sync so a user resizing across the breakpoint never
    # sees a stale "active" indicator.
    tabs = [
        f'<button class="tab-btn active" data-tgt="pane-{ROUTE_OVERVIEW_ID}">Full route</button>',
    ]
    options = [
        f'<option value="{ROUTE_OVERVIEW_ID}" selected>Full route</option>',
    ]
    panes = [ov_pane]

    for d in days:
        tabs.append(
            f'<button class="tab-btn" data-tgt="pane-{d["id"]}">{esc(d["label"])}</button>'
        )
        options.append(
            f'<option value="{d["id"]}">{esc(d["label"])}</option>'
        )

        # POIs split by status for visibility
        pois = d.get('pois') or []
        primary = [p for p in pois if p['status'] in ('primary', 'hike_candidate', 'conditional')]
        backup = [p for p in pois if p['status'] == 'backup']
        skipped = [p for p in pois if p['status'] == 'skip']
        logistics = [p for p in pois if p['status'] == 'logistics']

        summary_stats = []
        if d.get('miles') is not None:
            summary_stats.append(('Miles', f'{d["miles"]}'))
        if d.get('driving_hours_est') is not None:
            summary_stats.append(('Drive hrs (est)', f'{d["driving_hours_est"]}'))
        summary_stats.append(('POI stops', f'{len(primary)} primary, {len(backup)} backup'))
        stat_html = ''.join(
            f'<div class="summary-stat"><div class="val">{esc(v)}</div><div class="lab">{esc(l)}</div></div>'
            for l, v in summary_stats
        )

        # A day qualifies for an embedded map if it has either a drivable
        # track OR at least one mappable marker (POI / camp). This lets
        # travel-staging days (e.g. Day 0) show their bonus stops and camp
        # options on the map even without a recorded track.
        def _has_coords(x):
            return isinstance(x, dict) and x.get('lat') and x.get('lon')

        day_has_map = (
            bool(d.get('_map_points'))
            or any(_has_coords(p) for p in pois)
            # Each tier may hold a dict OR a list of dicts; walk via the shared helper.
            or any(_camp_has_coords(c) for _, _, _, c in _iter_camp_entries(d.get('camps') or {}))
        )
        is_scheduled = bool(d.get('schedule'))

        # POI tables.
        # On scheduled days we merge primary + backup + hike_candidate into one
        # mile-sorted table with checkboxes and ETAs. On unscheduled days
        # (the two highway travel days) we keep the original split tables.
        poi_tables = []
        if is_scheduled:
            merged = sorted(
                [p for p in pois if p['status'] in ('primary', 'hike_candidate', 'conditional', 'backup')],
                key=lambda p: p['mile'],
            )
            if merged:
                poi_tables.append('<h3>Stops (primary + bonus, in route order)</h3>')
                poi_tables.append(f'<table class="stops-table">{POI_HEADER_SCHEDULED}<tbody>')
                day_mph = int((d.get('schedule') or {}).get('moving_mph') or 20)
                for i, p in enumerate(merged):
                    poi_tables.append(poi_row(p, day_id=d['id'], allow_focus=day_has_map,
                                              scheduled=True, idx=i, day_mph=day_mph))
                poi_tables.append('</tbody></table>')
        else:
            if primary:
                poi_tables.append('<h3>Primary Stops</h3>')
                poi_tables.append(f'<table class="stops-table">{POI_HEADER}<tbody>')
                poi_tables.extend(poi_row(p, day_id=d['id'], allow_focus=day_has_map) for p in primary)
                poi_tables.append('</tbody></table>')
            if backup:
                poi_tables.append('<h3>Backup / Bonus Stops</h3>')
                poi_tables.append(f'<table class="stops-table">{POI_HEADER}<tbody>')
                poi_tables.extend(poi_row(p, day_id=d['id'], allow_focus=day_has_map) for p in backup)
                poi_tables.append('</tbody></table>')

        # Lookouts and lava tubes start checked. Other hike_candidates stay opt-in.
        hike_warn = ''
        hike_pois = [p for p in pois if p.get('status') == 'hike_candidate']
        if hike_pois:
            planned = [p['name'] for p in hike_pois if p.get('default_checked')]
            opt_in = [p['name'] for p in hike_pois if not p.get('default_checked')]
            bits = []
            if planned:
                listed = ', '.join(f'<strong>{esc(n)}</strong>' for n in planned)
                bits.append(
                    f'<strong>On the plan:</strong> {listed}. Uncheck to skip '
                    'and watch the ETA move.'
                )
            if opt_in:
                listed = ', '.join(f'<strong>{esc(n)}</strong>' for n in opt_in)
                bits.append(
                    f'<strong>Optional:</strong> {listed}. These start '
                    '<strong>unchecked</strong> so the day\'s arrival estimate '
                    'reflects driving only. Tick the ones you want and watch the ETA move.'
                )
            gear = ''
            if any('Lava Cave' in p['name'] for p in pois):
                gear = (
                    ' <br><strong>Lava caves:</strong> every person going underground needs their own '
                    'headlamp plus a backup light and spare batteries. The cave is pitch dark and stays '
                    'cold year round; the floor is uneven basalt. Boots and gloves recommended. '
                    'No permit and no paid entry — see the <a href="lava-caves.html">lava caves page</a> '
                    'for gear, white-nose decon, and how to find the pits.'
                )
            hike_warn = (
                f'<div class="warn">{" ".join(bits)}{gear}</div>'
            )

        # Camps block
        camps = d.get('camps')
        camps_html = (
            camp_block(camps, day_id=d['id'], allow_focus=day_has_map, scheduled=is_scheduled)
            if camps else ''
        )

        # Schedule controls bar (only on scheduled days)
        sched_html = schedule_controls_html(d)

        # Map container (highway days include OSRM polylines from planning/highway_tracks.json).
        map_id = f'map-{d["id"]}'
        has_map = day_has_map
        hw_note = ''
        if has_map and d.get('type') in ('travel', 'transit') and len(d.get('track_points') or []) > 30:
            hw_note = (
                '<p class="muted" style="margin:10px 2px 0;font-size:12px;line-height:1.45">'
                '<strong>Orange line:</strong> approximate paved corridor from '
                '<strong>OpenStreetMap</strong> (OSRM routing), decimated for offline pages '
                '&mdash; same <em>general</em> path as Google/Apple Maps but not copied from them. '
                'Navigate with Google Maps (or similar) in real time for lanes, traffic, and closures.'
                '</p>'
            )
        day_wrap_id = f'map-wrap-{d["id"]}'
        map_html = (
            f'<div class="map-wrap" id="{day_wrap_id}">'
            f'<div class="map-stage">'
            f'{_map_chrome_html(day_wrap_id)}'
            f'<div id="{map_id}" class="map" data-day-id="{d["id"]}"><div class="map-offline-notice">'
            'Loading map... (requires internet for tiles; falls back to coordinates list if offline)'
            f'</div></div></div>{hw_note}</div>'
            if has_map else
            '<div class="info">No mapped track segment for this day.</div>'
        )

        # Quick links for this day. Travel days get the highway corridor; route
        # days get the forest, fire and pass links that actually matter out there.
        is_outbound_travel = d.get('date_iso') == '2026-09-08'
        is_return_travel = d.get('date_iso') == '2026-09-13'
        quick_links = []
        if is_outbound_travel:
            quick_links = [
                {'label': 'Idaho 511',                'url': 'https://511.idaho.gov/'},
                {'label': 'ODOT TripCheck (I-84)',    'url': 'https://www.tripcheck.com/'},
                {'label': 'WSDOT real-time',          'url': 'https://wsdot.com/travel/real-time/'},
                {'label': 'Carson weather',           'url': 'https://forecast.weather.gov/MapClick.php?lat=45.7411&lon=-121.8214'},
                {'label': 'GPNF alerts',              'url': 'https://www.fs.usda.gov/r06/giffordpinchot/alerts'},
            ]
        elif is_return_travel:
            quick_links = [
                {'label': 'WSDOT real-time',          'url': 'https://wsdot.com/travel/real-time/'},
                {'label': 'ODOT TripCheck (I-84)',    'url': 'https://www.tripcheck.com/'},
                {'label': 'Idaho 511',                'url': 'https://511.idaho.gov/'},
                {'label': 'Nampa weather',            'url': 'https://forecast.weather.gov/MapClick.php?lat=43.6013&lon=-116.5645'},
            ]
        elif d['type'] == 'overland':
            quick_links = [
                {'label': 'GPNF alerts & closures',   'url': 'https://www.fs.usda.gov/r06/giffordpinchot/alerts'},
                {'label': 'GPNF road conditions',     'url': 'https://www.fs.usda.gov/r06/giffordpinchot/conditions'},
                {'label': 'InciWeb active fires',     'url': 'https://inciweb.wildfire.gov/'},
                {'label': 'AirNow fire & smoke',      'url': 'https://fire.airnow.gov/'},
                {'label': 'WSDOT mountain passes',    'url': 'https://wsdot.com/travel/real-time/mountainpasses'},
                {'label': 'Fire & closures page',     'url': 'fire-and-closures.html'},
            ]
            if d['id'] == 'day4_cascades':
                quick_links.append(
                    {'label': 'Falls Creek lava caves', 'url': 'lava-caves.html'},
                )

        ql_html = ''
        if quick_links:
            ql_html = (
                '<h3>Real-time quick links</h3>'
                '<div class="link-grid">'
                + ''.join(f'<a href="{esc(l["url"])}" target="_blank">{esc(l["label"])}</a>' for l in quick_links)
                + '</div>'
            )

        pane = (
            f'<div class="tab-pane" id="pane-{d["id"]}">'
            f'<div class="card">'
            f'<h2>{esc(d["title"])}</h2>'
            f'<div class="muted">{esc(d.get("descr", ""))}</div>'
            f'<div class="summary-grid">{stat_html}</div>'
            f'{weather_day_section_html(d["id"])}'
            f'{hike_warn}'
            f'{sched_html}'
            f'{map_html}'
            f'{"".join(poi_tables)}'
            f'{camps_html}'
            f'{ql_html}'
            '</div>'
            '</div>'
        )
        panes.append(pane)

    # Build per-day map data payload (tracks + POI markers + origin/destination camps).
    # We walk days in order so each day's map can include the PRIOR day's primary camp
    # as an "origin" marker (cyan diamond) for orientation.
    map_payload = {}
    prev_primary_camp = None
    for d in data['days']:
        pts = d.get('_map_points') or []
        pois = d.get('pois') or []
        camps = d.get('camps') or {}
        markers = []

        # Origin: previous day's primary camp, if any and this day has a map
        if pts and prev_primary_camp:
            markers.append({
                'lat': prev_primary_camp['lat'],
                'lon': prev_primary_camp['lon'],
                'name': f'Origin (prev night): {prev_primary_camp["name"]}',
                'kind': 'camp_origin',
            })

        # POI marker selection depends on whether there's a driven track.
        #  - Track days: only primary + hike_candidate go on the map (backups
        #    clutter an already busy scheduled-day view).
        #  - Track-less days (e.g. Day 0 travel + stage): ALL coord-bearing
        #    POIs are shown, because there are fewer of them and the "backup"
        #    bonus stops are the entire point of the map.
        if pts:
            show_statuses = {'primary', 'hike_candidate'}
        else:
            show_statuses = {'primary', 'hike_candidate', 'backup', 'conditional'}
        for p in pois:
            if p['status'] in show_statuses and p.get('lat') and p.get('lon'):
                markers.append({
                    'lat': p['lat'], 'lon': p['lon'], 'name': p['name'],
                    'kind': p.get('map_kind') or 'poi',
                })
        # Scheduled days with a driven track: bonus/backup rows use the same mile-sorted
        # merge as the stops table; expose them on the map only when the row checkbox
        # is checked (see sched_poi_id + syncBackupMarkersForDay in inline JS).
        if pts and d.get('schedule'):
            merged_map = sorted(
                [p for p in pois if p['status'] in (
                    'primary', 'hike_candidate', 'conditional', 'backup',
                )],
                key=lambda p: p['mile'],
            )
            for idx, p in enumerate(merged_map):
                if p['status'] != 'backup' or not p.get('lat') or not p.get('lon'):
                    continue
                markers.append({
                    'lat': p['lat'], 'lon': p['lon'], 'name': p['name'], 'kind': 'poi',
                    'sched_poi_id': f'{d["id"]}-{idx}',
                })

        # End-of-day camps (primary / backup / last-resort).
        # Tiers can hold either a single dict OR a list of equal-rank sites
        # (e.g. the Wedge has 3 secondary designated sites). Walk via helper.
        for key, idx, total, c in _iter_camp_entries(camps):
            if not _camp_has_coords(c):
                continue
            label_prefix = _tier_label(key, idx, total)
            markers.append({
                'lat': c['lat'], 'lon': c['lon'],
                'name': f'Camp ({label_prefix.lower()}): {c["name"]}',
                'kind': f'camp_{key}',
            })
            # Primary tiers may define `cluster_members`: additional designated
            # sites in the same cluster that we want pinned on the map as
            # primary-tier options (without generating extra cards).
            if key == 'primary' and isinstance(c.get('cluster_members'), list):
                for m in c['cluster_members']:
                    if _camp_has_coords(m):
                        markers.append({
                            'lat': m['lat'], 'lon': m['lon'],
                            'name': f'Camp (primary cluster): {m["name"]}',
                            'kind': 'camp_primary',
                        })

        map_payload[d['id']] = {'track': pts, 'markers': markers}
        if d.get('_map_extra_points'):
            map_payload[d['id']]['extra_track'] = d['_map_extra_points']

        # Update rolling "previous primary camp" for the next day's origin marker.
        # When primary is a list (multiple equal-rank sites), anchor on the first
        # entry -- it's treated as the "nominal" landing spot.
        if isinstance(camps, dict):
            prim_val = camps.get('primary')
            prim = prim_val[0] if isinstance(prim_val, list) and prim_val else prim_val
            if _camp_has_coords(prim):
                prev_primary_camp = {
                    'lat': prim['lat'], 'lon': prim['lon'], 'name': prim['name'],
                }

    map_payload[ROUTE_OVERVIEW_ID] = {
        'track': overview_track,
        'markers': ov_markers,
    }

    map_json = json.dumps(map_payload)
    # Calendar day -> tab id for "open today's leg" on load (browser local date).
    # If several legs share one date_iso, the first in itinerary order wins.
    day_tab_dates = [
        {'id': d['id'], 'date': d['date_iso']}
        for d in days
        if d.get('date_iso')
    ]
    day_tab_dates_json = json.dumps(day_tab_dates, ensure_ascii=False)

    # POI description dialog: map every POI name with a <desc> to its description + meta
    poi_desc_map = collect_poi_descriptions(data)
    poi_desc_json = json.dumps(poi_desc_map, ensure_ascii=False)
    poi_desc_dialog_js = POI_DESC_DIALOG_JS.format(desc_json=poi_desc_json)

    # Offline tiles: base64 data URIs keyed by "z/x/y" (empty dict if never
    # downloaded). See scripts/download_offline_tiles.py.
    offline_tiles_json = json.dumps(OFFLINE_TILES)

    brand_html = (
        f'<h1>{esc(variant["header_h1"])}</h1><div class="meta">{variant["header_meta"]}</div>'
    )
    nav_block = _top_nav_html(
        variant['nav_key'],
        brand_html=brand_html,
        weather_href=f'weather.html?variant={esc(wkey)}',
        itinerary_href=variant['html_path'].name,
        gpx_href=variant['gpx_filename'],
    )
    html_out = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{esc(variant['page_title'])}</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{PWA_HEAD}
<style>{LEAFLET_CSS}</style>
<style>{CSS}</style>
<!-- Inline Leaflet 1.9.4 so the map engine is available before any inline
     script that references `L` (e.g. `L.TileLayer.extend(...)`). -->
<script>{LEAFLET_JS}</script>
</head><body>
{nav_block}
<main>
<div class="day-picker-wrap">
<label class="day-picker-label" id="day-picker-label" for="day-picker">Choose a day</label>
<select class="day-picker" id="day-picker" aria-labelledby="day-picker-label">{''.join(options)}</select>
</div>
<div class="tabs" role="tablist">{''.join(tabs)}</div>
{''.join(panes)}
<section class="card" style="margin-top:24px">
<h2>{cfg.NWS_ALERT_LABEL}</h2>
<div class="muted" style="margin-bottom:8px">Fetched live when online; ignore if viewing offline. Use <strong>Menu → Weather</strong> or the per-day weather blocks when connectivity is available.</div>
<div id="live-alerts" class="alerts-banner alerts-loading">Checking {cfg.NWS_ALERT_LABEL}...</div>
</section>
{POI_DESC_DIALOG_HTML}
</main>
<script>
const TAB_BTNS = document.querySelectorAll('.tab-btn');
const PANES = document.querySelectorAll('.tab-pane');
const DAY_PICKER = document.getElementById('day-picker');
function activateTab(dayId) {{
  const btn = document.querySelector('.tab-btn[data-tgt="pane-' + dayId + '"]');
  const pane = document.getElementById('pane-' + dayId);
  if (!btn || !pane) return false;
  TAB_BTNS.forEach(x => x.classList.remove('active'));
  PANES.forEach(x => x.classList.remove('active'));
  btn.classList.add('active');
  pane.classList.add('active');
  // Mirror the active day into the mobile picker so a window resize across
  // the desktop/mobile breakpoint never leaves the two controls disagreeing.
  if (DAY_PICKER && DAY_PICKER.value !== dayId) DAY_PICKER.value = dayId;
  return true;
}}
TAB_BTNS.forEach(b => b.addEventListener('click', () => {{
  const dayId = b.dataset.tgt.replace('pane-','');
  activateTab(dayId);
  setTimeout(() => ensureMap(dayId), 30);
}}));
if (DAY_PICKER) {{
  DAY_PICKER.addEventListener('change', () => {{
    const dayId = DAY_PICKER.value;
    activateTab(dayId);
    setTimeout(() => ensureMap(dayId), 30);
    // Scroll the page back to the top of the day so the user lands at the
    // start of the new day's content rather than wherever they were in the
    // previous day's pane.
    window.scrollTo({{top: 0, behavior: 'smooth'}});
  }});
}}

const MAP_DATA = {map_json};
const MAPS = {{}};
// dayId -> {{ schedPoiId: Leaflet layer }} for backup stops toggled by row checkboxes.
const BACKUP_MARKER_REGISTRY = {{}};
// Optional GPS dot per map (never used for initial fitBounds).
let __{cfg.JS_PREFIX}_LAST_GPS = null;
const __{cfg.JS_PREFIX}_MY_LOC_BY_DAY = {{}};
let __{cfg.JS_PREFIX}_GPS_WATCH_ID = null;

function esriLayer(name) {{
  // Online Esri tile sources; we mark failed tiles transparent so the
  // underlying offline layer can show through when there's no connectivity.
  return L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/' + name + '/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{
      attribution: 'Tiles &copy; Esri',
      maxZoom: 19,
      errorTileUrl: TRANSPARENT_PNG,
      crossOrigin: true,
    }}
  );
}}

// ----- Offline low-res tile layer -----
// OFFLINE_TILES is a dict of {{ "z/x/y" : "data:image/png;base64,..." }} built at
// HTML-generation time from planning/offline_tiles/. It covers the full trip
// bbox at zoom {min(cfg.TILE_ZOOMS)}-{max(cfg.TILE_ZOOMS)} so the map still has a recognizable background when
// viewed offline. Zooming past {max(cfg.TILE_ZOOMS)} auto-stretches the deepest cached tiles via
// maxNativeZoom, which must stay equal to the deepest zoom actually cached --
// set any lower and the deeper tiles are downloaded but never requested.
const OFFLINE_TILES = {offline_tiles_json};
const TRANSPARENT_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const OfflineTileLayer = L.TileLayer.extend({{
  getTileUrl: function(coords) {{
    const key = coords.z + '/' + coords.x + '/' + coords.y;
    return OFFLINE_TILES[key] || TRANSPARENT_PNG;
  }}
}});

function ensureMap(dayId) {{
  if (typeof L === 'undefined') return;
  const spec = MAP_DATA[dayId]; if (!spec) return;
  const hasTrack = spec.track && spec.track.length > 0;
  const hasMarkers = spec.markers && spec.markers.length > 0;
  // Allow track-less days (e.g. Day 0) to show a map framed around their
  // POI / camp markers. Only bail if BOTH are empty.
  if (!hasTrack && !hasMarkers) return;
  const elId = 'map-' + dayId; const el = document.getElementById(elId);
  if (!el || MAPS[dayId]) return;
  el.innerHTML = '';
  const m = L.map(elId);
  // Offline low-res tiles live in their own pane below the online tile pane
  // so Esri always renders on top when online, and shows through when Esri
  // tiles fail (errorTileUrl keeps failed tiles transparent). The offline
  // layer stays on at all times -- it's the background fallback.
  m.createPane('offlinePane');
  m.getPane('offlinePane').style.zIndex = 150;
  const offline = new OfflineTileLayer('', {{
    pane: 'offlinePane', minZoom: 0, maxZoom: 19, maxNativeZoom: {max(cfg.TILE_ZOOMS)},
    attribution: 'Offline baseline: &copy; OpenStreetMap contributors (cached)',
  }}).addTo(m);
  const topo = esriLayer('World_Topo_Map');
  const imagery = esriLayer('World_Imagery');
  const streets = esriLayer('World_Street_Map');
  topo.addTo(m);
  L.control.layers(
    {{'Topo (online)': topo, 'Satellite (online)': imagery, 'Street (online)': streets}},
    {{'Offline baseline (always on)': offline}},
    {{collapsed: true, position: 'topright'}}
  ).addTo(m);
  // Build an extensible bounds object so we can frame track + markers together.
  const bounds = L.latLngBounds([]);
  if (hasTrack) {{
    const line = L.polyline(spec.track, {{color:'#ff9d45', weight:3}}).addTo(m);
    bounds.extend(line.getBounds());
  }}
  // Highway leg on days that also drive to or from the route: dimmer and
  // dashed so it never reads as part of the trail route.
  if (spec.extra_track && spec.extra_track.length) {{
    const hw = L.polyline(spec.extra_track, {{color:'#58a6ff', weight:2, opacity:0.65, dashArray:'6,6'}}).addTo(m);
    bounds.extend(hw.getBounds());
  }}
  if (!BACKUP_MARKER_REGISTRY[dayId]) BACKUP_MARKER_REGISTRY[dayId] = {{}};
  spec.markers.forEach(mk => {{
    const mkr = buildMarker(mk);
    if (!mkr) return;
    mkr.bindPopup(mk.name);
    const sid = mk.sched_poi_id;
    if (sid) {{
      BACKUP_MARKER_REGISTRY[dayId][sid] = mkr;
      const pane = document.getElementById('pane-' + dayId);
      const tr = pane && pane.querySelector('tr[data-poi-id="' + sid + '"]');
      const on = tr && tr.querySelector('.poi-include') && tr.querySelector('.poi-include').checked;
      if (on) {{
        mkr.addTo(m);
        bounds.extend([mk.lat, mk.lon]);
      }}
    }} else {{
      mkr.addTo(m);
      bounds.extend([mk.lat, mk.lon]);
    }}
  }});
  syncBackupMarkersForDay(dayId);
  if (bounds.isValid()) {{
    m.fitBounds(bounds, {{padding:[30,30], maxZoom: 14}});
  }} else {{
    m.setView([{cfg.MAP_FALLBACK_CENTER[0]}, {cfg.MAP_FALLBACK_CENTER[1]}], {cfg.MAP_FALLBACK_ZOOM});  // trip-area fallback
  }}
  addLegend(m);
  MAPS[dayId] = m;
  syncMyLocationForDay(dayId);
}}

function syncMyLocationForDay(dayId) {{
  const map = MAPS[dayId];
  if (!map || __{cfg.JS_PREFIX}_LAST_GPS == null) return;
  const lat = __{cfg.JS_PREFIX}_LAST_GPS.lat;
  const lon = __{cfg.JS_PREFIX}_LAST_GPS.lon;
  let layer = __{cfg.JS_PREFIX}_MY_LOC_BY_DAY[dayId];
  if (!layer) {{
    layer = L.circleMarker([lat, lon], {{
      radius: 10,
      color: '#ffffff',
      weight: 3,
      fillColor: '#2f80ff',
      fillOpacity: 0.95,
      interactive: true,
      pane: 'markerPane',
      className: 'wca-my-location',
    }}).addTo(map);
    layer.bindPopup('Your location (GPS, approximate)');
    __{cfg.JS_PREFIX}_MY_LOC_BY_DAY[dayId] = layer;
  }} else {{
    layer.setLatLng([lat, lon]);
  }}
  try {{ layer.bringToFront(); }} catch (e) {{}}
}}

function syncMyLocationAllMaps() {{
  Object.keys(MAPS).forEach((id) => syncMyLocationForDay(id));
}}

function _setGpsUi(state, detail) {{
  document.querySelectorAll('.map-loc-btn').forEach(btn => {{
    btn.classList.toggle('is-locating', state === 'locating');
    btn.classList.toggle('has-fix', state === 'fix');
    btn.dataset.gpsState = state;
    const title = detail || 'Show my GPS location on this map';
    btn.title = title;
    btn.setAttribute('aria-label', title);
    const label = btn.querySelector('.loc-label');
    if (!label) return;
    label.textContent = ({{
      idle: 'My location',
      locating: 'Locating…',
      fix: 'My location',
      denied: 'Location blocked',
      unavailable: 'No GPS',
      insecure: 'Needs HTTPS',
    }})[state] || 'My location';
  }});
}}

function _gpsApplyFix(pos, flyDayId) {{
  const lat = pos && pos.coords && pos.coords.latitude;
  const lon = pos && pos.coords && pos.coords.longitude;
  if (lat == null || lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return;
  __{cfg.JS_PREFIX}_LAST_GPS = {{ lat, lon }};
  _setGpsUi('fix', 'GPS fix — tap to recenter this map on you');
  syncMyLocationAllMaps();
  if (flyDayId && MAPS[flyDayId]) {{
    const m = MAPS[flyDayId];
    const z = Math.max(m.getZoom() || 0, 12);
    m.flyTo([lat, lon], z, {{duration: 0.6}});
  }}
  if (typeof _speakOnGps === 'function') _speakOnGps(lat, lon);
}}

function _gpsErrorMessage(err) {{
  const code = err && err.code;
  if (code === 1) return 'Location permission denied. On iPad: Settings → Safari → Location, or Settings → Privacy → Location Services.';
  if (code === 2) return 'Location unavailable (Wi‑Fi iPads need a network fix; there is no GPS chip).';
  if (code === 3) return 'Location timed out. Try My location again, or move to open sky / Wi‑Fi.';
  return (err && err.message) ? String(err.message) : 'Location failed.';
}}

function _gpsOnError(err, allowLowAccuracyRetry) {{
  if (err && err.code === 3 && allowLowAccuracyRetry) {{
    startMyLocationWatch({{enableHighAccuracy: false, retry: false}});
    return;
  }}
  const state = (err && err.code === 1) ? 'denied' : 'unavailable';
  _setGpsUi(state, _gpsErrorMessage(err));
}}

function _gpsClearWatch() {{
  if (__{cfg.JS_PREFIX}_GPS_WATCH_ID != null && navigator.geolocation) {{
    try {{ navigator.geolocation.clearWatch(__{cfg.JS_PREFIX}_GPS_WATCH_ID); }} catch (e) {{}}
  }}
  __{cfg.JS_PREFIX}_GPS_WATCH_ID = null;
}}

function startMyLocationWatch(opts) {{
  opts = opts || {{}};
  if (!navigator.geolocation) {{
    _setGpsUi('unavailable', 'This browser has no geolocation API.');
    return;
  }}
  if (!window.isSecureContext) {{
    _setGpsUi('insecure', 'Location requires HTTPS or localhost (file:// will not work on iPad).');
    return;
  }}
  const high = opts.enableHighAccuracy !== false;
  const retry = opts.retry !== false;
  _setGpsUi('locating', 'Waiting for GPS…');
  _gpsClearWatch();
  try {{
    __{cfg.JS_PREFIX}_GPS_WATCH_ID = navigator.geolocation.watchPosition(
      (pos) => _gpsApplyFix(pos, null),
      (err) => _gpsOnError(err, retry && high),
      {{
        enableHighAccuracy: high,
        maximumAge: high ? 10000 : 60000,
        timeout: high ? 10000 : 20000,
      }}
    );
  }} catch (e) {{
    _setGpsUi('unavailable', String((e && e.message) || e));
  }}
}}

function requestMyLocation(dayId) {{
  if (!navigator.geolocation) {{
    _setGpsUi('unavailable', 'This browser has no geolocation API.');
    return;
  }}
  if (!window.isSecureContext) {{
    _setGpsUi('insecure', 'Location requires HTTPS or localhost (file:// will not work on iPad).');
    return;
  }}
  _setGpsUi('locating', 'Waiting for GPS…');
  const onFix = (pos) => {{
    _gpsApplyFix(pos, dayId);
    startMyLocationWatch({{enableHighAccuracy: true, retry: true}});
  }};
  const lowAccuracyOpts = {{enableHighAccuracy: false, maximumAge: 60000, timeout: 20000}};
  try {{
    navigator.geolocation.getCurrentPosition(
      onFix,
      (err) => {{
        if (err && err.code === 3) {{
          navigator.geolocation.getCurrentPosition(
            onFix,
            (err2) => _gpsOnError(err2, false),
            lowAccuracyOpts
          );
          return;
        }}
        _gpsOnError(err, false);
      }},
      {{enableHighAccuracy: true, maximumAge: 10000, timeout: 8000}}
    );
  }} catch (e) {{
    _setGpsUi('unavailable', String((e && e.message) || e));
  }}
}}

function syncBackupMarkersForDay(dayId) {{
  const reg = BACKUP_MARKER_REGISTRY[dayId];
  const m = MAPS[dayId];
  if (!reg || !m) return;
  const pane = document.getElementById('pane-' + dayId);
  if (!pane) return;
  Object.keys(reg).forEach(sid => {{
    const layer = reg[sid];
    const tr = pane.querySelector('tr[data-poi-id="' + sid + '"]');
    const on = tr && tr.querySelector('.poi-include') && tr.querySelector('.poi-include').checked;
    if (on) {{ if (!m.hasLayer(layer)) layer.addTo(m); }}
    else {{ if (m.hasLayer(layer)) m.removeLayer(layer); }}
  }});
}}

// ----- Custom marker shapes -----
// POIs = green filled circles. Camps = color-coded triangles (tent-shaped).
// Origin (previous night's camp) = cyan diamond so it stands out from end-of-day camps.
function _svgTriangle(color, size) {{
  const s = size;
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="' + s +
    '" height="' + s + '" style="display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.6))">' +
    '<polygon points="10,2 18,17 2,17" fill="' + color +
    '" stroke="#0d1117" stroke-width="2" stroke-linejoin="round"/></svg>';
}}
function _svgDiamond(color, size) {{
  const s = size;
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="' + s +
    '" height="' + s + '" style="display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.6))">' +
    '<polygon points="10,1 19,10 10,19 1,10" fill="' + color +
    '" stroke="#0d1117" stroke-width="2" stroke-linejoin="round"/></svg>';
}}
const MARKER_STYLE = {{
  poi:             {{kind: 'circle',  color: '#238636', radius: 6, label: 'Stop'}},
  trailhead:       {{kind: 'circle',  color: '#f0883e', radius: 8, label: 'Trailhead'}},
  trail_poi:       {{kind: 'circle',  color: '#1f6feb', radius: 6, label: 'Trail landmark'}},
  camp_primary:    {{kind: 'tri',     color: '#a371f7', size: 20,  label: 'Camp (primary)'}},
  camp_secondary:  {{kind: 'tri',     color: '#e3a008', size: 18,  label: 'Camp (backup)'}},
  camp_tertiary:   {{kind: 'tri',     color: '#8b949e', size: 16,  label: 'Camp (last-resort)'}},
  camp_origin:     {{kind: 'diamond', color: '#56d4f5', size: 22,  label: 'Origin (prior night\\'s camp)'}},
}};
function buildMarker(mk) {{
  const st = MARKER_STYLE[mk.kind] || MARKER_STYLE.poi;
  if (st.kind === 'circle') {{
    return L.circleMarker([mk.lat, mk.lon], {{
      radius: st.radius, color: st.color, weight: 2,
      fillColor: st.color, fillOpacity: 0.8
    }});
  }}
  const svg = (st.kind === 'diamond' ? _svgDiamond : _svgTriangle)(st.color, st.size);
  const icon = L.divIcon({{
    html: svg,
    className: 'marker-icon marker-' + mk.kind,
    iconSize: [st.size, st.size],
    iconAnchor: [st.size / 2, st.size / 2],
    popupAnchor: [0, -st.size / 2],
  }});
  return L.marker([mk.lat, mk.lon], {{icon: icon}});
}}

// ----- Map legend -----
function addLegend(m) {{
  const legend = L.control({{position: 'bottomleft'}});
  legend.onAdd = function() {{
    const div = L.DomUtil.create('div', 'map-legend');
    const row = (swatch, text) =>
      '<div class="legend-row"><span class="legend-swatch">' + swatch + '</span>' +
      '<span>' + text + '</span></div>';
    div.innerHTML =
      row('<span class="legend-dot" style="background:#238636"></span>', 'Primary stop / hike') +
      row('<span class="legend-dot" style="background:#f0883e;width:11px;height:11px;border-radius:2px;display:inline-block"></span>', 'Trailhead') +
      row('<span class="legend-dot" style="background:#1f6feb"></span>', 'Trail landmark') +
      row(_svgTriangle('#a371f7', 14), 'Camp (primary)') +
      row(_svgTriangle('#e3a008', 14), 'Camp (backup)') +
      row(_svgTriangle('#8b949e', 14), 'Camp (last-resort)') +
      row(_svgDiamond('#56d4f5', 14), "Origin (prior night's camp)") +
      '<div class="legend-row"><span class="legend-swatch">' +
        '<span class="legend-line" style="background:#ff9d45"></span>' +
      '</span><span>Route track</span></div>' +
      row(
        '<span class="legend-dot" style="background:#2f80ff;border:2px solid #fff;box-sizing:border-box"></span>',
        'You (GPS, if browser allows)'
      );
    L.DomEvent.disableClickPropagation(div);
    return div;
  }};
  legend.addTo(m);
}}

function focusMap(dayId, lat, lon) {{
  activateTab(dayId);
  ensureMap(dayId);
  const m = MAPS[dayId];
  if (m) {{
    m.flyTo([lat, lon], 15, {{duration: 0.6}});
    const mapEl = document.getElementById('map-' + dayId);
    if (mapEl) mapEl.scrollIntoView({{behavior: 'smooth', block: 'center'}});
  }} else {{
    window.open('https://www.google.com/maps/search/?api=1&query=' + lat + ',' + lon, '_blank');
  }}
}}
document.addEventListener('click', function(e) {{
  const a = e.target.closest('a.focus-map');
  if (!a) return;
  e.preventDefault();
  focusMap(a.dataset.day, parseFloat(a.dataset.lat), parseFloat(a.dataset.lon));
}});

// ----- Map fullscreen toggle -----
// iPad Safari: requestFullscreen/webkitRequestFullscreen exist for HTMLElement
// but only actually work for <video>. Checking the method is not enough —
// document.fullscreenEnabled is false, the webkit call returns undefined and
// does nothing, and a thrown/rejected request never reached the CSS fallback
// because the old handler only toggled fallback inside promise.catch().
function _fsRequest(el) {{
  if (el.requestFullscreen) return el.requestFullscreen();
  if (el.webkitRequestFullscreen) return el.webkitRequestFullscreen();
  if (el.msRequestFullscreen) return el.msRequestFullscreen();
}}
function _fsExit() {{
  if (document.exitFullscreen) return document.exitFullscreen();
  if (document.webkitExitFullscreen) return document.webkitExitFullscreen();
  if (document.msExitFullscreen) return document.msExitFullscreen();
}}
function _fsElement() {{
  return document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement || null;
}}
function _fsNativeEnabled() {{
  if (typeof document.fullscreenEnabled === 'boolean') return document.fullscreenEnabled;
  if (typeof document.webkitFullscreenEnabled === 'boolean') return document.webkitFullscreenEnabled;
  if (typeof document.msFullscreenEnabled === 'boolean') return document.msFullscreenEnabled;
  return false;
}}
function _invalidateAllMapSizes() {{
  requestAnimationFrame(() => {{
    Object.keys(MAPS).forEach(k => {{
      const m = MAPS[k];
      if (m) m.invalidateSize({{animate: false}});
    }});
    requestAnimationFrame(() => {{
      Object.keys(MAPS).forEach(k => {{
        const m = MAPS[k];
        if (m) m.invalidateSize({{animate: false}});
      }});
    }});
  }});
}}
function _fsLockScroll(on) {{
  document.documentElement.classList.toggle('map-fs-open', on);
  document.body.classList.toggle('map-fs-open', on);
}}
function _fsFallbackOn(wrap) {{
  document.querySelectorAll('.map-wrap.is-fullscreen-fallback').forEach(w => {{
    if (w !== wrap) w.classList.remove('is-fullscreen-fallback');
  }});
  wrap.classList.add('is-fullscreen-fallback');
  _fsLockScroll(true);
  setTimeout(_invalidateAllMapSizes, 0);
  setTimeout(_invalidateAllMapSizes, 200);
}}
function _fsFallbackOff(wrap) {{
  wrap.classList.remove('is-fullscreen-fallback');
  if (!document.querySelector('.map-wrap.is-fullscreen-fallback')) _fsLockScroll(false);
  setTimeout(_invalidateAllMapSizes, 0);
  setTimeout(_invalidateAllMapSizes, 200);
}}
function _toggleMapFullscreen(wrap) {{
  if (wrap.classList.contains('is-fullscreen-fallback')) {{
    _fsFallbackOff(wrap);
    return;
  }}
  if (_fsElement() === wrap) {{
    try {{ _fsExit(); }} catch (e) {{ _fsFallbackOff(wrap); }}
    return;
  }}
  if (!_fsNativeEnabled()) {{
    _fsFallbackOn(wrap);
    return;
  }}
  try {{
    const p = _fsRequest(wrap);
    if (p && typeof p.then === 'function') {{
      p.then(() => {{
        setTimeout(_invalidateAllMapSizes, 0);
        setTimeout(_invalidateAllMapSizes, 200);
      }}).catch(() => _fsFallbackOn(wrap));
    }} else {{
      requestAnimationFrame(() => {{
        if (_fsElement() !== wrap) _fsFallbackOn(wrap);
        else {{
          setTimeout(_invalidateAllMapSizes, 0);
          setTimeout(_invalidateAllMapSizes, 200);
        }}
      }});
    }}
  }} catch (e) {{
    _fsFallbackOn(wrap);
  }}
}}
document.addEventListener('click', function(e) {{
  const locBtn = e.target.closest('.map-loc-btn');
  if (locBtn) {{
    e.preventDefault();
    const wrap = document.getElementById(locBtn.dataset.target);
    if (!wrap) return;
    const mapEl = wrap.querySelector('.map');
    const dayId = mapEl && mapEl.dataset.dayId;
    if (dayId) ensureMap(dayId);
    requestMyLocation(dayId);
    return;
  }}
  const btn = e.target.closest('.map-fs-btn');
  if (!btn) return;
  e.preventDefault();
  const wrap = document.getElementById(btn.dataset.target);
  if (!wrap) return;
  const mapEl = wrap.querySelector('.map');
  const dayId = mapEl && mapEl.dataset.dayId;
  if (dayId) ensureMap(dayId);
  _toggleMapFullscreen(wrap);
}});
document.addEventListener('keydown', function(e) {{
  if (e.key !== 'Escape') return;
  const open = document.querySelector('.map-wrap.is-fullscreen-fallback');
  if (!open) return;
  e.preventDefault();
  _fsFallbackOff(open);
}});
function _fsChange() {{
  const fsEl = _fsElement();
  document.querySelectorAll('.map-wrap').forEach(w => w.classList.remove('is-fullscreen'));
  if (fsEl && fsEl.classList && fsEl.classList.contains('map-wrap')) {{
    fsEl.classList.add('is-fullscreen');
    _fsLockScroll(true);
  }} else if (!document.querySelector('.map-wrap.is-fullscreen-fallback')) {{
    _fsLockScroll(false);
  }}
  setTimeout(_invalidateAllMapSizes, 0);
  setTimeout(_invalidateAllMapSizes, 150);
}}
document.addEventListener('fullscreenchange', _fsChange);
document.addEventListener('webkitfullscreenchange', _fsChange);
document.addEventListener('msfullscreenchange', _fsChange);
if (window.visualViewport) {{
  window.visualViewport.addEventListener('resize', _invalidateAllMapSizes);
}}
window.addEventListener('orientationchange', () => setTimeout(_invalidateAllMapSizes, 300));

// ----- Live NWS alerts for {cfg.NWS_ALERT_AREA} (CORS-enabled public API) -----
function escHTML(s){{return String(s==null?'':s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
async function loadAlerts() {{
  const el = document.getElementById('live-alerts');
  if (!el) return;
  try {{
    const r = await fetch('https://api.weather.gov/alerts/active?area={cfg.NWS_ALERT_AREA}', {{
      headers: {{'Accept': 'application/geo+json'}}
    }});
    if (!r.ok) throw new Error('NWS HTTP ' + r.status);
    const j = await r.json();
    const feats = j.features || [];
    const now = new Date().toLocaleString();
    if (!feats.length) {{
      el.classList.remove('alerts-loading');
      el.classList.add('alerts-ok');
      el.innerHTML = '<strong>No active NWS alerts for {cfg.NWS_ALERT_AREA}.</strong> <span class="muted">Checked ' + escHTML(now) + '. <a href="https://www.weather.gov/alerts" target="_blank" rel="noopener">Full alert feed</a></span>';
      return;
    }}
    const rank = e => /Flash Flood Warning/i.test(e)?0:/Flood Warning/i.test(e)?1:/Severe Thunderstorm Warning/i.test(e)?2:/Warning/i.test(e)?3:/Red Flag/i.test(e)?4:/Watch/i.test(e)?5:/Advisory/i.test(e)?6:7;
    feats.sort((a,b)=>rank(a.properties.event||'')-rank(b.properties.event||''));
    const rows = feats.map(f => {{
      const p = f.properties || {{}};
      const sev = p.severity || '';
      const exp = p.expires ? new Date(p.expires).toLocaleString() : '';
      return '<li><strong>' + escHTML(p.event) + '</strong> &middot; <span class="muted">' + escHTML(sev) + '</span> &middot; ' + escHTML(p.areaDesc || '') + (exp ? ' &middot; <em>expires ' + escHTML(exp) + '</em>' : '') + (p.headline ? '<div class="alert-desc">' + escHTML(p.headline) + '</div>' : '') + '</li>';
    }}).join('');
    el.classList.remove('alerts-loading');
    el.classList.add('alerts-active');
    el.innerHTML = '<strong>' + feats.length + ' active NWS {cfg.NWS_ALERT_AREA} alert' + (feats.length===1?'':'s') + '.</strong> <span class="muted">Fetched ' + escHTML(now) + '. <a href="#" id="alerts-toggle">show/hide</a> &middot; <a href="https://www.weather.gov/alerts" target="_blank" rel="noopener">full feed</a></span><ul class="alert-list" id="alerts-list">' + rows + '</ul>';
    const tog = document.getElementById('alerts-toggle');
    if (tog) tog.addEventListener('click', function(e){{e.preventDefault();const ul=document.getElementById('alerts-list');if(ul)ul.style.display=ul.style.display==='none'?'':'none';}});
  }} catch (err) {{
    el.classList.remove('alerts-loading');
    el.classList.add('alerts-offline');
    el.innerHTML = '<strong>Live alert check unavailable</strong> <span class="muted">(' + escHTML(err.message) + '). Use the real-time links below when online.</span>';
  }}
}}
loadAlerts();

// ----- Per-day scheduler (checkbox + ETA + duration; localStorage-persisted) -----
function _hav_mi(lat1, lon1, lat2, lon2) {{
  const R = 3958.7613;
  const tr = x => x * Math.PI / 180;
  const dLa = tr(lat2 - lat1), dLo = tr(lon2 - lon1);
  const a = Math.sin(dLa/2)**2 + Math.cos(tr(lat1))*Math.cos(tr(lat2))*Math.sin(dLo/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}}
function _fmtTime(min) {{
  if (!isFinite(min)) return '--';
  const total = Math.round(min);
  const h = Math.floor(total / 60) % 24;
  const m = ((total % 60) + 60) % 60;
  const am = h < 12 ? 'AM' : 'PM';
  const h12 = ((h + 11) % 12) + 1;
  return h12 + ':' + String(m).padStart(2, '0') + ' ' + am;
}}
function _fmtDur(min) {{
  if (!isFinite(min) || min < 0) return '--';
  const total = Math.round(min);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm';
}}
function _parseHHMM(s) {{
  const m = (s || '').match(/^(\\d{{1,2}}):(\\d{{2}})$/);
  if (!m) return 9 * 60;
  return (parseInt(m[1], 10) || 0) * 60 + (parseInt(m[2], 10) || 0);
}}
function _schedKey(dayId) {{ return 'sched-v1-' + dayId; }}
function _loadSched(dayId) {{
  try {{ return JSON.parse(localStorage.getItem(_schedKey(dayId)) || 'null'); }}
  catch (e) {{ return null; }}
}}
function _saveSched(dayId, state) {{
  try {{ localStorage.setItem(_schedKey(dayId), JSON.stringify(state)); }} catch (e) {{}}
}}

function recomputeSchedule(dayId) {{
  const ctrl = document.querySelector('.schedule-controls[data-day="' + dayId + '"]');
  if (!ctrl) return;
  const pane = document.getElementById('pane-' + dayId);
  if (!pane) return;
  const startInput = ctrl.querySelector('.sched-start');
  const mphInput = ctrl.querySelector('.sched-mph');
  const startMin = _parseHHMM(startInput.value);
  const mph = Math.max(3, parseFloat(mphInput.value) || 1);
  const startLat = parseFloat(ctrl.dataset.startLat);
  const startLon = parseFloat(ctrl.dataset.startLon);
  const miLo = parseFloat(ctrl.dataset.miLo) || 0;

  const rows = pane.querySelectorAll('tr[data-poi-id]');
  let prevMile = miLo;
  let prevLat = startLat, prevLon = startLon;
  let cur = startMin;
  let driveTotal = 0, stopTotal = 0, includedCount = 0;
  // Miles we avoid driving because an upstream spur POI was un-checked.
  // Accumulated on skipped-spur rows, consumed by the next included leg (and
  // by the final camp leg if no later stops were included).
  let pendingSpurSaveMi = 0;
  rows.forEach(tr => {{
    const include = tr.querySelector('.poi-include').checked;
    const etaCell = tr.querySelector('.poi-eta');
    const durInput = tr.querySelector('.poi-duration');
    const mile = parseFloat(tr.dataset.mile);
    const lat = parseFloat(tr.dataset.lat);
    const lon = parseFloat(tr.dataset.lon);
    const offMi = (parseFloat(tr.dataset.offtrack) || 0) * 2 / 1609.344;
    const spurMi = parseFloat(tr.dataset.spurMi) || 0;
    if (!include) {{
      // If this was an on-spur stop, credit its round-trip miles toward the
      // next included leg. Dwell time is already excluded by skipping the row.
      pendingSpurSaveMi += spurMi;
      etaCell.innerHTML = '<span class="muted">skipped</span>';
      tr.classList.add('skipped-row');
      return;
    }}
    tr.classList.remove('skipped-row');
    const rawLegMi = Math.max(0, mile - prevMile) + offMi;
    const legMi = Math.max(0, rawLegMi - pendingSpurSaveMi);
    pendingSpurSaveMi = 0;   // consumed
    const legMin = legMi / mph * 60;
    cur += legMin;
    driveTotal += legMin;
    etaCell.innerHTML = '<strong>' + _fmtTime(cur) + '</strong>';
    const dur = Math.max(0, parseFloat(durInput.value) || 0);
    cur += dur;
    stopTotal += dur;
    includedCount += 1;
    prevMile = mile;
    prevLat = lat;
    prevLon = lon;
  }});

  // Camp ETAs. The straight-line estimate from the last included stop to camp
  // already ignores any skipped-spur detour (we're not on the spur anymore),
  // so we do not apply pendingSpurSaveMi here. It's only meaningful between
  // two track-mile anchored stops. For the same reason we don't carry it into
  // the next day's computation.
  let primaryCampEta = null;
  pane.querySelectorAll('.camp[data-camp-tier]').forEach(camp => {{
    if (camp.dataset.day !== dayId) return;
    const cLat = parseFloat(camp.dataset.lat);
    const cLon = parseFloat(camp.dataset.lon);
    if (!isFinite(cLat) || !isFinite(cLon)) return;
    const distMi = _hav_mi(prevLat, prevLon, cLat, cLon) * 1.3;
    const legMin = distMi / mph * 60;
    const eta = cur + legMin;
    const span = camp.querySelector('.camp-eta-val');
    if (span) span.textContent = _fmtTime(eta);
    if (camp.dataset.campTier === 'primary') primaryCampEta = eta;
  }});

  ctrl.querySelector('.sched-count').textContent = String(includedCount);
  ctrl.querySelector('.sched-stop-time').textContent = _fmtDur(stopTotal);
  ctrl.querySelector('.sched-drive-time').textContent = _fmtDur(driveTotal);
  ctrl.querySelector('.sched-day-total').textContent = _fmtDur(stopTotal + driveTotal);
  ctrl.querySelector('.sched-camp-eta').textContent =
    primaryCampEta != null ? _fmtTime(primaryCampEta) : '--';

  const state = {{ start: startInput.value, mph: mphInput.value, stops: {{}} }};
  rows.forEach(tr => {{
    state.stops[tr.dataset.poiId] = {{
      checked: tr.querySelector('.poi-include').checked,
      duration: parseFloat(tr.querySelector('.poi-duration').value) || 0,
    }};
  }});
  _saveSched(dayId, state);
  syncBackupMarkersForDay(dayId);
}}

function attachSchedule(ctrl) {{
  const dayId = ctrl.dataset.day;
  const pane = document.getElementById('pane-' + dayId);
  if (!pane) return;
  const state = _loadSched(dayId);
  if (state) {{
    if (state.start) ctrl.querySelector('.sched-start').value = state.start;
    if (state.mph) ctrl.querySelector('.sched-mph').value = state.mph;
    pane.querySelectorAll('tr[data-poi-id]').forEach(tr => {{
      const s = state.stops && state.stops[tr.dataset.poiId];
      if (!s) return;
      tr.querySelector('.poi-include').checked = !!s.checked;
      if (s.duration != null) tr.querySelector('.poi-duration').value = s.duration;
    }});
  }}
  const rerun = () => recomputeSchedule(dayId);
  ctrl.querySelector('.sched-start').addEventListener('input', rerun);
  ctrl.querySelector('.sched-mph').addEventListener('input', rerun);
  pane.querySelectorAll('tr[data-poi-id] .poi-include, tr[data-poi-id] .poi-duration')
    .forEach(el => {{ el.addEventListener('input', rerun); el.addEventListener('change', rerun); }});
  ctrl.querySelector('.sched-reset').addEventListener('click', () => {{
    try {{ localStorage.removeItem(_schedKey(dayId)); }} catch (e) {{}}
    ctrl.querySelector('.sched-start').value = ctrl.dataset.defaultBreak;
    ctrl.querySelector('.sched-mph').value = ctrl.dataset.defaultMph;
    pane.querySelectorAll('tr[data-poi-id]').forEach(tr => {{
      tr.querySelector('.poi-include').checked = tr.dataset.defaultChecked === 'true';
      tr.querySelector('.poi-duration').value = tr.dataset.defaultDuration;
    }});
    rerun();
  }});
  rerun();
}}
document.querySelectorAll('.schedule-controls').forEach(attachSchedule);

{poi_desc_dialog_js}

</script>
{SPEAK_SETTINGS_JS}
{_speak_engine_js(data)}
<script>

// Leaflet is inlined in <head>. If the viewer's local calendar date matches a
// trip leg's date_iso, open that day tab (first match when two legs share a date);
// otherwise keep the default "Full route" tab and load its map.
(function(){{
  const DAY_TAB_DATES = {day_tab_dates_json};
  if (typeof L === 'undefined') {{
    document.querySelectorAll('.map-offline-notice').forEach(el => {{
      el.textContent = 'Map engine failed to load. Refer to GPX or printed maps. Textual content is fully usable.';
    }});
    return;
  }}
  const y = new Date();
  const today = y.getFullYear() + '-' + String(y.getMonth() + 1).padStart(2, '0') + '-' + String(y.getDate()).padStart(2, '0');
  let picked = null;
  for (let i = 0; i < DAY_TAB_DATES.length; i++) {{
    if (DAY_TAB_DATES[i].date === today) {{ picked = DAY_TAB_DATES[i].id; break; }}
  }}
  if (picked && activateTab(picked)) {{
    setTimeout(() => ensureMap(picked), 30);
  }} else {{
    ensureMap('{ROUTE_OVERVIEW_ID}');
  }}
}})();
setTimeout(function() {{ startMyLocationWatch(); }}, 800);
if (window.WcaSpeakSettings && WcaSpeakSettings.read().enabled) {{
  _speakUnlock();
  _speakRequestWake();
}}
</script>
{weather_scripts}
{PWA_REGISTER_JS}
</body></html>
"""
    return html_out


def _daylight_table_html() -> str:
    """Sunrise/sunset per trip day, from trip_config.DAYLIGHT."""
    rows = ''
    for row in cfg.DAYLIGHT:
        day = ''
        for d in data['days']:
            if d.get('date_iso') == row['date_iso']:
                day = (d.get('label') or '').split(' - ')[0]
                break
        rows += (f'<tr><td>{esc(row["date_iso"])}</td><td>{esc(day)}</td>'
                 f'<td class="num">{esc(row["sunrise"])}</td>'
                 f'<td class="num">{esc(row["sunset"])}</td>'
                 f'<td class="num">{esc(row["hours"])}</td></tr>')
    return (
        '<h3>Daylight</h3>'
        '<table><thead><tr><th>Date</th><th>Day</th><th>Sunrise</th><th>Sunset</th>'
        '<th>Daylight</th></tr></thead><tbody>' + rows + '</tbody></table>'
        '<p class="muted">Pacific Daylight Time at the route mid-latitude. '
        'Regenerate with <code>scripts/daylight_table.py</code>.</p>'
    )


# -----------------------------------------------------------------------------
# Full REFERENCE HTML (everything in one linear document)
# -----------------------------------------------------------------------------
def build_reference_html():
    # Real-time links grouped by category
    rt_by_cat = {}
    for l in data['realtime_links']:
        rt_by_cat.setdefault(l['cat'], []).append(l)
    rt_html = ''
    for cat, links in rt_by_cat.items():
        rt_html += f'<div class="cat-head">{esc(cat)}</div><div class="link-grid">'
        for l in links:
            href = l['url']
            # Stay inside the installed PWA for relative trip pages.
            blank = ' target="_blank"' if href.startswith('http') else ''
            rt_html += f'<a href="{esc(href)}"{blank}>{esc(l["label"])}</a>'
        rt_html += '</div>'

    # Fuel section
    fp = data['fuel']
    sb = fp['surface_breakdown']
    stations_html = '<table><thead><tr><th>Station</th><th>Role</th><th>Brands</th></tr></thead><tbody>'
    for s in fp['stations']:
        stations_html += f'<tr><td>{esc(s["name"])}</td><td>{esc(s["role"])}</td><td>{esc(s["brands"])}</td></tr>'
    stations_html += '</tbody></table>'

    gaps_html = '<table><thead><tr><th>Gap</th><th>Miles</th><th>What it means</th></tr></thead><tbody>'
    for g in fp.get('critical_gaps', []):
        gaps_html += (
            f'<tr><td><strong>{esc(g["label"])}</strong><div class="muted" style="font-size:12px">'
            f'mile {g["from_mi"]} &rarr; {g["to_mi"]}</div></td>'
            f'<td class="num"><strong>{g["gap_mi"]}</strong></td>'
            f'<td>{esc(g["note"])}</td></tr>'
        )
    gaps_html += '</tbody></table>'

    _notes_lis = ''.join(f'<li>{esc(n)}</li>' for n in fp.get('notes', []))
    surface_html = f"""
<table>
<thead><tr><th>Surface</th><th>Miles</th><th>MPG factor</th></tr></thead>
<tbody>
<tr><td>Paved highway</td><td class="num">{sb["paved_hwy_mi"]}</td><td class="num">{fp["mpg_factors"]["paved_hwy_65mph"]:.2f}</td></tr>
<tr><td>Graded gravel</td><td class="num">{sb["graded_gravel_mi"]}</td><td class="num">{fp["mpg_factors"]["graded_gravel"]:.2f}</td></tr>
<tr><td>Rough 2-track / narrow spur</td><td class="num">{sb["rough_2track_mi"]}</td><td class="num">{fp["mpg_factors"]["rough_2track"]:.2f}</td></tr>
<tr><td>Technical low-range</td><td class="num">{sb["technical_mi"]}</td><td class="num">{fp["mpg_factors"]["technical_low_range"]:.2f}</td></tr>
<tr><td><strong>Total route</strong></td><td class="num"><strong>{sb["total_mi"]}</strong></td><td></td></tr>
</tbody>
</table>
<h3>Fuel gaps that matter</h3>
{gaps_html}
<ul class="clean">{_notes_lis}</ul>
"""

    # Day-by-day full dump (no tabs here)
    day_sections = []
    for d in data['days']:
        pois = d.get('pois') or []
        # Full POI table incl. skips for reference
        poi_html = ''
        if pois:
            poi_html = (
                f'<table class="stops-table">{POI_HEADER}<tbody>'
                + ''.join(poi_row(p) for p in pois)
                + '</tbody></table>'
            )

        camps_html = camp_block(d.get('camps'), 'Camping options (primary / secondary / tertiary)') if d.get('camps') else ''

        day_sections.append(
            f'<div class="card" id="{d["id"]}">'
            f'<h2>{esc(d["label"])}</h2>'
            f'<p>{esc(d.get("title", ""))} &mdash; {esc(d.get("descr", ""))}</p>'
            f'<p class="muted">Miles: {d.get("miles") or "--"} &middot; Driving (est): {d.get("driving_hours_est") or "--"} hrs</p>'
            f'{poi_html}'
            f'{camps_html}'
            '</div>'
        )

    # Hikes and activities, collected from the day data rather than hardcoded.
    hike_rows = []
    for d in data['days']:
        for pp in (d.get('pois') or []):
            if pp.get('status') != 'hike_candidate':
                continue
            mins = pp.get('default_minutes')
            spur = pp.get('spur_mi') or 0
            extra = []
            if mins:
                extra.append(f'~{int(mins)} min budgeted')
            if spur:
                extra.append(f'~{spur:g} mi round-trip spur off route')
            off = pp.get('true_off_track_m') or 0
            if off > 400:
                extra.append(f'{off / 1609.344:.1f} mi from the main track')
            page = POI_APP_PAGES.get(pp['name'])
            if page:
                name_cell = (
                    f'<a href="{esc(page["href"])}">{esc(pp["name"])}</a>'
                )
            else:
                name_cell = '<strong>' + esc(pp['name']) + '</strong>'
            hike_rows.append(
                '<tr><td>' + name_cell + '</td>'
                '<td>' + esc(d['label'].split(' - ')[0]) + '</td>'
                '<td>' + esc(', '.join(extra) or '\u2014') + '</td>'
                '<td>' + esc(pp.get('note') or '') + '</td></tr>'
            )
    hike_detail = ''
    if hike_rows:
        hike_detail = (
            '<div class="card" id="hikes">'
            '<h2>Hikes &amp; Activities</h2>'
            '<p class="muted">Lookouts and the lava caves start <strong>checked</strong>. '
            'Other hikes start unchecked so each day\'s arrival estimate can opt them in. '
            'Times below are the default stop budgets baked into the scheduler, not hard estimates.</p>'
            '<table><thead><tr><th>Hike / activity</th><th>Day</th><th>Budget</th><th>Notes</th></tr></thead>'
            '<tbody>' + ''.join(hike_rows) + '</tbody></table>'
            '<h3>Gear notes</h3>'
            '<ul class="clean">'
            '<li><strong>Falls Creek Lava Caves:</strong> a real lava tube. One headlamp per person '
            '<em>plus</em> a backup light and spare batteries. Pitch dark, uneven basalt floor, cold '
            'year round. Boots and gloves recommended; a helmet or at minimum a beanie saves scalps. '
            'No permit, no paid entry. Full notes: <a href="lava-caves.html">lava caves page</a>.</li>'
            '<li><strong>High Rock Lookout:</strong> the lookout sits on a cliff edge with a serious '
            'drop. Fine for careful adults, worth thinking about with kids or dogs.</li>'
            '<li><strong>Northwest Forest Pass</strong> is required to park at most of these '
            'trailheads. Every vehicle needs its own displayed.</li>'
            '<li><strong>September daylight:</strong> see the table below. Usable light in dense '
            'timber and deep valleys ends well before official sunset, so start the long hikes '
            'before mid-afternoon.</li>'
            '</ul>'
            + _daylight_table_html()
            + '</div>'
        )

    # Emergency card, driven from trip_config.
    _contact_lis = ''.join(
        f'<li><strong>{esc(c["label"])}</strong>: '
        f'<a href="{esc(c["tel"])}">{esc(c["value"])}</a></li>'
        for c in cfg.EMERGENCY_CONTACTS
    )
    _hosp_lis = ''.join(
        f'<li><strong>{esc(h["name"])}</strong>: '
        f'<a href="{esc(h["tel"])}">{esc(h["value"])}</a>'
        f'<div class="muted" style="font-size:12px">{esc(h["detail"])}</div></li>'
        for h in cfg.HOSPITALS
    )
    _cell_lis = ''.join(f'<li>{esc(z)}</li>' for z in cfg.CELL_DEAD_ZONES)
    _permit_lis = ''.join(
        f'<li><strong>{esc(t)}</strong>: {esc(b)}</li>' for t, b in cfg.PERMITS_NOTE
    )
    _gear_lis = ''.join(
        f'<li><strong>{esc(t)}</strong><div class="muted" style="font-size:13px">{esc(b)}</div></li>'
        for t, b in cfg.GEAR_NOTES
    )
    gear_html = (
        '<div class="card" id="gear">'
        '<h2>Trip-specific gear</h2>'
        '<p class="muted">Not a general camping list &mdash; these are the items this route and '
        'season make non-obvious, pulled together from the fuel, camping, fire and lava-caves pages.</p>'
        '<ul class="clean">' + _gear_lis + '</ul>'
        '<p><a href="lava-caves.html">Falls Creek Lava Caves notes</a> '
        '&mdash; gear, permits, white-nose decon, how to find the pits. Cached in this app.</p>'
        '</div>'
    )
    emerg_html = (
        '<div class="card" id="emergency">'
        '<h2>Emergency Contacts &amp; Cell Coverage</h2>'
        '<ul class="clean">' + _contact_lis + '</ul>'
        '<h3>Nearest medical</h3>'
        '<ul class="clean">' + _hosp_lis + '</ul>'
        '<h3>Cell coverage realities</h3>'
        '<ul class="clean">' + _cell_lis + '</ul>'
        '<div class="warn" style="margin-top:12px"><strong>Satellite:</strong> '
        + esc(cfg.SATELLITE_COMMS_NOTE) + '</div>'
        '</div>'
        '<div class="card" id="permits">'
        '<h2>Permits &amp; Passes</h2>'
        '<ul class="clean">' + _permit_lis + '</ul>'
        '<p><a href="lava-caves.html">Falls Creek Lava Caves</a> need no entry permit. '
        'The notes page is in this app and works offline.</p>'
        '</div>'
    )

    # POI description dialog: shared with itinerary (see build_itinerary_html)
    ref_poi_desc_map = collect_poi_descriptions(data)
    ref_poi_desc_json = json.dumps(ref_poi_desc_map, ensure_ascii=False)
    ref_poi_desc_dialog_js = POI_DESC_DIALOG_JS.format(desc_json=ref_poi_desc_json)

    ref_brand_html = (
        f'<h1>{cfg.TRIP_TITLE} - Reference</h1>'
        f'<div class="meta">{cfg.TRIP_DATES_HUMAN} &middot; Full knowledge dump</div>'
    )
    ref_nav_block = _top_nav_html('reference', brand_html=ref_brand_html)
    html_out = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{cfg.TRIP_TITLE} - Reference</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{PWA_HEAD}
<style>{CSS}</style>
</head><body>
{ref_nav_block}
<main>

<div class="card">
<h2>Trip Overview</h2>
<div class="summary-grid">
<div class="summary-stat"><div class="val">{data["trip"]["route_total_miles"]:.0f}</div><div class="lab">Route miles</div></div>
<div class="summary-stat"><div class="val">{len(data["days"])}</div><div class="lab">Days on trip</div></div>
<div class="summary-stat"><div class="val">4</div><div class="lab">Days on route</div></div>
<div class="summary-stat"><div class="val">{cfg.GROUP_COUNTS["vehicles"]}</div><div class="lab">Vehicles</div></div>
<div class="summary-stat"><div class="val">5</div><div class="lab">Nights out</div></div>
<div class="summary-stat"><div class="val">744</div><div class="lab">Highway miles r/t</div></div>
</div>
<p>{esc(data["trip"].get("subtitle") or "")}, starting and ending in the Columbia River Gorge at Carson, WA.
Surface is mostly graded Forest Service gravel with paved stretches on US 12, FS 23 and FS 90, plus rough
narrow spurs to High Rock Lookout, Burley Mountain and Walupt Lake. No water crossings and no technical
obstacles; the challenges here are distance, fuel range, weather and fire closures rather than terrain.</p>
<div class="warn"><strong>Reservations:</strong> {esc(data["trip"].get("reservations_status") or "")}</div>
</div>

<div class="card">
<h2>Real-Time Info Sources</h2>
<p class="muted">Bookmark all of these. Check the fire and closure links every morning you have signal &mdash; for a September trip in Gifford Pinchot those matter more than the weather. Packwood and Randle are the only reliable coverage on route.</p>
{rt_html}
</div>

<div class="card">
<h2>Fuel Plan</h2>
<p>Only three stations sit on or near the route, and the binding constraint is the
<strong>154-mile stretch from Carson (mile 2) to Packwood (mile 156)</strong> with no fuel at all.
Top off in Carson without exception.</p>
<h3>Fuel stations</h3>
{stations_html}
<h3>Route surface breakdown & MPG factors</h3>
{surface_html}
<p>Per-vehicle worksheet and the full gap analysis: <a href="fuel-plan.html">Fuel plan</a> (same offline PWA). Source file for editors: <code>planning/fuel_plan.md</code>.</p>
</div>

{''.join(day_sections)}

{hike_detail}

{gear_html}

{emerg_html}

<div class="card">
<h2>Source Files</h2>
<ul class="clean">
<li><a href="{cfg.ROUTE_GPX_FILENAME}">Original route GPX</a> &mdash; 106 waypoints and the 325-mile main track</li>
<li><a href="trip-plan.gpx" download>trip-plan.gpx</a> &mdash; derived route with day splits and labeled camps, for Gaia / onX / CalTopo / Garmin</li>
<li><a href="camping-plan.html">Camping plan</a> (offline) &mdash; source <code>planning/camping_plan.md</code></li>
<li><a href="fuel-plan.html">Fuel plan</a> (offline) &mdash; source <code>planning/fuel_plan.md</code></li>
<li><a href="fire-and-closures.html">Fire &amp; closures</a> (offline) &mdash; source <code>planning/fire_and_closures.md</code></li>
<li><a href="lava-caves.html">Lava caves</a> (offline) &mdash; source <code>planning/lava_caves.md</code></li>
<li><code>scripts/trip_config.py</code> &mdash; trip identity: title, dates, contacts, map bbox</li>
<li><code>scripts/build_trip_data.py</code> &mdash; day split, campground plan, fuel plan, live links</li>
<li><code>scripts/trip_core.py</code> &mdash; POI catalog and scheduler stop-time defaults</li>
</ul>
</div>

<div class="card">
<h2>{cfg.NWS_ALERT_LABEL}</h2>
<p class="muted">Fetched live when online; ignore if viewing offline. Use <strong>Menu → Weather</strong> or the per-day weather blocks when connectivity is available.</p>
<div id="live-alerts" class="alerts-banner alerts-loading">Checking {cfg.NWS_ALERT_LABEL}...</div>
</div>
{POI_DESC_DIALOG_HTML}
</main>
<script>
function escHTML(s){{return String(s==null?'':s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
async function loadAlerts(){{
  const el=document.getElementById('live-alerts'); if(!el) return;
  try{{
    const r=await fetch('https://api.weather.gov/alerts/active?area={cfg.NWS_ALERT_AREA}',{{headers:{{'Accept':'application/geo+json'}}}});
    if(!r.ok) throw new Error('NWS HTTP '+r.status);
    const j=await r.json(); const feats=j.features||[]; const now=new Date().toLocaleString();
    if(!feats.length){{ el.classList.remove('alerts-loading'); el.classList.add('alerts-ok');
      el.innerHTML='<strong>No active NWS alerts for {cfg.NWS_ALERT_AREA}.</strong> <span class="muted">Checked '+escHTML(now)+'. <a href="https://www.weather.gov/alerts" target="_blank" rel="noopener">Full feed</a></span>'; return; }}
    const rank=e=>/Flash Flood Warning/i.test(e)?0:/Flood Warning/i.test(e)?1:/Severe Thunderstorm Warning/i.test(e)?2:/Warning/i.test(e)?3:/Red Flag/i.test(e)?4:/Watch/i.test(e)?5:/Advisory/i.test(e)?6:7;
    feats.sort((a,b)=>rank(a.properties.event||'')-rank(b.properties.event||''));
    const rows=feats.map(f=>{{const p=f.properties||{{}};const exp=p.expires?new Date(p.expires).toLocaleString():'';
      return '<li><strong>'+escHTML(p.event)+'</strong> &middot; <span class="muted">'+escHTML(p.severity||'')+'</span> &middot; '+escHTML(p.areaDesc||'')+(exp?' &middot; <em>expires '+escHTML(exp)+'</em>':'')+(p.headline?'<div class="alert-desc">'+escHTML(p.headline)+'</div>':'')+'</li>';}}).join('');
    el.classList.remove('alerts-loading'); el.classList.add('alerts-active');
    el.innerHTML='<strong>'+feats.length+' active NWS {cfg.NWS_ALERT_AREA} alert'+(feats.length===1?'':'s')+'.</strong> <span class="muted">Fetched '+escHTML(now)+'. <a href="https://www.weather.gov/alerts" target="_blank" rel="noopener">Full feed</a></span><ul class="alert-list">'+rows+'</ul>';
  }}catch(err){{ el.classList.remove('alerts-loading'); el.classList.add('alerts-offline');
    el.innerHTML='<strong>Live alert check unavailable</strong> <span class="muted">('+escHTML(err.message)+'). See links above when online.</span>'; }}
}}
loadAlerts();
{ref_poi_desc_dialog_js}
</script>
{SPEAK_SETTINGS_JS}
{_speak_engine_js(data)}
{PWA_REGISTER_JS}
</body></html>
"""
    return html_out


# -----------------------------------------------------------------------------
# GPX export
# -----------------------------------------------------------------------------
def _gpx_esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def build_gpx(variant=None):
    """Build a GPX file matching the current module-level `data`.

    `variant` only affects the <metadata> <name>/<desc> strings. Defaults to
    VARIANT_MAIN."""
    variant = variant or VARIANT_MAIN
    gpx_name = variant.get('gpx_metadata_name', f'{cfg.TRIP_TITLE} Trip Plan')
    gpx_desc = variant.get(
        'gpx_metadata_desc',
        f'Day-split tracks, POIs, and primary/backup campgrounds for the {cfg.TRIP_DATES_HUMAN} trip.')
    out = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<gpx version="1.1" creator="build_deliverables.py" xmlns="http://www.topografix.com/GPX/1/1">')
    out.append(f'<metadata><name>{_gpx_esc(gpx_name)}</name>'
               f'<desc>{_gpx_esc(gpx_desc)}</desc>'
               f'<time>{data.get("generated_at", cfg.TRIP_DATE_START)}T00:00:00Z</time></metadata>')

    # Camps first, so a camp reused on more than one night collapses into a
    # single pin carrying every night it serves. Emitting per-day instead would
    # either stack duplicate pins at identical coordinates, or -- if deduped
    # naively -- silently drop the later night's label, which is how the final
    # night's camp went missing from an earlier build.
    camp_nights: dict[tuple, dict] = {}
    for d in data['days']:
        camps = d.get('camps') or {}
        for key, idx, total, c in _iter_camp_entries(camps):
            if not _camp_has_coords(c):
                continue
            ck = (round(c['lat'], 5), round(c['lon'], 5), key, idx)
            entry = camp_nights.setdefault(ck, {'camp': c, 'tier': key, 'idx': idx,
                                                'total': total, 'nights': []})
            night = (d.get('label') or '').split(' - ')[0]
            if night not in entry['nights']:
                entry['nights'].append(night)
            entry['total'] = max(entry['total'], total)

    # Waypoints: POIs (primary / hike) + campsites (primary/secondary tagged).
    for d in data['days']:
        for p in (d.get('pois') or []):
            if p['status'] in ('primary', 'hike_candidate', 'conditional', 'backup'):
                label_prefix = ''
                if p['status'] == 'backup':
                    label_prefix = '[BACKUP] '
                elif p['status'] == 'hike_candidate':
                    label_prefix = '[HIKE] '
                elif p['status'] == 'conditional':
                    label_prefix = '[IF NEEDED] '
                name = label_prefix + (p.get('name') or '')
                desc = p.get('note') or ''
                ele = p.get('ele')
                sym = p.get('sym') or ''
                lines = [
                    f'<wpt lat="{p["lat"]}" lon="{p["lon"]}">',
                    (f'<ele>{ele}</ele>' if ele is not None else ''),
                    f'<name>{_gpx_esc(name)}</name>',
                    (f'<desc>{_gpx_esc(desc)}</desc>' if desc else ''),
                    (f'<sym>{_gpx_esc(sym)}</sym>' if sym else ''),
                    '</wpt>',
                ]
                out.append(''.join(x for x in lines if x))

    # Camp waypoints, one per distinct (location, tier), labeled with every
    # night it covers.
    tag_base = {'primary': '[CAMP PRIMARY]', 'secondary': '[CAMP BACKUP]',
                'tertiary': '[CAMP LAST-RESORT]'}
    for entry in camp_nights.values():
        c = entry['camp']
        tag = tag_base[entry['tier']]
        if entry['total'] > 1:
            tag = tag[:-1] + f'-{chr(ord("A") + entry["idx"] - 1)}]'
        nights = ' + '.join(entry['nights'])
        name = f'{tag} {nights} - {c.get("name", "")}'
        desc = (f'{c.get("cost", "")} | {c.get("facilities", "")} | '
                f'{c.get("notes", "")} | Access: {c.get("access", "")}').strip(' |')
        out.append(''.join([
            f'<wpt lat="{c["lat"]}" lon="{c["lon"]}">',
            f'<name>{_gpx_esc(name)}</name>',
            f'<desc>{_gpx_esc(desc)}</desc>',
            '<sym>Campground</sym>',
            '</wpt>',
        ]))
        # Cluster members get their own waypoint so offline mapping apps show
        # the full site layout rather than just the anchor.
        if entry['tier'] == 'primary' and isinstance(c.get('cluster_members'), list):
            for m in c['cluster_members']:
                if not _camp_has_coords(m):
                    continue
                out.append(''.join([
                    f'<wpt lat="{m["lat"]}" lon="{m["lon"]}">',
                    f'<name>{_gpx_esc("[CAMP PRIMARY-CLUSTER] " + nights + " - " + (m.get("name") or ""))}</name>',
                    f'<desc>{_gpx_esc("Designated site in the primary cluster anchored at " + (c.get("name") or ""))}</desc>',
                    '<sym>Campground</sym>',
                    '</wpt>',
                ]))

    # Tracks: one <trk> per day
    for d in data['days']:
        pts = d.get('track_points') or []
        if not pts:
            continue
        out.append(f'<trk><name>{_gpx_esc(d["label"])}</name><trkseg>')
        for lat, lon in pts:
            out.append(f'<trkpt lat="{lat}" lon="{lon}"></trkpt>')
        out.append('</trkseg></trk>')

    # Extra polyline for days that also cover a highway leg (e.g. the final
    # day closes the loop and then drives home).
    for d in data['days']:
        extra = d.get('extra_track_points') or []
        if not extra:
            continue
        out.append(f'<trk><name>{_gpx_esc(d["label"] + " - highway leg")}</name><trkseg>')
        for lat, lon in extra:
            out.append(f'<trkpt lat="{lat}" lon="{lon}"></trkpt>')
        out.append('</trkseg></trk>')

    out.append('</gpx>')
    return '\n'.join(out)


# -----------------------------------------------------------------------------
# Render driver: one variant = one HTML itinerary + one GPX file.
# -----------------------------------------------------------------------------
def render_variant(variant):
    """Render a variant's itinerary HTML + GPX from its trip_data JSON.

    Reassigns the module-level `data` and `overview_track` globals so the
    existing build_itinerary_html / build_gpx helpers (which read from them)
    operate on the loaded payload without threading `data` through every
    nested call."""
    global data, overview_track
    payload_path = variant['data_path']
    if not payload_path.exists():
        print(f'Skipping {variant["key"]}: {payload_path.relative_to(BASE)} missing '
              f'(run scripts/build_trip_data.py first)')
        return
    data = json.loads(payload_path.read_text(encoding='utf-8'))
    overview_track = prepare_variant_context(data)

    html_out = build_itinerary_html(variant)
    variant['html_path'].write_text(html_out, encoding='utf-8')
    print(f'Wrote {variant["html_path"].name} ({len(html_out) / 1024:.1f} KB)')

    gpx_out = build_gpx(variant)
    variant['gpx_path'].write_text(gpx_out, encoding='utf-8')
    print(f'Wrote {variant["gpx_path"].name} ({len(gpx_out) / 1024:.1f} KB)')


def main():
    for variant in ALL_VARIANTS:
        render_variant(variant)

    ref = build_reference_html()
    (OUT_DIR / 'trip-reference.html').write_text(ref, encoding='utf-8')
    print(f'Wrote trip-reference.html ({len(ref) / 1024:.1f} KB)')

    # Standalone markdown -> HTML PWA pages (fuel, fire & closures, camping).
    write_planning_markdown_pages()
    write_weather_html()
    write_settings_html()


if __name__ == '__main__':
    main()
