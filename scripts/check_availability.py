"""Query live Recreation.gov availability for the campgrounds on this route.

The campground plan in ``build_trip_data.py`` carries a snapshot of these
numbers. Re-run this to see how far they have drifted, or after any change to
the day split.

Facility ids come from the Recreation.gov URL:
``recreation.gov/camping/campgrounds/<id>``.

Usage:
    python scripts/check_availability.py
"""
from __future__ import annotations
import json
import pathlib
import sys
import time
import urllib.request

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402

# The five nights the group is out.
TARGET_DATES = ['2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11', '2026-09-12']
MONTH_START = '2026-09-01'

# (facility_id, label, route mile, which night it is wanted for)
TARGETS = [
    ('233103',   'Panther Creek',            'mi 308.4', 'Sat Sep 12'),
    ('10250549', 'Goose Lake',               'mi 34.5',  'first-come only'),
    ('232895',   'Peterson Prairie',         'mi 36.0',  'Day 1 backup'),
    ('10352092', 'Forlorn Lakes',            'mi 38.6',  'first-come only'),
    ('10351695', 'Cultus Creek',             'mi 50.2',  'first-come only'),
    ('232861',   'Takhlakh Lake',            'mi 83.5',  'Wed Sep 9  <-- priority 2'),
    ('232857',   'Adams Fork',               'mi 99.6',  'Day 2 alternative'),
    ('10250494', 'Cat Creek',                'mi 101.2', 'first-come only'),
    ('232860',   'Walupt Lake',              'mi 132.8', 'Thu Sep 10  <-- priority 4'),
    ('232852',   'North Fork',               'mi 226.2', 'Day 3 tertiary'),
    ('232896',   'North Fork BEAR GROUP',    'mi 226',   'group site'),
    ('232898',   'North Fork ELK GROUP',     'mi 226',   'Fri + Sat  <-- PRIORITY 1'),
    ('232855',   'Tower Rock',               'mi 228.6', 'Day 3 secondary'),
    ('232853',   'Iron Creek',               'mi 230.8', 'was CLOSED at last check'),
]

UA = {
    'User-Agent': cfg.TILE_USER_AGENT,
    'Accept': 'application/json',
}


def fetch_month(cg_id: str) -> dict:
    url = (f'https://www.recreation.gov/api/camps/availability/campground/'
           f'{cg_id}/month?start_date={MONTH_START}T00%3A00%3A00.000Z')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def summarize(cg_id: str, label: str, mile: str, want: str) -> None:
    data = fetch_month(cg_id)
    campsites = data.get('campsites', {})
    print(f'\n=== {label} ({mile}) id={cg_id}')
    print(f'    wanted for: {want}')
    print(f'    sites in feed: {len(campsites)}')
    for night in TARGET_DATES:
        buckets: dict[str, list[str]] = {}
        for site_id, site in campsites.items():
            status = site.get('availabilities', {}).get(night + 'T00:00:00Z')
            if status:
                buckets.setdefault(status, []).append(site.get('site') or site_id)
        avail = sorted(buckets.get('Available', []))
        others = ', '.join(f'{k}={len(v)}' for k, v in sorted(buckets.items())
                           if k != 'Available')
        flag = '  <-- NONE' if not avail else ''
        print(f'      {night}: available={len(avail):3d}   {others}{flag}')
        if avail:
            shown = ', '.join(avail[:12])
            more = f' (+{len(avail) - 12} more)' if len(avail) > 12 else ''
            print(f'          {shown}{more}')


def main() -> None:
    print('Recreation.gov live availability')
    print(f'Nights: {", ".join(TARGET_DATES)}')
    print('"Not Reservable" means a first-come site: it will never show as '
          'available here but may still be open on arrival.')
    for cg_id, label, mile, want in TARGETS:
        try:
            summarize(cg_id, label, mile, want)
        except Exception as e:  # noqa: BLE001 -- diagnostic tool
            print(f'\n=== {label} id={cg_id} ERROR: {e}')
        time.sleep(2)
    print('\nBooking priority: North Fork Elk Group (Fri+Sat), Takhlakh Lake (Wed), '
          'Panther Creek (Sat), Walupt Lake (Thu).')


if __name__ == '__main__':
    main()
