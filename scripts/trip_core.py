"""Shared library for building the consolidated trip_data JSON payload.

Public entry points:

* ``load_route(plan_dir)`` -- one-time load of ``route_analysis.json`` +
  ``route_tracks.json`` into a dict used by every subsequent call.
* ``build_payload(...)`` -- turns a ``days_spec`` list plus camp data and
  schedule defaults into the JSON payload written to disk.

The POI catalog (``POI_STATUS``, ``POI_RENAME``, ``POI_SPUR_OVERRIDES``,
``default_minutes``) lives here. Waypoints are matched by their exact ``<name>``
from the source GPX, so keep the keys byte-identical to the GPX -- including
typos.

POI status values
-----------------
``primary``         Planned stop. Checked by default in the ETA scheduler.
``hike_candidate``  Hike or activity to triage. Not checked by default, except
                    lava tubes and fire lookouts, which start on the day's plan.
``backup``          Lower-priority option. Not checked.
``landmark``        A distant peak or reference marker, not somewhere you drive
                    to. Zero stop minutes and never checked -- without this the
                    scheduler would try to add a 25-mile round trip for a
                    waypoint that just labels Mount Rainier.
``logistics``       Fuel and services.
``skip``            Deliberately excluded (usually a trailhead waypoint that
                    duplicates the destination waypoint next to it).
"""
from __future__ import annotations
import json
import math
import pathlib
import sys
from typing import Any

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402


# ---------------------------------------------------------------------------
# POI catalog
# ---------------------------------------------------------------------------
POI_STATUS: dict[str, tuple[str, str]] = {
    # --- Day 1: Carson -> Takhlakh Lake (mi 0-84.5) ---------------------
    'DP - Columbia River Gorge':      ('primary', 'Trip start. Only sea-level breach of the Cascade Range.'),
    'Gas Station':                    ('logistics', 'Fuel stop'),
    'DP - High Bridge':               ('primary', 'Wind River Rd crossing high above the canyon.'),
    'DP - Wind River':                ('backup', 'Same pullout as High Bridge.'),
    'Triangle Pass':                  ('backup', 'Loop junction. The route returns through here at mi 324.8 on the final day.'),
    'DP - Big Lava Bed':              ('primary', 'Rugged 8,200-year-old basalt flow from the Indian Heaven volcanic field.'),
    'Monte Cristo Slab':              ('backup', 'Rock-climbing crag ~1.9 mi off route.'),
    'DP - Goose Lake':                ('primary', 'Lava-dammed lake; the Big Lava Bed flow created it.'),
    'DP - Guler Ice Cave':            ('hike_candidate', 'Developed 650-ft lava tube west of Trout Lake. $5 day-use / Northwest Forest Pass. Ladder entry; ice features are often gone by September. About 4.5 mi off route (9 mi round trip). Decontaminate kit before Falls Creek on Saturday.'),
    'Interpretive Site: Peterson Prairie': ('backup', '~3.4 mi off route, next to Peterson Prairie Campground.'),
    'DP - Forlorn Lakes':             ('primary', 'Chain of about a dozen small lakes at ~3,700 ft.'),
    'Indian Viewpoint':               ('primary', 'Roadside viewpoint on the Indian Heaven shoulder.'),
    'DP - Berry Fields Interpretive Site': ('primary', 'Sawtooth Berry Fields - a tribal gathering place for over 9,000 years. Ripe huckleberries in September; the fields are reserved for tribal harvest in places, so read the posted signs.'),
    'Langfield Falls trailhead':      ('skip', 'Trailhead marker; DP - Langfield Falls is the destination.'),
    'DP - Basket Tree Interpretive Site': ('primary', 'Preserved cedar showing traditional bark harvesting.'),
    'DP - Langfield Falls':           ('hike_candidate', 'Short, easy trail to the falls on Big Mosquito Creek. Good first stretch-the-legs stop.'),
    'Steamboat Viewpoint trail':      ('skip', 'Trailhead marker; DP - Steamboat Mountain Lookout is the destination.'),
    'DP - Steamboat Mountain Lookout': ('hike_candidate', 'Former lookout site at 5,424 ft. Steep but short; big Cascades panorama.'),
    'Mt Adams Viewpoint':             ('primary', 'Roadside Mount Adams view.'),
    'Swampy Meadows':                 ('backup', 'Subalpine meadow, good wildlife stop.'),
    'DP - Lewis River':               ('backup', 'Headwaters draining Adams Glacier.'),
    'DP - Council Lake':              ('primary', 'Small high lake at ~4,200 ft.'),
    'DP - Council Bluff':             ('hike_candidate', 'Short steep climb to a ~4,800 ft summit with a panoramic payoff. Historic council site.'),
    'Council Bluff trailhead':        ('skip', 'Trailhead marker; DP - Council Bluff is the destination.'),
    'DP - Babyshoe Pass':             ('primary', '~4,350 ft pass on FS 23. Gravel over the top.'),
    'DP - Takhlakh Lake':             ('primary', 'The signature view of the route: Mount Adams reflected in the lake. Day 1 overnight is the free High Lakes cluster (Council, Olallie and nearby pullouts), not the paid campground.'),

    # --- Day 2: Takhlakh -> Walupt Lake (mi 84.5-133.5) -----------------
    'DP - Takh Takh Lava Flow':       ('primary', 'Young basalt flow off Mount Adams, right beside Takhlakh Lake.'),
    'DP - Mt Adams':                  ('landmark', 'Reference marker for the 12,276 ft summit - view it, do not drive to it.'),
    'Midway Warming Hut':             ('backup', 'Simple non-reservable winter shelter; hub of the Midway trail network.'),
    'DP - Cispus River':              ('primary', 'Upper Cispus, fed from Snowgrass Flats in the Goat Rocks.'),
    'DP - Hamilton Buttes':           ('hike_candidate', '5,772 ft summit in the Dark Divide. Longer climb; big views.'),
    'DP - Bishop Falls':              ('hike_candidate', 'Hidden multi-tier falls in a steep, remote canyon. Access is rough - scout before committing.'),
    'DP - Walupt Creek Falls':        ('hike_candidate', 'Roughly 220-245 ft of tiered falls.'),
    'Walupt Creek Falls Trailhead':   ('skip', 'Trailhead marker; DP - Walupt Creek Falls is the destination.'),
    'DP - Walupt Lake':               ('primary', 'Second-largest lake in the forest and the deepest in the county. Visit for the lake and Goat Rocks trailheads; Thursday night is Chambers Lake (free), with Walupt CG as the paid backup.'),
    'DP - Gilbert Peak':              ('landmark', 'Reference marker for the 8,184 ft high point of the Goat Rocks.'),

    # --- Day 3: Walupt -> North Fork (mi 133.5-226.5) -------------------
    'Goat Ridge Lookout':             ('backup', '~2.3 mi off route.'),
    'DP - High Rock Lookout':         ('hike_candidate', 'About 3 miles round trip to a historic lookout perched over a cliff, with Mount Rainier only 13 air miles away. The best view on the route and the single most worthwhile hike. Access road is rough; the last stretch is narrow.'),
    'High Rock Trailhead':            ('skip', 'Trailhead marker; DP - High Rock Lookout is the destination.'),
    'DP - Mt Rainier':                ('landmark', 'Reference marker for the 14,410 ft summit - view it, do not drive to it.'),
    'DP - Cowlitz River':             ('backup', 'Glacier-fed Cowlitz, alongside US 12.'),
    'Layser Cave':                    ('primary', 'Interpreted rock shelter above the Cispus valley and one of the most significant archaeological sites in the western Cascades. Short walk from the parking area.'),
    'Camp Creek Falls':               ('primary', 'Short roadside waterfall stop.'),

    # --- Day 4: North Fork -> Panther Creek (mi 226.5-308.5) ------------
    'DP - Burley Mountain Fire Lookout': ('primary', 'Historic lookout at 5,154 ft with a 360-degree view taking in Rainier, Adams, St Helens and Hood. Drivable to near the top; narrow road.'),
    'DP - Pinto Rock':                ('primary', 'Striking welded-tuff breccia crag at 5,123 ft.'),
    'Pinto Rock Trailhead':           ('skip', 'Trailhead marker; DP - Pinto Rock is the destination.'),
    'Elk Pass':                       ('primary', 'High point on the route between the Cispus and Lewis drainages.'),
    'DP - Mt St Helens':              ('landmark', 'Reference marker for the volcano - view it, do not drive to it.'),
    'Miller Creek Falls':             ('backup', 'Near the Curly Creek pullout.'),
    'Curly Creek Falls Trailhead':    ('skip', 'Trailhead marker; DP - Curly Creek Falls is the destination.'),
    'DP - Curly Creek Falls':         ('primary', 'One of a tiny handful of waterfalls on earth with two natural basalt arches spanning its face. Short walk from the road.'),
    'Rush Creek Falls':               ('backup', 'Same pullout area as Curly Creek Falls.'),
    'Falls Creek Caves Trailhead':    ('skip', 'Trailhead marker; DP - Falls Creek Lava Caves is the destination.'),
    'DP - Falls Creek Lava Caves':    ('hike_candidate', 'LAVA TUBE. No permit, no paid entry — this is not Ape Cave. A large cave system formed by the Big Lava Bed flow ~8,200 years ago. Every person going in needs their own headlamp plus a backup light and spare batteries; the cave is pitch dark, the floor is uneven basalt, and it stays cold year round. Boots, gloves and a helmet or beanie are worth having. Decontaminate kit first if you went in Guler Ice Cave on Wednesday. See the lava caves page for parking and how to find the pits.'),
    'Red Mountain Fire Lookout':      ('hike_candidate', 'Lookout at 4,965 ft on the Indian Heaven boundary; panorama of four volcanoes. ~1.7 mi off route.'),
    'DP - Panther Creek Falls':       ('primary', 'About 130 ft of tiered falls with a built viewing platform a short walk from the road. First and last night are the free pullouts just up this road.'),
}


# Some source waypoints share a generic name. Re-label them by
# (exact GPX name, integer route mile) so the itinerary reads clearly.
POI_RENAME: dict[tuple[str, int], str] = {
    ('Gas Station', 2):   'Fuel - Carson, WA',
    ('Gas Station', 155): 'Fuel - Packwood, WA',
    ('Gas Station', 216): 'Fuel - Randle, WA',
}

# Notes that replace the generic catalog note for a specific instance.
POI_NOTE_OVERRIDE: dict[tuple[str, int], str] = {
    ('Gas Station', 2): 'TOP OFF HERE. Last fuel for 154 route miles until Packwood at mi 156.',
    ('Gas Station', 155): 'First fuel since Carson. Packwood also has food and a store.',
    ('Gas Station', 216): 'Randle. Last fuel before the final 108 miles back to the Gorge.',
}


# Per-POI "spur miles saved if skipped" -- round-trip miles avoided when the
# stop is unchecked in the scheduler.
POI_SPUR_OVERRIDES: dict[str, float] = {
    'DP - High Rock Lookout': 9.0,
    'Red Mountain Fire Lookout': 3.4,
    'DP - Burley Mountain Fire Lookout': 6.0,
    'Interpretive Site: Peterson Prairie': 6.8,
    'DP - Guler Ice Cave': 9.0,
    'Monte Cristo Slab': 3.8,
    'Goat Ridge Lookout': 4.6,
    'DP - Hamilton Buttes': 2.5,
}


# Planned stops that are not in the source GPX. Merged onto the main track in
# load_route() so they get a route mile and off-track distance like any other
# waypoint. Re-parsing the Gaia export does not wipe these.
EXTRA_WAYPOINTS: list[dict[str, Any]] = [
    {
        'name': 'DP - Guler Ice Cave',
        'lat': 45.961424,
        'lon': -121.631396,
        'ele': None,
        'sym': 'cave',
        'desc': (
            'Guler Ice Cave (also called Ice Cave Picnic Area) is a developed 650-foot lava '
            'tube in Gifford Pinchot National Forest, west of Trout Lake, Washington, at about '
            '2,820 feet. The tube formed from lava that issued 12,000 to 18,000 years ago from '
            'the crater now occupied by Lake Wapiki in the Indian Heaven volcanic field.\n\n'
            'The cave was known to Native Americans, who used the cold interior to store '
            'huckleberries, and to early settlers in the Trout Lake valley, who cut ice from it '
            'and hauled it by wagon to towns along the Columbia. Later it was a commercial ice '
            'and produce cellar managed by Christian Guler, the namesake of the nearby community.\n\n'
            'The Forest Service site has picnic tables, fire rings, and a ladder into the tube. '
            'Parking is a $5 day-use fee or a Northwest Forest Pass. Inside: pitch dark, near '
            'freezing year-round, and often icy or muddy underfoot. Ice stalactites and '
            'stalagmites are the draw in spring and early summer; by early September most of '
            'that ice is usually gone, but the lava bridges and the "Crystal Grotto" remain. '
            'Bring a headlamp plus a backup light. Dogs are not allowed in the cave.\n\n'
            'From the driving corridor this is a side trip east of Goose Lake on FR 24 / '
            'Carson-Guler Road, about 4.5 miles off the track at route mile 36 (roughly 9 miles '
            'round trip). The Saturday Falls Creek caves are a different, wilder tube. '
            'Decontaminate boots and kit between the two stops so white-nose fungus is not '
            'carried from one cave to the other.'
        ),
    },
]


# Stops that get checked by default in the itinerary scheduler.
# hike_candidate is False unless the stop is a lava tube, ice cave, or a
# lookout -- those are on the day's plan; other hikes stay opt-in.
DEFAULT_CHECKED_BY_STATUS = {
    'primary':         True,
    'conditional':     True,
    'hike_candidate':  False,
    'backup':          False,
    'landmark':        False,
    'skip':            False,
    'logistics':       False,
    'unclassified':    False,
}


def is_default_checked(name: str, status: str, sym: str = '') -> bool:
    """Whether the scheduler checkbox starts ticked.

    Lava tubes, ice caves and fire lookouts are on the plan even when their
    catalog status is hike_candidate (or backup). Skip and landmark never are.
    """
    if status in ('skip', 'landmark'):
        return False
    n = (name or '').lower()
    s = (sym or '').lower()
    if 'lava cave' in n or 'lava tube' in n or 'ice cave' in n:
        return True
    if 'lookout' in n or s == 'fire-lookout':
        return True
    return DEFAULT_CHECKED_BY_STATUS.get(status, False)

# Statuses that contribute no driving detour and no stop time.
ZERO_TIME_STATUSES = {'landmark'}


def default_minutes(name: str, sym: str, status: str, note: str) -> int:
    """Stop-time default seeds for the itinerary scheduler inputs."""
    n = (name or '').lower()
    s = (sym or '').lower()

    if status == 'landmark':
        return 0

    # Named hikes and activities, longest first.
    if 'high rock lookout' in n:            return 150
    if 'hamilton buttes' in n:              return 120
    if 'falls creek lava caves' in n:       return 90
    if 'guler ice cave' in n:               return 45
    if 'council bluff' in n:                return 75
    if 'steamboat mountain' in n:           return 60
    if 'bishop falls' in n:                 return 60
    if 'walupt creek falls' in n:           return 60
    if 'red mountain fire lookout' in n:    return 45
    if 'burley mountain' in n:              return 45
    if 'layser cave' in n:                  return 30
    if 'panther creek falls' in n:          return 30
    if 'takh takh' in n:                    return 30
    if 'langfield falls' in n:              return 25
    if 'curly creek falls' in n:            return 25
    if 'berry fields' in n:                 return 25
    if 'takhlakh lake' in n:                return 30
    if 'basket tree' in n:                  return 20
    if 'big lava bed' in n:                 return 20
    if 'pinto rock' in n:                   return 20
    if 'camp creek falls' in n:             return 20
    if 'rush creek falls' in n:             return 20
    if 'miller creek falls' in n:           return 15
    if 'babyshoe pass' in n:                return 10
    if 'elk pass' in n:                     return 10
    if 'triangle pass' in n:                return 5
    if 'high bridge' in n:                  return 10
    if 'columbia river gorge' in n:         return 15
    if n.startswith('fuel - '):             return 25

    # Fall back on the GPX symbol.
    if s == 'fuel-24':                      return 25
    if s == 'cave':                         return 45
    if s == 'fire-lookout':                 return 45
    if s == 'waterfall':                    return 25
    if s == 'lake':                         return 20
    if s in ('binoculars', 'attraction', 'information'): return 15
    if s in ('cliff', 'peak', 'volcano', 'bridge'):      return 15
    if s in ('water', 'marsh'):             return 10
    if s == 'building-24':                  return 15
    return 20


# ---------------------------------------------------------------------------
# Route loading + geometry helpers
# ---------------------------------------------------------------------------
def _haversine_m(a, b):
    R = 6371000.0
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    dlat = la2 - la1
    dlon = lo2 - lo1
    s = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(s))


def load_highway_tracks(planning_dir: pathlib.Path) -> dict[str, Any]:
    """Load optional OSRM polylines for the highway travel legs."""
    p = planning_dir / 'highway_tracks.json'
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding='utf-8'))


def _nearest_on_track(
    pt: tuple[float, float], pts: list, cum_mi: list[float]
) -> tuple[int, float, float]:
    """Return (index, dist_m, mile) of the nearest main-track point."""
    best_i = 0
    best_d = float('inf')
    for i, tp in enumerate(pts):
        d = _haversine_m(pt, tp)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i, best_d, cum_mi[best_i]


def _merge_extra_waypoints(route: dict[str, Any]) -> None:
    """Project EXTRA_WAYPOINTS onto the main track and insert them in mile order."""
    pts = route['main_points']
    cum_mi = route['cum_mi']
    ordered = route['ordered']
    by_name = route['by_name']
    existing = {w.get('name') for w in ordered}
    for extra in EXTRA_WAYPOINTS:
        nm = extra.get('name') or ''
        if nm in existing:
            continue
        i, d_m, mi = _nearest_on_track((extra['lat'], extra['lon']), pts, cum_mi)
        w = {
            **extra,
            'mile': round(mi, 3),
            'track_index': i,
            'dist_to_track_m': round(d_m, 1),
        }
        ordered.append(w)
        by_name.setdefault(nm, []).append(w)
        existing.add(nm)
    ordered.sort(key=lambda x: x.get('mile') or 0)


def load_route(plan_dir: pathlib.Path) -> dict[str, Any]:
    """Load route_analysis.json + route_tracks.json and precompute cum_mi."""
    analysis = json.loads((plan_dir / 'route_analysis.json').read_text(encoding='utf-8'))
    tracks = json.loads((plan_dir / 'route_tracks.json').read_text(encoding='utf-8'))

    main_track = next((t for t in tracks if t['name'] == cfg.MAIN_TRACK_NAME), None)
    if main_track is None:
        raise SystemExit(
            f'Main track {cfg.MAIN_TRACK_NAME!r} not in route_tracks.json. '
            f'Available: {[t["name"] for t in tracks]}'
        )

    pts = main_track['points']
    cum_mi = [0.0]
    for i in range(1, len(pts)):
        cum_mi.append(cum_mi[-1] + _haversine_m(pts[i - 1], pts[i]) / 1609.344)

    ordered = list(analysis['waypoints_ordered'])
    by_name: dict[str, list[dict]] = {}
    for w in ordered:
        by_name.setdefault(w.get('name') or '', []).append(w)

    route = {
        'main_track': main_track,
        'main_points': pts,
        'cum_mi': cum_mi,
        'ordered': ordered,
        'by_name': by_name,
        'total_mi': analysis['track_miles'],
    }
    _merge_extra_waypoints(route)
    return route


def slice_track(route: dict[str, Any], mi_lo: float | None, mi_hi: float | None) -> list[list[float]]:
    """Return main-track points whose cumulative-mile values fall in [mi_lo, mi_hi]."""
    if mi_lo is None or mi_hi is None:
        return []
    pts = route['main_points']
    cum_mi = route['cum_mi']
    i_lo = next((i for i, m in enumerate(cum_mi) if m >= mi_lo), 0)
    i_hi = next((i for i, m in enumerate(cum_mi) if m >= mi_hi), len(cum_mi) - 1)
    return pts[i_lo:i_hi + 1]


def build_day_track(route: dict[str, Any], segments: list[dict]) -> list[list[float]]:
    """Concatenate track slices (optionally reversed) into one day polyline."""
    out: list[list[float]] = []
    for seg in segments:
        sliced = slice_track(route, seg.get('mi_lo'), seg.get('mi_hi'))
        if seg.get('reverse'):
            sliced = list(reversed(sliced))
        if out and sliced and tuple(sliced[0]) == tuple(out[-1]):
            sliced = sliced[1:]
        out.extend(sliced)
    return out


# ---------------------------------------------------------------------------
# POI assembly
# ---------------------------------------------------------------------------
def _waypoint_to_poi(w: dict, route: dict, day_mile: float,
                     status_info: tuple[str, str] | None) -> dict | None:
    """Convert a raw waypoint into the POI dict consumed by HTML/GPX builders."""
    nm = w.get('name') or ''
    sym = w.get('sym') or ''
    if status_info is None:
        # Campsites are handled by the CAMPSITES table, not as POIs.
        if sym == 'campsite-24':
            return None
        if sym in ('fuel-24', 'city-24', 'toilets-24'):
            status, note = 'logistics', sym
        else:
            status, note = 'unclassified', ''
    else:
        status, note = status_info

    raw_mile_key = int(w.get('mile') or 0)
    display_name = POI_RENAME.get((nm, raw_mile_key), nm)
    note = POI_NOTE_OVERRIDE.get((nm, raw_mile_key), note)

    off_m = round(w.get('dist_to_track_m', 0), 1)
    spur = POI_SPUR_OVERRIDES.get(nm, 0.0)
    if status in ZERO_TIME_STATUSES:
        # Never let the scheduler route the group to a distant summit marker.
        off_m = 0.0
        spur = 0.0

    return {
        'name': display_name,
        'gpx_name': nm,
        'lat': w['lat'], 'lon': w['lon'], 'ele': w.get('ele'),
        'mile': round(day_mile, 2),
        'dist_to_track_m': off_m,
        'true_off_track_m': round(w.get('dist_to_track_m', 0), 1),
        'sym': w.get('sym'),
        'status': status,
        'note': note,
        'desc': (w.get('desc') or '').strip(),
        'spur_mi': spur,
    }


def pois_for_segments(
    route: dict[str, Any],
    segments: list[dict],
    poi_status: dict[str, tuple[str, str]],
    suppress_names: set[str] | None = None,
    extra_status: dict[str, tuple[str, str]] | None = None,
    use_day_mi: bool = True,
) -> list[dict]:
    """Collect POIs covered by a list of mile segments, in driven order.

    When ``use_day_mi`` is True each POI's ``mile`` is recalculated as
    mile-along-the-day starting at 0, so the scheduler's ``mile - prevMile`` leg
    math stays correct even for reversed or multi-segment days.
    """
    suppress_names = suppress_names or set()
    extra_status = extra_status or {}
    out: list[dict] = []
    seen: set[tuple[str, float]] = set()
    running_day_mi = 0.0
    for seg in segments:
        mi_lo = seg.get('mi_lo')
        mi_hi = seg.get('mi_hi')
        if mi_lo is None or mi_hi is None:
            continue
        seg_len = max(0.0, mi_hi - mi_lo)
        reverse = bool(seg.get('reverse'))
        in_win = [w for w in route['ordered']
                  if w.get('mile') is not None and mi_lo <= w['mile'] < mi_hi]
        in_win.sort(key=lambda w: -(w['mile']) if reverse else (w['mile']))
        for w in in_win:
            nm = w.get('name') or ''
            if nm in suppress_names:
                continue
            raw_mi = w['mile']
            if use_day_mi:
                off = (mi_hi - raw_mi) if reverse else (raw_mi - mi_lo)
                emit_mi = running_day_mi + off
            else:
                emit_mi = raw_mi
            key = (nm, round(emit_mi, 2))
            if key in seen:
                continue
            seen.add(key)
            status_info = extra_status.get(nm) or poi_status.get(nm)
            poi = _waypoint_to_poi(w, route, emit_mi, status_info)
            if poi is not None and poi['status'] != 'skip':
                out.append(poi)
        running_day_mi += seg_len
    return out


# ---------------------------------------------------------------------------
# Day payload assembly
# ---------------------------------------------------------------------------
def _resolve_camp(camp_spec: Any, camp_data: dict[str, Any] | None) -> Any:
    """Expand ``{'inherit': key}`` to the referenced camp dict."""
    if isinstance(camp_spec, dict) and 'inherit' in camp_spec:
        ref = camp_spec['inherit']
        if camp_data and ref in camp_data:
            return camp_data[ref]
    return camp_spec


def build_payload(
    *,
    days_spec: list[dict],
    camp_data: dict[str, Any],
    schedule_defaults: dict[str, dict],
    route: dict[str, Any],
    trip_meta: dict[str, Any],
    group_counts: dict[str, Any],
    fuel_plan: dict[str, Any],
    realtime_links: list[dict[str, str]],
    live_fire_overlays: list[dict[str, Any]] | None = None,
    generated_at: str,
    suppress_names: set[str] | None = None,
    poi_status: dict[str, tuple[str, str]] | None = None,
    intro_html: str | None = None,
) -> dict[str, Any]:
    """Build a full trip-data payload from a days-spec + camp + schedule set.

    ``days_spec`` items support:
      * ``mi_lo`` / ``mi_hi``: mile window along the main track.
      * ``track_segments``: list of ``{mi_lo, mi_hi, reverse}``; takes
        precedence over the scalar window.
      * ``synthetic_pois`` / ``synthetic_track_points``: injected POIs or
        lat/lon polylines for highway travel legs that aren't on the route.
    """
    poi_status = poi_status or POI_STATUS
    suppress_names = suppress_names or set()

    out_days: list[dict] = []
    for d in days_spec:
        d_copy = {k: v for k, v in d.items() if k not in (
            'track_segments', 'poi_extra_status', 'synthetic_pois', 'synthetic_track_points',
        )}

        segments = d.get('track_segments')
        if not segments and d.get('mi_lo') is not None and d.get('mi_hi') is not None:
            segments = [{'mi_lo': d['mi_lo'], 'mi_hi': d['mi_hi'], 'reverse': False}]
        segments = segments or []

        # POIs.
        if d.get('synthetic_pois') is not None:
            d_copy['pois'] = [dict(p) for p in d['synthetic_pois']]
        else:
            d_copy['pois'] = pois_for_segments(
                route, segments, poi_status,
                suppress_names=suppress_names,
                extra_status=d.get('poi_extra_status'),
            )

        # Track polyline for this day.
        synth = d.get('synthetic_track_points')
        if synth:
            d_copy['track_points'] = [[float(p[0]), float(p[1])] for p in synth]
        elif segments:
            d_copy['track_points'] = build_day_track(route, segments)
        else:
            d_copy['track_points'] = []

        # Extra polyline drawn alongside the day's main line (e.g. the drive
        # home on a day that also finishes a stretch of route).
        extra = d.get('extra_track_points')
        if extra:
            d_copy['extra_track_points'] = [[float(p[0]), float(p[1])] for p in extra]

        # Camp selection.
        camp_key = d.get('camp_key', d['id'])
        d_copy['camps'] = _resolve_camp(camp_data.get(camp_key), camp_data) or None

        # Schedule annotations (only for days that opt into it).
        sched = schedule_defaults.get(d['id'])
        if sched and d_copy['track_points']:
            first_pt = d_copy['track_points'][0]
            d_copy['schedule'] = {
                'break_camp_time': sched['break_camp'],
                'moving_mph':      sched['moving_mph'],
                'start_lat':       first_pt[0],
                'start_lon':       first_pt[1],
                'mi_lo':           0.0,
            }
            for p in d_copy['pois']:
                p['default_minutes'] = default_minutes(
                    p['name'], p.get('sym'), p['status'], p.get('note'))
                p['default_checked'] = is_default_checked(
                    p['name'], p['status'], p.get('sym') or '')

        out_days.append(d_copy)

    payload: dict[str, Any] = {
        'trip': trip_meta,
        'group_counts': group_counts,
        'days': out_days,
        'fuel': fuel_plan,
        'realtime_links': realtime_links,
        'generated_at': generated_at,
    }
    if live_fire_overlays:
        payload['live_fire_overlays'] = live_fire_overlays
    if intro_html:
        payload['intro_html'] = intro_html
    return payload


def write_payload(payload: dict[str, Any], out_path: pathlib.Path) -> None:
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def print_payload_summary(payload: dict[str, Any], label: str) -> None:
    days = payload.get('days') or []
    print(f'{label}: {len(days)} days')
    for d in days:
        pois = d.get('pois') or []
        tp = d.get('track_points') or []
        by_status: dict[str, int] = {}
        for p in pois:
            by_status[p['status']] = by_status.get(p['status'], 0) + 1
        bits = ' '.join(f'{k}={v}' for k, v in sorted(by_status.items()))
        print(f"  {d['id']:18s} {d['label']:46s} pois={len(pois):3d} track={len(tp):5d}  {bits}")
