"""Find free / primitive / dispersed campsites near the Washington Cascades route.

Two data sources are queried and merged:

  1. RIDB (Recreation Information Database) — official US federal API covering
     USFS, BLM, NPS and other agency primitive and dispersed facilities.
     Requires a free API key: sign up at https://ridb.recreation.gov then copy
     the key from your profile page.  Set it as RIDB_API_KEY in the environment
     or pass --ridb-key on the command line.

  2. FreeCampsites.net — community-sourced directory of informal dispersed
     spots and free first-come sites that are often not in RIDB.  Their API
     endpoint requires a real browser origin (same-site cookies + Referer), so
     this part drives Chromium via Playwright.  Install once with:
         pip install playwright
         playwright install chromium
     The browser opens visibly so you can watch it work.  Pass --headless if
     you want it hidden.

Usage:
    # both sources (recommended):
    export RIDB_API_KEY=your-key-here
    python scripts/find_dispersed_campsites.py

    # RIDB only (no browser needed):
    python scripts/find_dispersed_campsites.py --source ridb --ridb-key YOUR_KEY

    # FreeCampsites only (no RIDB key needed):
    python scripts/find_dispersed_campsites.py --source freecampsites

    # Show results but do not write the JSON output file:
    python scripts/find_dispersed_campsites.py --dry-run

Output:
    planning/dispersed_sites.json  — deduplicated site list; review before use
    stdout                         — formatted summary report

The JSON output can be reviewed and any interesting sites can be copied into
the CAMPSITES table in build_trip_data.py.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPTS = pathlib.Path(__file__).resolve().parent
BASE = _SCRIPTS.parent
PLAN = BASE / 'planning'
OUTPUT_PATH = PLAN / 'dispersed_sites.json'

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402

# ---------------------------------------------------------------------------
# Route geometry — search centers and bounding box
# ---------------------------------------------------------------------------
# Five points spread around the 325-mile loop give ~30-40 mi radius coverage
# for each source query without any single call being too broad.
SEARCH_CENTERS = [
    (46.28, -121.60, 'High Lakes / Takhlakh (Day 1)'),
    (46.42, -121.47, 'Walupt / Goat Rocks (Day 2)'),
    (46.45, -121.79, 'North Fork / Cispus (Day 3)'),
    (46.05, -121.70, 'Mid-route / FS 23 corridor'),
    (45.82, -121.88, 'Wind River / Panther Creek (Travel + Day 4)'),
]

ROUTE_BBOX = cfg.TILE_BBOX  # lat 45.55-46.95, lon -122.45 to -121.20

# Radius in miles for each RIDB query centre.
RIDB_RADIUS_MI = 35

# Max sites per FreeCampsites.net call.
FCS_MAX_SITES = 50

# Sites already in the plan — used to flag known vs. new results.
KNOWN_SITE_NAMES = {
    s.lower() for s in (
        'Panther Creek', 'Takhlakh Lake', 'Walupt Lake',
        'North Fork Elk Group', 'North Fork Elk Group Camp',
        'North Fork Bear Group', 'North Fork Bear Group Camp',
        'North Fork Campground', 'North Fork',
        'Tower Rock', 'Adams Fork', 'Iron Creek', 'Peterson Prairie',
        'Council Lake', 'Olallie Lake', 'Horseshoe Lake', 'Chain of Lakes',
        'Chambers Lake', 'Cat Creek', 'Crest Camp',
        'Home Valley', 'Moss Creek', 'Big Cedars',
        'Goose Lake', 'Forlorn Lakes', 'Cultus Creek',
    )
}

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    r = 3_958.8  # Earth radius in miles
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return r * 2 * math.asin(math.sqrt(a))


def in_route_bbox(lat: float, lon: float) -> bool:
    bb = ROUTE_BBOX
    return (bb['lat_min'] <= lat <= bb['lat_max']
            and bb['lon_min'] <= lon <= bb['lon_max'])


# ---------------------------------------------------------------------------
# RIDB source
# ---------------------------------------------------------------------------
RIDB_BASE = 'https://ridb.recreation.gov/api/v1'

# FacilityTypeDescription values we want to include.  RIDB uses these strings.
RIDB_CAMPING_TYPES = {
    'camping', 'primitive camping', 'dispersed camping',
    'primitive', 'dispersed', 'backcountry camping',
    'tent only camping', 'walk-to camping',
}


def _ridb_get(path: str, params: dict, api_key: str) -> dict:
    qs = '&'.join(f'{k}={urllib.request.quote(str(v))}' for k, v in params.items())
    url = f'{RIDB_BASE}/{path}?{qs}&apikey={api_key}'
    req = urllib.request.Request(url, headers={
        'User-Agent': cfg.TILE_USER_AGENT,
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def _is_camping_facility(facility: dict) -> bool:
    ftype = (facility.get('FacilityTypeDescription') or '').lower()
    if any(t in ftype for t in RIDB_CAMPING_TYPES):
        return True
    # Also include non-reservable facilities whose activity list includes Camping
    # (activity id 9 = Camping in the RIDB activity taxonomy)
    for act in facility.get('FACILITYACTIVITY') or []:
        if str(act.get('ActivityID')) == '9':
            return True
    return False


def query_ridb(api_key: str, verbose: bool = True) -> list[dict]:
    """Return a deduplicated list of primitive/dispersed campsite dicts from RIDB."""
    seen_ids: set[str] = set()
    sites: list[dict] = []

    for lat, lon, label in SEARCH_CENTERS:
        if verbose:
            print(f'  RIDB  querying near {label} …')
        offset = 0
        while True:
            try:
                data = _ridb_get('facilities', {
                    'latitude': lat,
                    'longitude': lon,
                    'radius': RIDB_RADIUS_MI,
                    'state': 'WA',
                    'limit': 50,
                    'offset': offset,
                    'full': 'true',
                }, api_key)
            except urllib.error.HTTPError as exc:
                print(f'    RIDB HTTP {exc.code}: {exc.reason}', file=sys.stderr)
                break
            except Exception as exc:  # noqa: BLE001
                print(f'    RIDB error: {exc}', file=sys.stderr)
                break

            facilities = data.get('RECDATA') or []
            if not facilities:
                break

            for f in facilities:
                fid = str(f.get('FacilityID', ''))
                if fid in seen_ids:
                    continue
                if not _is_camping_facility(f):
                    continue
                f_lat = f.get('FacilityLatitude') or 0
                f_lon = f.get('FacilityLongitude') or 0
                if not f_lat or not f_lon:
                    continue
                if not in_route_bbox(float(f_lat), float(f_lon)):
                    continue
                seen_ids.add(fid)
                reservable = bool(f.get('Reservable'))
                sites.append({
                    'source': 'ridb',
                    'ridb_id': fid,
                    'name': f.get('FacilityName', '').strip(),
                    'lat': float(f_lat),
                    'lon': float(f_lon),
                    'fee': 'Fee' if reservable else 'Unknown / likely free',
                    'reservable': reservable,
                    'facility_type': f.get('FacilityTypeDescription', ''),
                    'facilities': f.get('FacilityDescription', '')[:200].replace('\n', ' '),
                    'url': (f'https://www.recreation.gov/camping/campgrounds/{fid}'
                            if reservable else ''),
                    'notes': '',
                })

            total = data.get('METADATA', {}).get('RESULTS', {}).get('TOTAL_COUNT', 0)
            offset += len(facilities)
            if offset >= total or len(facilities) < 50:
                break
            time.sleep(0.5)

        time.sleep(1)

    return sites


# ---------------------------------------------------------------------------
# FreeCampsites.net source  (requires Playwright)
# ---------------------------------------------------------------------------
_FCS_JS = """\
(args) => new Promise((resolve, reject) => {{
    const xhr = new XMLHttpRequest();
    const url = '/wp-content/themes/freecampsites/androidApp.php'
        + '?location=' + args.lat + ',' + args.lon
        + '&coordinates=' + args.lat + ',' + args.lon
        + '&max_sites=' + args.max_sites;
    xhr.open('GET', url);
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.onload = function() {{ resolve(xhr.responseText); }};
    xhr.onerror = function() {{ reject('XHR network error'); }};
    xhr.ontimeout = function() {{ reject('XHR timeout'); }};
    xhr.timeout = 20000;
    xhr.send();
}})
"""


def _parse_fcs_response(raw: str) -> list[dict]:
    """Strip the WordPress whitespace preamble and parse JSON."""
    # The response may start with many blank lines before the JSON object.
    idx = raw.find('{')
    if idx < 0:
        return []
    try:
        data = json.loads(raw[idx:])
    except json.JSONDecodeError:
        return []
    return data.get('resultList') or []


def query_freecampsites(headless: bool = False, verbose: bool = True) -> list[dict]:
    """Return a list of campsite dicts from FreeCampsites.net via Playwright."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print(
            '\nPlaywright not installed.  Run:\n'
            '    pip install playwright\n'
            '    playwright install chromium\n'
            'Then re-run this script, or use --source ridb to skip FreeCampsites.',
            file=sys.stderr,
        )
        return []

    sites: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            )
        )
        page = ctx.new_page()

        if verbose:
            print('  FCS   opening freecampsites.net …')
        try:
            page.goto('https://www.freecampsites.net', wait_until='domcontentloaded',
                      timeout=30_000)
            # Brief pause so cookies / any JS init can settle.
            page.wait_for_timeout(2_000)
        except PWTimeout:
            print('    FCS   page load timed out', file=sys.stderr)
            browser.close()
            return []

        for lat, lon, label in SEARCH_CENTERS:
            if verbose:
                print(f'  FCS   querying near {label} …')
            try:
                raw = page.evaluate(
                    _FCS_JS,
                    {'lat': lat, 'lon': lon, 'max_sites': FCS_MAX_SITES},
                )
            except PWTimeout:
                print(f'    FCS   XHR timed out for {label}', file=sys.stderr)
                continue
            except Exception as exc:  # noqa: BLE001
                print(f'    FCS   error for {label}: {exc}', file=sys.stderr)
                continue

            records = _parse_fcs_response(raw or '')
            if verbose:
                print(f'    → {len(records)} results')

            for r in records:
                site_id = str(r.get('id', ''))
                if site_id in seen_ids:
                    continue
                try:
                    s_lat = float(r.get('latitude') or 0)
                    s_lon = float(r.get('longitude') or 0)
                except (TypeError, ValueError):
                    continue
                if not s_lat or not s_lon:
                    continue
                if not in_route_bbox(s_lat, s_lon):
                    continue
                seen_ids.add(site_id)
                fee_raw = (r.get('type_specific') or {}).get('fee') or ''
                sites.append({
                    'source': 'freecampsites',
                    'fcs_id': site_id,
                    'name': (r.get('name') or '').strip(),
                    'lat': s_lat,
                    'lon': s_lon,
                    'fee': fee_raw if fee_raw else 'Unknown',
                    'reservable': False,
                    'facility_type': 'community-sourced',
                    'facilities': (r.get('excerpt') or '')[:200].replace('\n', ' '),
                    'rating': r.get('ratings_average'),
                    'rating_count': r.get('ratings_count'),
                    'url': r.get('url') or '',
                    'notes': f"FreeCampsites.net listing — {r.get('city', '')}, {r.get('county', '')} county",
                })

            time.sleep(1)

        browser.close()

    return sites


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
DEDUP_THRESHOLD_MI = 0.4  # sites closer than this are treated as the same site


def deduplicate(sites: list[dict]) -> list[dict]:
    """Merge sites that are within DEDUP_THRESHOLD_MI of each other.

    RIDB entries take precedence over FreeCampsites when deduplicating.
    """
    # Sort so RIDB entries come first (they win ties).
    ordered = sorted(sites, key=lambda s: 0 if s['source'] == 'ridb' else 1)
    kept: list[dict] = []
    for site in ordered:
        too_close = False
        for existing in kept:
            dist = haversine_mi(site['lat'], site['lon'],
                                existing['lat'], existing['lon'])
            if dist < DEDUP_THRESHOLD_MI:
                # Annotate the kept entry with the duplicate source.
                existing.setdefault('also_in', [])
                existing['also_in'].append(site['source'])
                too_close = True
                break
        if not too_close:
            kept.append(site)
    return kept


# ---------------------------------------------------------------------------
# Plan membership check
# ---------------------------------------------------------------------------

def _name_key(name: str) -> str:
    return name.lower().strip().rstrip(' campground').rstrip(' camp').strip()


def flag_known(sites: list[dict]) -> None:
    """Set 'already_in_plan' on each site dict."""
    for s in sites:
        key = _name_key(s['name'])
        s['already_in_plan'] = (
            key in KNOWN_SITE_NAMES
            or s['name'].lower() in KNOWN_SITE_NAMES
        )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _fee_display(site: dict) -> str:
    fee = site.get('fee') or ''
    fee_lc = fee.lower()
    if 'free' in fee_lc:
        return 'FREE'
    if site.get('reservable'):
        return 'Fee (reservable)'
    if 'fee' in fee_lc:
        return 'Fee'
    return fee or '?'


def print_report(sites: list[dict]) -> None:
    new_sites = [s for s in sites if not s.get('already_in_plan')]
    known_sites = [s for s in sites if s.get('already_in_plan')]

    def _section(heading: str, items: list[dict]) -> None:
        print(f'\n{"=" * 60}')
        print(heading)
        print('=' * 60)
        if not items:
            print('  (none)')
            return
        for s in sorted(items, key=lambda x: (x['lat'], x['lon'])):
            src = s['source'].upper()[:4]
            fee = _fee_display(s)
            rating = ''
            if s.get('rating') is not None:
                rating = f'  ★ {s["rating"]:.1f}/5 ({s.get("rating_count", 0)} reviews)'
            print(f'\n  [{src}] {s["name"]}')
            print(f'         {s["lat"]:.5f}, {s["lon"]:.5f}  |  {fee}{rating}')
            if s.get('facility_type') and s['facility_type'] not in ('community-sourced',):
                print(f'         Type: {s["facility_type"]}')
            if s.get('facilities'):
                snippet = s['facilities'][:120]
                print(f'         {snippet}{"…" if len(s["facilities"]) > 120 else ""}')
            if s.get('url'):
                print(f'         {s["url"]}')
            if s.get('also_in'):
                print(f'         (also found in: {", ".join(set(s["also_in"]))})')

    free_new = [s for s in new_sites if 'free' in (s.get('fee') or '').lower()]
    fee_new = [s for s in new_sites if 'free' not in (s.get('fee') or '').lower()]

    _section(f'NEW FREE sites not already in the plan ({len(free_new)})', free_new)
    _section(f'NEW other / unknown-fee sites not in plan ({len(fee_new)})', fee_new)
    _section(f'Already in the plan — confirmed ({len(known_sites)})', known_sites)

    print(f'\nTotal: {len(sites)} unique sites  '
          f'({len(new_sites)} new, {len(known_sites)} already known)')


def write_json(sites: list[dict], path: pathlib.Path) -> None:
    out = {
        'generated': datetime.now(timezone.utc).isoformat(),
        'route': cfg.TRIP_TITLE,
        'bbox': ROUTE_BBOX,
        'search_centers': [
            {'lat': lat, 'lon': lon, 'label': lbl}
            for lat, lon, lbl in SEARCH_CENTERS
        ],
        'total_sites': len(sites),
        'new_sites': sum(1 for s in sites if not s.get('already_in_plan')),
        'sites': sites,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nSaved {len(sites)} sites → {path.relative_to(BASE)}')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='Find free/primitive/dispersed campsites near the WA Cascades route.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        '--source', choices=['ridb', 'freecampsites', 'both'], default='both',
        help='Which data source(s) to query (default: both)',
    )
    p.add_argument(
        '--ridb-key', default=os.environ.get('RIDB_API_KEY', ''),
        metavar='KEY',
        help='RIDB API key (overrides RIDB_API_KEY env var)',
    )
    p.add_argument(
        '--headless', action='store_true',
        help='Run the FreeCampsites browser in headless mode (default: visible)',
    )
    p.add_argument(
        '--output', default=str(OUTPUT_PATH), metavar='PATH',
        help=f'JSON output path (default: {OUTPUT_PATH.relative_to(BASE)})',
    )
    p.add_argument(
        '--dry-run', action='store_true',
        help='Print results but do not write the JSON file',
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    use_ridb = args.source in ('ridb', 'both')
    use_fcs = args.source in ('freecampsites', 'both')

    if use_ridb and not args.ridb_key:
        print(
            'RIDB API key not set.  Get a free key at https://ridb.recreation.gov\n'
            'then set RIDB_API_KEY in the environment or pass --ridb-key KEY.\n'
            'Skipping RIDB source.',
            file=sys.stderr,
        )
        use_ridb = False

    all_sites: list[dict] = []

    if use_ridb:
        print('\n── RIDB (Recreation Information Database) ──────────────')
        ridb_sites = query_ridb(args.ridb_key, verbose=True)
        print(f'  Found {len(ridb_sites)} RIDB facilities in route bbox')
        all_sites.extend(ridb_sites)

    if use_fcs:
        print('\n── FreeCampsites.net ─────────────────────────────────────')
        if not args.headless:
            print('  Opening a visible Chromium window — it will close when done.')
        fcs_sites = query_freecampsites(headless=args.headless, verbose=True)
        print(f'  Found {len(fcs_sites)} FreeCampsites.net entries in route bbox')
        all_sites.extend(fcs_sites)

    if not all_sites:
        print('\nNo sites found.  Check API key and network connectivity.')
        return

    print('\n── Deduplicating ─────────────────────────────────────────')
    deduped = deduplicate(all_sites)
    removed = len(all_sites) - len(deduped)
    print(f'  {len(all_sites)} total → {len(deduped)} unique  ({removed} duplicates merged)')

    flag_known(deduped)

    print_report(deduped)

    if not args.dry_run:
        write_json(deduped, pathlib.Path(args.output))
    else:
        print('\n(--dry-run: JSON file not written)')


if __name__ == '__main__':
    main()
