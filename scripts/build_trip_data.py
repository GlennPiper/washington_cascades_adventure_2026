"""Build the consolidated trip_data.json consumed by the HTML and GPX generators.

Inputs:
  planning/route_analysis.json  (waypoints ordered by mile, projected on track)
  planning/route_tracks.json    (raw polylines by track name)
  planning/highway_tracks.json  (optional OSRM polylines for travel days)

Output:
  planning/trip_data.json

Trip identity (title, dates, contacts, bbox) lives in ``trip_config.py``.
The POI catalog and scheduler heuristics live in ``trip_core.py``.
This file owns the day split, the campground plan, the fuel plan, and the
live-conditions link list.
"""
from __future__ import annotations
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import trip_config as cfg  # noqa: E402
from trip_core import (  # noqa: E402
    build_payload,
    load_highway_tracks,
    load_route,
    print_payload_summary,
    write_payload,
)

BASE = _SCRIPTS.parent
PLAN = BASE / 'planning'


# ---------------------------------------------------------------------------
# Day split
# ---------------------------------------------------------------------------
# Mile windows along the 324.8-mile main track. The split is driven by where
# established campgrounds actually sit: there is a dense cluster from mile 34
# to 141, then an 85-mile gap with nothing developed until North Fork at 226,
# which forces days 3 and 4 to be the long ones.
DAYS = [
    {
        'id': 'sep8_travel',
        'label': 'Sep 8 (Tue) - Travel to the Gorge',
        'date_iso': '2026-09-08',
        'title': 'Nampa, ID -> Carson, WA (Panther Creek camp)',
        'type': 'travel',
        'descr': (
            'Meet at the Sinclair Stinker Station, 1902 N Franklin Blvd, Nampa at 8:00 AM MDT; '
            'roll out by 8:15. I-84 west through Oregon, then up the Columbia River Gorge and '
            'across into Washington. About 376 miles and 7 hours of moving time, so plan on '
            '8.5 to 9 hours with fuel and food stops for a six-vehicle group. You gain an hour '
            'crossing into Pacific time, which puts arrival in camp around 3:30 to 4:30 PM PDT. '
            'Camp at Panther Creek, roughly 11 miles up Wind River Road from Carson, and start '
            'the loop from mile 0 in the morning.'
        ),
        'mi_lo': None,
        'mi_hi': None,
        'miles': 376,
        'driving_hours_est': 7.1,
    },
    {
        'id': 'day1_cascades',
        'label': 'Sep 9 (Wed) - Day 1: Carson -> Takhlakh Lake',
        'date_iso': '2026-09-09',
        'title': 'Day 1: Columbia Gorge -> Indian Heaven -> Takhlakh Lake',
        'type': 'overland',
        'descr': (
            'The scenic-payoff day. Top off in Carson because there is no fuel for the next 154 '
            'route miles. Climb Wind River Road past the High Bridge, skirt the Big Lava Bed, '
            'and work north through Goose Lake and the Forlorn Lakes into the Indian Heaven '
            'country and the Sawtooth Berry Fields. Huckleberries should still be on in early '
            'September. Over Babyshoe Pass and finish at Takhlakh Lake, where Mount Adams '
            'reflects in the water - the signature view of the whole route.'
        ),
        'mi_lo': 0.0,
        'mi_hi': 84.5,
        'miles': 85,
        'driving_hours_est': 6.0,
    },
    {
        'id': 'day2_cascades',
        'label': 'Sep 10 (Thu) - Day 2: Takhlakh -> Walupt Lake',
        'date_iso': '2026-09-10',
        'title': 'Day 2: Takh Takh lava -> Upper Cispus -> Walupt Lake',
        'type': 'overland',
        'descr': (
            'The short day, and deliberately so: 49 route miles leaves real time for the '
            'waterfalls and the Goat Rocks edge. Start on the Takh Takh lava flow, drop into '
            'the Upper Cispus, and pass Hamilton Buttes and Bishop Falls. Finish at Walupt '
            'Lake, the deepest lake in the county and the trailhead gateway to the Goat Rocks '
            'Wilderness. The Walupt Lake access road is long and rough - budget for it.'
        ),
        'mi_lo': 84.5,
        'mi_hi': 133.5,
        'miles': 49,
        'driving_hours_est': 4.5,
    },
    {
        'id': 'day3_cascades',
        'label': 'Sep 11 (Fri) - Day 3: Walupt -> North Fork',
        'date_iso': '2026-09-11',
        'title': 'Day 3: Packwood fuel -> High Rock Lookout -> Randle -> North Fork',
        'type': 'overland',
        'descr': (
            'The longest day at 93 miles, but a good share of it is paved US 12, so it moves '
            'faster than the number suggests. Fuel at Packwood around mile 156 - the first '
            'pump since Carson. The centrepiece is High Rock Lookout: about 3 miles round trip '
            'to a historic lookout on a cliff edge with Mount Rainier only 13 air miles away. '
            'Fuel again at Randle, then Layser Cave and Camp Creek Falls on the way into camp '
            'on the Cispus.'
        ),
        'mi_lo': 133.5,
        'mi_hi': 226.5,
        'miles': 93,
        'driving_hours_est': 7.0,
    },
    {
        'id': 'day4_cascades',
        'label': 'Sep 12 (Sat) - Day 4: North Fork -> Panther Creek',
        'date_iso': '2026-09-12',
        'title': 'Day 4: Burley Mountain -> Elk Pass -> lava caves -> Panther Creek',
        'type': 'overland',
        'descr': (
            'The volcano-and-lava day, 82 miles. Burley Mountain Lookout takes in Rainier, '
            'Adams, St Helens and Hood from one spot. South over Elk Pass with Mount St Helens '
            'filling the window, then down the Lewis River past Curly Creek Falls and its twin '
            'natural basalt arches. Late in the day, the Falls Creek Lava Caves: a genuine lava '
            'tube from the Big Lava Bed eruption. Everyone going underground needs their own '
            'headlamp plus a backup. Finish at Panther Creek Falls and camp where the trip '
            'started.'
        ),
        'mi_lo': 226.5,
        'mi_hi': 308.5,
        'miles': 82,
        'driving_hours_est': 6.5,
    },
    {
        'id': 'sep13_return',
        'label': 'Sep 13 (Sun) - Close the loop + drive home',
        'date_iso': '2026-09-13',
        'title': 'Panther Creek -> Triangle Pass (loop close) -> Nampa, ID',
        'type': 'travel',
        'descr': (
            'Two options. Break camp early and run the final 16 route miles from Panther Creek '
            'down to Triangle Pass to formally close the loop, then drop into the Gorge and '
            'head east - that adds roughly an hour and a half on top of a 368-mile, near-7-hour '
            'drive, so leaving camp by 7:00 AM matters. Or skip the last segment, drive straight '
            'out to Carson, and be home earlier. Decide the night before based on how everyone '
            'feels.'
        ),
        'mi_lo': 308.5,
        'mi_hi': 324.81,
        'miles': 384,
        'driving_hours_est': 8.0,
    },
]


# ---------------------------------------------------------------------------
# Campground plan
# ---------------------------------------------------------------------------
# Availability figures are a snapshot taken 2026-08-31 from Recreation.gov for
# the relevant night. NOTHING IS BOOKED. Friday Sep 11 and Saturday Sep 12 are
# the scarce nights because they fall on a weekend.
#
# For six vehicles: ordinary Gifford Pinchot sites hold one or two rigs, so the
# group needs either a group site or several adjacent numbered sites.
_RESGOV = 'https://www.recreation.gov/camping/campgrounds/'

CAMPSITES = {
    'sep8_travel': {
        'primary': {
            'name': 'Panther Creek Campground (Recreation.gov 233103)',
            'lat': 45.81972, 'lon': -121.87972,
            'status': 'primary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 9 of 33 sites are first-come',
            'facilities': 'Vault toilets, potable water, tables, fire rings. No hookups.',
            'notes': ('NOT BOOKED. 19 of 33 sites showed available for Sep 8 as of 2026-08-31. '
                      'Forest campground about 11 miles up Wind River Rd from Carson, so it is a '
                      'short backtrack to mile 0 in the morning. Same camp as the final night, '
                      'which means the group only has to learn one site. Reserve several adjacent '
                      'numbered sites for six rigs.'),
            'access': 'WA-14 to Carson, north on Wind River Rd, right on Panther Creek Rd (FS 65).',
            'reserve_url': _RESGOV + '233103',
        },
        'secondary': {
            'name': 'Home Valley Campground (Skamania County park)',
            'lat': 45.70870, 'lon': -121.77348,
            'status': 'secondary',
            'kind': 'developed_county',
            'cost': 'County park fee',
            'facilities': 'Showers, potable water, toilets - the only showers near the route.',
            'notes': ('Booked through Skamania County, not Recreation.gov. Right on the Columbia '
                      'and only 2.9 miles from route mile 0, and it is the first campground you '
                      'reach driving in from the east. Trade-off: it sits between WA-14 and the '
                      'BNSF main line, so expect highway and train noise.'),
            'access': 'Directly off WA-14 at Home Valley, east of Carson.',
        },
        'tertiary': [
            {
                'name': 'Moss Creek Campground',
                'lat': 45.79501, 'lon': -121.63444,
                'status': 'tertiary',
                'kind': 'developed_fcfs',
                'cost': 'Per-site fee',
                'facilities': 'Vault toilets, water',
                'notes': 'First-come. On the Little White Salmon, about 20 route miles in - useful only if the group decides to bank miles on arrival evening.',
                'access': 'FS 18 north from Willard.',
            },
            {
                'name': 'Big Cedars County Park',
                'lat': 45.80154, 'lon': -121.64364,
                'status': 'tertiary',
                'kind': 'developed_county',
                'cost': 'County park fee',
                'facilities': 'Toilets, water',
                'notes': 'Skamania County site adjacent to Moss Creek; same purpose as a mile-banking option.',
                'access': 'FS 18 north from Willard.',
            },
        ],
    },
    'day1_cascades': {
        'primary': {
            'name': 'Takhlakh Lake Campground (Recreation.gov 232861)',
            'lat': 46.28083, 'lon': -121.59861,
            'status': 'primary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 18 of 54 sites are first-come',
            'facilities': 'Vault toilets, potable water, tables, fire rings. No hookups. Non-motorised boating only.',
            'notes': ('NOT BOOKED, AND THIS IS THE ONE TO GRAB. 22 of 54 sites showed available '
                      'for Sep 9 as of 2026-08-31, but ZERO for Fri Sep 11 and Sat Sep 12 - which '
                      'is exactly why Day 1 ends here on a Wednesday. Mount Adams reflected in the '
                      'lake is the signature view of the route. Sites in the 30s and 40s were the '
                      'most open; book adjacent ones for six rigs.'),
            'access': 'FS 23 over Babyshoe Pass, then FS 2329. Paved most of the way with a gravel stretch over the pass.',
            'reserve_url': _RESGOV + '232861',
        },
        'secondary': [
            {
                'name': 'Council Lake Campground',
                'lat': 46.26327, 'lon': -121.63178,
                'status': 'secondary',
                'kind': 'primitive_fcfs',
                'cost': 'Free or low fee',
                'facilities': 'Vault toilet. No potable water.',
                'notes': 'First-come, not reservable, roughly 5 route miles before Takhlakh. Small and rustic - good fallback for part of the group, not all six rigs.',
                'access': 'Short rough spur off FS 2334.',
            },
            {
                'name': 'Olallie Lake Campground',
                'lat': 46.28868, 'lon': -121.61949,
                'status': 'secondary',
                'kind': 'primitive_fcfs',
                'cost': 'Free or low fee',
                'facilities': 'Vault toilet. No potable water.',
                'notes': 'First-come. Very small, in the same Midway High Lakes cluster as Takhlakh.',
                'access': 'Spur off FS 2329.',
            },
        ],
        'tertiary': [
            {
                'name': 'Horseshoe Lake Campground',
                'lat': 46.30978, 'lon': -121.56663,
                'status': 'tertiary',
                'kind': 'primitive_fcfs',
                'cost': 'Free or low fee',
                'facilities': 'Vault toilet. No potable water.',
                'notes': 'First-come, just under a mile off route past Takhlakh.',
                'access': 'FS 2329 spur.',
            },
            {
                'name': 'Chain of Lakes Campground',
                'lat': 46.29310, 'lon': -121.59633,
                'status': 'tertiary',
                'kind': 'primitive_fcfs',
                'cost': 'Free or low fee',
                'facilities': 'Vault toilet. No potable water.',
                'notes': 'First-come, rough access road. Last-resort spillover for the High Lakes area.',
                'access': 'Rough spur off FS 2329.',
            },
        ],
    },
    'day2_cascades': {
        'primary': {
            'name': 'Walupt Lake Campground (Recreation.gov 232860)',
            'lat': 46.42306, 'lon': -121.47361,
            'status': 'primary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 14 of 42 sites are first-come',
            'facilities': 'Vault toilets, potable water, boat launch. No hookups.',
            'notes': ('NOT BOOKED. 7 of 42 sites showed available for Sep 10 as of 2026-08-31 - '
                      'thinner than Takhlakh, so this is the second priority to reserve. Only 1 '
                      'site was open for Fri Sep 11, so the Thursday timing matters. Goat Rocks '
                      'trailheads leave from the campground. The access road in is long and rough.'),
            'access': 'FS 21 then FS 2160 east - roughly 16 miles of gravel off the main route.',
            'reserve_url': _RESGOV + '232860',
        },
        'secondary': {
            'name': 'Chambers Lake Campground',
            'lat': 46.46549, 'lon': -121.53183,
            'status': 'secondary',
            'kind': 'primitive_fcfs',
            'cost': 'Free or low fee',
            'facilities': 'Vault toilet. No potable water.',
            'notes': ('First-come and not on Recreation.gov, so availability cannot be checked in '
                      'advance. About 8 route miles past Walupt near the Goat Rocks boundary. '
                      'Reasonable Plan B if Walupt is full on arrival.'),
            'access': 'FS 21 spur north of the Walupt junction.',
        },
        'tertiary': [
            {
                'name': 'Adams Fork Campground (Recreation.gov 232857)',
                'lat': 46.33889, 'lon': -121.64694,
                'status': 'tertiary',
                'kind': 'developed_reservable',
                'cost': 'Per-site fee; 7 of 23 sites are first-come',
                'facilities': 'Vault toilets, tables, fire rings. No potable water.',
                'notes': ('16 of 23 sites showed available for Sep 10. Sits at route mile 99.6, so '
                          'choosing it shortens Day 2 to 15 miles and lengthens Day 3 to 127 - use '
                          'it only if the group wants an easy Thursday or Walupt falls through.'),
                'access': 'On FS 21 beside the Cispus River.',
                'reserve_url': _RESGOV + '232857',
            },
            {
                'name': 'Cat Creek Campground',
                'lat': 46.34855, 'lon': -121.62496,
                'status': 'tertiary',
                'kind': 'primitive_fcfs',
                'cost': 'Free',
                'facilities': 'Vault toilet. No potable water.',
                'notes': 'First-come only, very small. Route mile 101. Overflow for Adams Fork.',
                'access': 'FS 2160 just east of Adams Fork.',
            },
        ],
    },
    'day3_cascades': {
        'primary': {
            'name': 'North Fork Elk Group Camp (Recreation.gov 232898)',
            'lat': 46.45250, 'lon': -121.78889,
            'status': 'primary',
            'kind': 'developed_group_reservable',
            'cost': 'Single group-site fee for the whole party',
            'facilities': 'Vault toilets, potable water, group shelter area, tables, fire rings.',
            'notes': ('NOT BOOKED, AND THE MOST TIME-SENSITIVE RESERVATION OF THE TRIP. This is a '
                      'single reservable group site, which is what six vehicles actually want, and '
                      'as of 2026-08-31 it was open on both Fri Sep 11 and Sat Sep 12 - the two '
                      'nights when nearly everything else in the forest is booked. One booking '
                      'covers the whole group. If it goes, Tower Rock is the fallback.'),
            'access': 'FS 23 south from Randle along the Cispus, near North Fork Campground.',
            'reserve_url': _RESGOV + '232898',
        },
        'secondary': {
            'name': 'Tower Rock Campground (Recreation.gov 232855)',
            'lat': 46.44500, 'lon': -121.86806,
            'status': 'secondary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 6 of 20 sites are first-come',
            'facilities': 'Vault toilets, potable water, tables, fire rings.',
            'notes': ('The best weekend availability found anywhere on the route: 10 of 20 sites '
                      'open for Fri Sep 11 and 8 for Sat Sep 12 as of 2026-08-31. Route mile 228.6, '
                      'about 2 miles past North Fork. Book several adjacent sites if the Elk group '
                      'site is gone.'),
            'access': 'FS 23 / FS 28 along the Cispus, south of Randle.',
            'reserve_url': _RESGOV + '232855',
        },
        'tertiary': [
            {
                'name': 'North Fork Bear Group Camp (Recreation.gov 232896)',
                'lat': 46.45083, 'lon': -121.78778,
                'status': 'tertiary',
                'kind': 'developed_group_reservable',
                'cost': 'Single group-site fee',
                'facilities': 'Same complex as Elk Group.',
                'notes': ('The other group site at North Fork. It was open Sep 8 through 10 but '
                          'ALREADY TAKEN for Fri Sep 11 and Sat Sep 12, so it does not work for '
                          'this itinerary unless the day split changes.'),
                'access': 'Same as Elk Group.',
                'reserve_url': _RESGOV + '232896',
            },
            {
                # Recreation.gov reports this facility at the same coordinate as
                # Bear Group Camp; use the source GPX campground waypoint instead
                # so the two don't land on top of each other on the map and in GPX.
                'name': 'North Fork Campground (Recreation.gov 232852)',
                'lat': 46.45109, 'lon': -121.78760,
                'status': 'tertiary',
                'kind': 'developed_reservable',
                'cost': 'Per-site fee; 7 of 19 sites are first-come',
                'facilities': 'Vault toilets, potable water.',
                'notes': ('Only 1 site open for Fri Sep 11 and none for Sat Sep 12 as of 2026-08-31 '
                          '- not viable for six rigs on the weekend, but listed because the '
                          'first-come sites could still absorb one or two vehicles.'),
                'access': 'FS 23 south from Randle.',
                'reserve_url': _RESGOV + '232852',
            },
        ],
    },
    'day4_cascades': {
        'primary': {
            'name': 'Panther Creek Campground (Recreation.gov 233103)',
            'lat': 45.81972, 'lon': -121.87972,
            'status': 'primary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 9 of 33 sites are first-come',
            'facilities': 'Vault toilets, potable water, tables, fire rings.',
            'notes': ('NOT BOOKED. Only 5 of 33 sites showed available for Sat Sep 12 as of '
                      '2026-08-31, so book this at the same time as the first night. Route mile '
                      '308.4, right after Panther Creek Falls, and it leaves only 16 miles of loop '
                      'to close on Sunday morning.'),
            'access': 'Panther Creek Rd (FS 65) off Wind River Rd.',
            'reserve_url': _RESGOV + '233103',
        },
        'secondary': {
            'name': 'Crest Camp',
            'lat': 45.90889, 'lon': -121.80103,
            'status': 'secondary',
            'kind': 'primitive_fcfs',
            'cost': 'Free',
            'facilities': 'None. No water, no toilet.',
            'notes': 'Small primitive site at route mile 302.7 near the Pacific Crest Trail crossing. First-come. Fits a couple of rigs at most - a bail-out, not a plan.',
            'access': 'FS 60 near the PCT trailhead.',
        },
        'tertiary': {
            'name': 'Home Valley Campground (Skamania County park)',
            'lat': 45.70870, 'lon': -121.77348,
            'status': 'tertiary',
            'kind': 'developed_county',
            'cost': 'County park fee',
            'facilities': 'Showers, potable water, toilets.',
            'notes': ('Worth considering deliberately rather than as a fallback: finishing the '
                      'full loop to Triangle Pass on Saturday and dropping to Home Valley makes '
                      'Saturday about 117 miles, but it means hot showers before the drive home '
                      'and nothing left to do on Sunday but leave.'),
            'access': 'Directly off WA-14 at Home Valley.',
        },
    },
}


# ---------------------------------------------------------------------------
# Per-day scheduling defaults (only route days get the on-page scheduler)
# ---------------------------------------------------------------------------
# break_camp is local time; moving_mph is pure driving speed with no stops
# folded in. Gifford Pinchot forest roads run slower than desert two-track:
# 20-25 mph on graded gravel, less on the rough spurs, faster on the paved
# US 12 stretch that dominates Day 3.
SCHEDULE_DEFAULTS = {
    'day1_cascades': {'break_camp': '08:00', 'moving_mph': 22},
    'day2_cascades': {'break_camp': '08:30', 'moving_mph': 20},
    'day3_cascades': {'break_camp': '07:30', 'moving_mph': 28},
    'day4_cascades': {'break_camp': '07:30', 'moving_mph': 22},
}


# ---------------------------------------------------------------------------
# Fuel plan
# ---------------------------------------------------------------------------
FUEL_PLAN_SUMMARY = {
    'stations': [
        {'name': 'Carson, WA (route mile 2)', 'lat': 45.74106, 'lon': -121.82137,
         'role': 'MANDATORY top-off. Last fuel for 154 route miles.',
         'brands': 'Small-town station on Wind River Rd; also a store. Verify hours - do not arrive at 9 PM expecting to fuel.'},
        {'name': 'Stevenson, WA (near the start, off route)', 'lat': 45.69560, 'lon': -121.88500,
         'role': 'Backup for Carson, ~7 mi west on WA-14',
         'brands': 'Larger selection of stations and a full grocery store.'},
        {'name': 'Trout Lake, WA (off-route detour)', 'lat': 45.99760, 'lon': -121.52640,
         'role': 'Optional mid-Day-1 insurance, roughly 12 miles southeast of the route via WA-141',
         'brands': 'Single small station plus a store; limited hours. Not in the route GPX. Worth it only if someone is running low before Babyshoe Pass.'},
        {'name': 'Packwood, WA (route mile 156)', 'lat': 46.60421, 'lon': -121.67279,
         'role': 'First fuel since Carson. Day 3 refuel point.',
         'brands': 'Multiple stations on US 12, plus food, store and cell service.'},
        {'name': 'Randle, WA (route mile 217)', 'lat': 46.53564, 'lon': -121.95699,
         'role': 'Last fuel before the final 108 miles back to the Gorge',
         'brands': 'Station and store on US 12; Cowlitz Valley Ranger Station is here.'},
        {'name': 'Morton, WA (off route, west on US 12)', 'lat': 46.55900, 'lon': -122.27600,
         'role': 'Backup if Randle is closed; also the nearest hospital',
         'brands': 'Several stations. About 20 miles west of Randle.'},
    ],
    'critical_gaps': [
        {'from_mi': 2, 'to_mi': 156, 'gap_mi': 154,
         'label': 'Carson to Packwood',
         'note': ('The one that matters. 154 miles of mostly forest road with no fuel. At a '
                  'degraded 13 mpg that is about 12 gallons, which most rigs handle on one tank - '
                  'but anything with a small tank, a heavy foot, or a roof rack should carry a '
                  'jerry can. Trout Lake is the only bail-out and it is a 24-mile round trip '
                  'detour off Day 1.')},
        {'from_mi': 217, 'to_mi': 325, 'gap_mi': 108,
         'label': 'Randle to the Gorge',
         'note': 'Fill at Randle. The last 108 miles cross Elk Pass and the Lewis River country with nothing open.'},
    ],
    'surface_breakdown': {
        'paved_hwy_mi': 95,
        'graded_gravel_mi': 175,
        'rough_2track_mi': 45,
        'technical_mi': 10,
        'total_mi': 325,
    },
    'mpg_factors': {
        'paved_hwy_65mph': 1.00,
        'paved_local': 0.95,
        'graded_gravel': 0.82,
        'rough_2track': 0.65,
        'technical_low_range': 0.50,
    },
    'notes': [
        'Two full refuels on route: Packwood at mile 156 and Randle at mile 217.',
        'The whole 325-mile loop at a 16 mpg baseline works out to roughly 20 gallons, but the '
        'binding constraint is the 154-mile Carson-to-Packwood leg, not the total.',
        'Forest-road fuel economy runs well below highway numbers. Plan on 65 to 82 percent of '
        'your normal mpg depending on surface, and worse if you are airing down and running low range.',
        'Fill in Nampa before departure and again somewhere in Oregon on the drive out; the '
        'travel day is 376 highway miles.',
    ],
}


# ---------------------------------------------------------------------------
# Live-conditions links
# ---------------------------------------------------------------------------
_NWS_POINT = 'https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}'

REALTIME_LINKS = [
    # --- Fire and smoke: the primary go/no-go risk for a September trip ---
    {'cat': 'Fire/Smoke', 'label': 'Gifford Pinchot NF alerts & closures (official)',
     'url': 'https://www.fs.usda.gov/r06/giffordpinchot/alerts'},
    {'cat': 'Fire/Smoke', 'label': 'Gifford Pinchot NF fire restrictions',
     'url': 'https://www.fs.usda.gov/detail/giffordpinchot/fire'},
    {'cat': 'Fire/Smoke', 'label': 'InciWeb - all active incidents',
     'url': 'https://inciweb.wildfire.gov/'},
    {'cat': 'Fire/Smoke', 'label': 'AirNow Fire & Smoke map',
     'url': 'https://fire.airnow.gov/'},
    {'cat': 'Fire/Smoke', 'label': 'WA DNR wildfire dashboard',
     'url': 'https://www.dnr.wa.gov/Wildfires'},
    {'cat': 'Fire/Smoke', 'label': 'WA Smoke Information blog',
     'url': 'https://wasmoke.blogspot.com/'},
    {'cat': 'Fire/Smoke', 'label': 'Northwest Interagency Coordination Center',
     'url': 'https://gacc.nifc.gov/nwcc/'},
    {'cat': 'Fire/Smoke', 'label': 'WA DNR burn risk / restrictions map',
     'url': 'https://experience.arcgis.com/experience/9b98a5b78b4b4c4e9b1b0b4c2f0e3f8b'},

    # --- Weather ---
    {'cat': 'Weather', 'label': 'NWS Carson / Wind River (route start)',
     'url': _NWS_POINT.format(lat=45.7411, lon=-121.8214)},
    {'cat': 'Weather', 'label': 'NWS Indian Heaven / Berry Fields',
     'url': _NWS_POINT.format(lat=46.0882, lon=-121.7678)},
    {'cat': 'Weather', 'label': 'NWS Takhlakh Lake (Day 1 camp)',
     'url': _NWS_POINT.format(lat=46.2808, lon=-121.5986)},
    {'cat': 'Weather', 'label': 'NWS Walupt Lake (Day 2 camp)',
     'url': _NWS_POINT.format(lat=46.4231, lon=-121.4736)},
    {'cat': 'Weather', 'label': 'NWS High Rock Lookout',
     'url': _NWS_POINT.format(lat=46.6845, lon=-121.9014)},
    {'cat': 'Weather', 'label': 'NWS North Fork / Cispus (Day 3 camp)',
     'url': _NWS_POINT.format(lat=46.4525, lon=-121.7889)},
    {'cat': 'Weather', 'label': 'NWS Panther Creek (Day 4 camp)',
     'url': _NWS_POINT.format(lat=45.8197, lon=-121.8797)},
    {'cat': 'Weather', 'label': 'NWS Portland office (south Cascades / Gorge)',
     'url': 'https://www.weather.gov/pqr'},
    {'cat': 'Weather', 'label': 'NWS Seattle office (Rainier / north)',
     'url': 'https://www.weather.gov/sew'},
    {'cat': 'Weather', 'label': 'NWS nationwide active alerts',
     'url': 'https://www.weather.gov/alerts'},
    {'cat': 'Weather', 'label': 'Radar KRTX (Portland)',
     'url': 'https://radar.weather.gov/station/KRTX/standard'},
    {'cat': 'Weather', 'label': 'Radar KATX (Camano / Rainier)',
     'url': 'https://radar.weather.gov/station/KATX/standard'},

    # --- Roads ---
    {'cat': 'Roads', 'label': 'WSDOT traveler information',
     'url': 'https://wsdot.com/travel/real-time/'},
    {'cat': 'Roads', 'label': 'WSDOT mountain pass conditions',
     'url': 'https://wsdot.com/travel/real-time/mountainpasses'},
    {'cat': 'Roads', 'label': 'WSDOT US 12 / White Pass corridor',
     'url': 'https://wsdot.com/travel/real-time/mountainpasses/white'},
    {'cat': 'Roads', 'label': 'Gifford Pinchot road conditions',
     'url': 'https://www.fs.usda.gov/r06/giffordpinchot/conditions'},
    {'cat': 'Roads', 'label': 'ODOT TripCheck (I-84 drive out)',
     'url': 'https://www.tripcheck.com/'},
    {'cat': 'Roads', 'label': 'Idaho 511',
     'url': 'https://511.idaho.gov/'},

    # --- Camping and permits ---
    {'cat': 'Camping/Permits', 'label': 'Recreation.gov alerts',
     'url': 'https://www.recreation.gov/alerts'},
    {'cat': 'Camping/Permits', 'label': 'Takhlakh Lake Campground (Day 1)',
     'url': _RESGOV + '232861'},
    {'cat': 'Camping/Permits', 'label': 'Walupt Lake Campground (Day 2)',
     'url': _RESGOV + '232860'},
    {'cat': 'Camping/Permits', 'label': 'North Fork Elk Group Camp (Day 3)',
     'url': _RESGOV + '232898'},
    {'cat': 'Camping/Permits', 'label': 'Tower Rock Campground (Day 3 backup)',
     'url': _RESGOV + '232855'},
    {'cat': 'Camping/Permits', 'label': 'Panther Creek Campground (Days 0 and 4)',
     'url': _RESGOV + '233103'},
    {'cat': 'Camping/Permits', 'label': 'Northwest Forest Pass',
     'url': 'https://www.fs.usda.gov/detail/r6/passes-permits/recreation/?cid=fsbdev2_027010'},
    {'cat': 'Camping/Permits', 'label': 'Skamania County parks (Home Valley)',
     'url': 'https://www.skamaniacounty.org/community/parks-recreation'},
    {'cat': 'Camping/Permits', 'label': 'Falls Creek lava caves (in this app)',
     'url': 'lava-caves.html'},

    # --- Land management ---
    {'cat': 'Forest Service', 'label': 'Gifford Pinchot National Forest',
     'url': 'https://www.fs.usda.gov/giffordpinchot'},
    {'cat': 'Forest Service', 'label': 'Mt Adams Ranger District (Trout Lake)',
     'url': 'https://www.fs.usda.gov/r06/giffordpinchot/offices/mt-adams-ranger-district'},
    {'cat': 'Forest Service', 'label': 'Cowlitz Valley Ranger District (Randle)',
     'url': 'https://www.fs.usda.gov/r06/giffordpinchot/offices/cowlitz-valley-ranger-district'},
    {'cat': 'Forest Service', 'label': 'Mount St Helens National Volcanic Monument',
     'url': 'https://www.fs.usda.gov/detail/mountsthelens/home'},
    {'cat': 'Forest Service', 'label': 'Mount Rainier National Park conditions',
     'url': 'https://www.nps.gov/mora/planyourvisit/conditions.htm'},

    # --- Emergency (public agency numbers only) ---
    {'cat': 'Emergency', 'label': 'Skamania County Sheriff (Gorge / Wind River)',
     'url': 'tel:+15094279490'},
    {'cat': 'Emergency', 'label': 'Lewis County dispatch, non-emergency (Randle / Packwood)',
     'url': 'tel:+13607401105'},
    {'cat': 'Emergency', 'label': 'Arbor Health Morton Hospital (nearest ER, north)',
     'url': 'tel:+13604965112'},
    {'cat': 'Emergency', 'label': 'Skyline Hospital White Salmon (nearest ER, south)',
     'url': 'tel:+15094931101'},
    {'cat': 'Emergency', 'label': 'Mt Adams Ranger District',
     'url': 'tel:+15093953402'},
    {'cat': 'Emergency', 'label': 'Cowlitz Valley Ranger District',
     'url': 'tel:+13604971103'},
]


INTRO_HTML = (
    '<p>A 325-mile loop through Gifford Pinchot National Forest, starting and ending in the '
    'Columbia River Gorge at Carson. The route runs north along the Mount Adams flank, touches '
    'the Goat Rocks at Walupt Lake, reaches its northern limit at High Rock Lookout looking '
    'straight at Mount Rainier, then swings back south past Mount St Helens and down the Lewis '
    'River to close the loop at Triangle Pass.</p>'
    '<p>Four driving days on route, bracketed by two 370-mile highway days to and from Nampa. '
    'Day mileages are 85, 49, 93 and 82 - the split is dictated by where developed campgrounds '
    'actually exist, since there is an 85-mile stretch in the middle of the route with nothing '
    'established.</p>'
    '<p><strong>Nothing is reserved yet.</strong> Campground notes in each day carry a live '
    'availability snapshot from 2026-08-31 and a priority order for booking. The North Fork Elk '
    'Group Camp for Friday and Saturday is the most time-sensitive one.</p>'
)


def _attach_highway_tracks(hw: dict, day: dict) -> dict:
    """Merge OSRM highway polylines onto the travel days."""
    d = dict(day)
    if d['id'] == 'sep8_travel':
        d['synthetic_track_points'] = hw.get('sep8_nampa_to_carson') or []
    elif d['id'] == 'sep13_return':
        # Sunday both closes the loop and drives home: the route slice is the
        # main line, the highway leg is drawn alongside it.
        d['extra_track_points'] = hw.get('sep13_carson_to_nampa') or []
    return d


def main() -> None:
    route = load_route(PLAN)
    hw = load_highway_tracks(PLAN)
    days_spec = [_attach_highway_tracks(hw, day) for day in DAYS]

    payload = build_payload(
        days_spec=days_spec,
        camp_data=CAMPSITES,
        schedule_defaults=SCHEDULE_DEFAULTS,
        route=route,
        trip_meta={
            'title': cfg.TRIP_TITLE,
            'subtitle': cfg.TRIP_SUBTITLE,
            'dates': f'{cfg.TRIP_DATE_START} through {cfg.TRIP_DATE_END}',
            'dates_human': cfg.TRIP_DATES_HUMAN,
            'route_gpx_source': cfg.ROUTE_GPX_FILENAME,
            'route_total_miles': round(route['total_mi'], 2),
            'main_track_points': len(route['main_points']),
            'meet_point': cfg.MEET_POINT,
            'route_start': cfg.ROUTE_START,
            'route_end': cfg.ROUTE_END,
            'highway_tracks_note': (
                (hw.get('source') or '').strip() or
                'Highway polylines follow OpenStreetMap via OSRM; not live navigation data.'
            ),
            'highway_legs': hw.get('legs') or {},
            'permits': cfg.PERMITS_NOTE,
            'emergency_contacts': cfg.EMERGENCY_CONTACTS,
            'hospitals': cfg.HOSPITALS,
            'cell_dead_zones': cfg.CELL_DEAD_ZONES,
            'satellite_comms_note': cfg.SATELLITE_COMMS_NOTE,
            'reservations_status': (
                'NOTHING IS BOOKED. Availability figures in the camp notes are a Recreation.gov '
                'snapshot from 2026-08-31 and will drift. Book in this order: North Fork Elk Group '
                'Camp (Fri + Sat), Takhlakh Lake (Wed), Panther Creek (Tue + Sat), Walupt Lake (Thu).'
            ),
        },
        group_counts=cfg.GROUP_COUNTS,
        fuel_plan=FUEL_PLAN_SUMMARY,
        realtime_links=REALTIME_LINKS,
        generated_at='2026-08-31',
        intro_html=INTRO_HTML,
    )

    out_path = PLAN / 'trip_data.json'
    write_payload(payload, out_path)
    print(f'Wrote {out_path} ({out_path.stat().st_size / 1024:.1f} KB)')
    print_payload_summary(payload, label=cfg.TRIP_TITLE)


if __name__ == '__main__':
    main()
