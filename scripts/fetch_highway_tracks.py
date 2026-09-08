"""Fetch driving polylines for the highway travel legs via OSRM.

The trip's on-route days come from the source GPX, but the drive out from Nampa
and the drive home are ordinary highway miles with no GPX track. This pulls
them from the public OSRM demo server so the travel days still draw a line on
the map.

Writes planning/highway_tracks.json:
    { "<leg_key>": [[lat, lon], ...], ..., "source": "...", "legs": {...} }

Idempotent-ish: re-running refetches. Network required. If OSRM is unreachable
the existing file is left alone so a transient failure can't blank the maps.

Usage:
    python scripts/fetch_highway_tracks.py
"""
from __future__ import annotations
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402

BASE = _SCRIPTS.parent
PLAN = BASE / 'planning'
OUT = PLAN / 'highway_tracks.json'

OSRM = 'https://router.project-osrm.org/route/v1/driving/'
DECIMATE_EVERY = 6  # OSRM returns dense geometry; thin it for page weight.

MEET = (cfg.MEET_POINT['lat'], cfg.MEET_POINT['lon'])
ROUTE_START = (cfg.ROUTE_START['lat'], cfg.ROUTE_START['lon'])
# Tuesday night primary: FR 68 pullout west of Triangle Pass.
TRIANGLE_PASS_CAMP = (45.78538, -121.75436)

LEGS = {
    'sep8_nampa_to_carson': {
        'label': 'Nampa, ID -> Triangle Pass dispersed camp (via Carson fuel)',
        'points': [MEET, ROUTE_START, TRIANGLE_PASS_CAMP],
    },
    'sep13_carson_to_nampa': {
        'label': 'Carson, WA -> Nampa, ID (drive home)',
        'points': [ROUTE_START, MEET],
    },
}


def osrm_route(points: list[tuple[float, float]]) -> dict:
    coords = ';'.join(f'{lon},{lat}' for lat, lon in points)
    url = (OSRM + urllib.parse.quote(coords)
           + '?overview=full&geometries=geojson&steps=false')
    req = urllib.request.Request(url, headers={'User-Agent': cfg.TILE_USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def main() -> None:
    out: dict = {
        'source': ('Highway polylines follow OpenStreetMap road geometry via the public OSRM '
                   'demo router. They are planning aids, not turn-by-turn navigation.'),
        'legs': {},
    }
    failures = []
    for key, spec in LEGS.items():
        try:
            data = osrm_route(spec['points'])
            route = data['routes'][0]
            line = route['geometry']['coordinates']  # [lon, lat]
            pts = [[round(lat, 5), round(lon, 5)] for lon, lat in line]
            thinned = pts[::DECIMATE_EVERY]
            if thinned and thinned[-1] != pts[-1]:
                thinned.append(pts[-1])
            out[key] = thinned
            miles = route['distance'] / 1609.344
            hours = route['duration'] / 3600.0
            out['legs'][key] = {
                'label': spec['label'],
                'miles': round(miles, 1),
                'driving_hours': round(hours, 2),
                'point_count': len(thinned),
            }
            print(f'{key}: {miles:.1f} mi, {hours:.2f} hr moving, '
                  f'{len(pts)} pts -> {len(thinned)} after decimation')
        except Exception as e:  # noqa: BLE001 -- network diagnostics only
            print(f'{key}: FAILED ({e})')
            failures.append(key)
        time.sleep(1)

    if failures and OUT.exists():
        print(f'\n{len(failures)} leg(s) failed; leaving existing {OUT.name} untouched.')
        return
    if failures:
        print(f'\n{len(failures)} leg(s) failed and no previous file exists. '
              f'Travel-day maps will have no highway line.')

    OUT.write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f'\nWrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)')


if __name__ == '__main__':
    main()
