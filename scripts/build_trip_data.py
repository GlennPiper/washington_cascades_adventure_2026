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
# Mile windows along the 324.8-mile main track. Overnight targets are free
# dispersed clusters on the track (High Lakes, Chambers, Greenhorn, Panther
# Creek pullouts). Paid developed campgrounds stay in the tables as backups.
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
            'Camp the free pullouts along Panther Creek Road (FS 65 / 6513), roughly 11 miles '
            'up Wind River Road from Carson, and start the loop from mile 0 in the morning. '
            'The developed Panther Creek campground is the paid backup.'
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
            'September. Over Babyshoe Pass to Takhlakh Lake, where Mount Adams reflects in '
            'the water - the signature view of the whole route. Overnight in the free High '
            'Lakes cluster (Council, Olallie, Chain of Lakes, Horseshoe) rather than the paid '
            'Takhlakh campground.'
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
            'The short day: 57 route miles leaves real time for the '
            'waterfalls and the Goat Rocks edge. Start on the Takh Takh lava flow, drop into '
            'the Upper Cispus, and pass Hamilton Buttes and Bishop Falls. Finish at Walupt '
            'Lake, the deepest lake in the county and the trailhead gateway to the Goat Rocks '
            'Wilderness. The Walupt Lake access road is long and rough - budget for it. Night '
            'is at Chambers Lake, the free first-come camp about 8 miles past Walupt.'
        ),
        'mi_lo': 84.5,
        'mi_hi': 141.0,
        'miles': 57,
        'driving_hours_est': 5.2,
    },
    {
        'id': 'day3_cascades',
        'label': 'Sep 11 (Fri) - Day 3: Walupt -> North Fork',
        'date_iso': '2026-09-11',
        'title': 'Day 3: Packwood fuel -> High Rock Lookout -> Randle -> North Fork',
        'type': 'overland',
        'descr': (
            'Still the long day at 91 miles, but a good share of it is paved US 12, so it moves '
            'faster than the number suggests. Fuel at Packwood around mile 156 - the first '
            'pump since Carson. The centrepiece is High Rock Lookout: about 3 miles round trip '
            'to a historic lookout on a cliff edge with Mount Rainier only 13 air miles away. '
            'Fuel again at Randle, then Layser Cave and Camp Creek Falls on the way into the '
            'free Greenhorn Creek pullouts south of Randle on the FS 25 side of the Cispus.'
        ),
        'mi_lo': 141.0,
        'mi_hi': 232.0,
        'miles': 91,
        'driving_hours_est': 6.8,
    },
    {
        'id': 'day4_cascades',
        'label': 'Sep 12 (Sat) - Day 4: North Fork -> Panther Creek',
        'date_iso': '2026-09-12',
        'title': 'Day 4: Burley Mountain -> Elk Pass -> lava caves -> Panther Creek',
        'type': 'overland',
        'descr': (
            'The volcano-and-lava day, 77 miles. Burley Mountain Lookout takes in Rainier, '
            'Adams, St Helens and Hood from one spot. South over Elk Pass with Mount St Helens '
            'filling the window, then down the Lewis River past Curly Creek Falls and its twin '
            'natural basalt arches. Late in the day, the Falls Creek Lava Caves: a genuine lava '
            'tube from the Big Lava Bed eruption. Everyone going underground needs their own '
            'headlamp plus a backup. Finish at Panther Creek Falls and camp the same free '
            'pullouts the trip started at.'
        ),
        'mi_lo': 232.0,
        'mi_hi': 308.5,
        'miles': 77,
        'driving_hours_est': 6.1,
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
# Preference: free dispersed / primitive first, paid developed campgrounds as
# backups. Inclusion rule for the FreeCampsites.net dump: Free fee, within 3.5
# miles of the main track, not a rest area / "no camping" pin / generic
# corridor listing / obvious off-route detour. Forest Road 9705 (4.7 mi off)
# is the one extra — Lewis River Horse Camp pullouts on the Day 1 corridor.
# Six vehicles will not fit on one pullout — the group should expect to occupy
# several adjacent sites in the same cluster. Stage 1 fire restrictions
# typically ban campfires at dispersed sites; bring a gas stove.
#
# Paid Recreation.gov availability (snapshot 2026-08-31) is kept on the backup
# cards only. Nothing is reserved.
_RESGOV = 'https://www.recreation.gov/camping/campgrounds/'
_FCS = 'https://freecampsites.net/'


def _camp(name, lat, lon, status, kind, cost, facilities, notes, access, url=None):
    """One campsite dict for CAMPSITES."""
    d = {
        'name': name,
        'lat': lat,
        'lon': lon,
        'status': status,
        'kind': kind,
        'cost': cost,
        'facilities': facilities,
        'notes': notes,
        'access': access,
    }
    if url:
        d['reserve_url'] = url
    return d


_SPLIT_NOTE = (
    'Six vehicles will not share one pullout. Scout on arrival and take several '
    'adjacent existing sites in the same cluster.'
)

CAMPSITES = {
    'sep8_travel': {
        'primary': [
            _camp(
                'Panther Creek Dispersed #2', 45.834828, -121.870893,
                'primary', 'dispersed_fcfs', 'Free',
                'Fire pit. No toilet, no water. Small-rig friendly.',
                ('Closest of the three named pullouts to the developed campground (~0.3 mi off '
                 'the loop at mile 308, and the same road you drive Tuesday evening). Most '
                 'reviewed of the cluster. ' + _SPLIT_NOTE),
                'Panther Creek Rd (FS 65 / 6513) off Wind River Rd, north of the developed campground.',
                _FCS + 'panther-creek-dispersed-2/',
            ),
            _camp(
                'Panther Creek Dispersed #1', 45.84326, -121.85922,
                'primary', 'dispersed_fcfs', 'Free',
                'No amenities. One of several pullouts along Panther Creek.',
                ('About a mile further up the same road as #2. Use it when #2 is taken or to '
                 'spread the group. ' + _SPLIT_NOTE),
                'FS 65 / 6513, continuing north from the developed campground.',
                _FCS + 'panther-creek-dispersed-1/',
            ),
            _camp(
                'Upper Panther Creek Dispersed', 45.84941, -121.85544,
                'primary', 'dispersed_fcfs', 'Free',
                'Large, fairly flat grassy pullout with a fire ring. Unmaintained.',
                ('The roomiest of the three. Same arrival corridor Tuesday evening. ' + _SPLIT_NOTE),
                'NF-6513 off Panther Creek Rd.',
                _FCS + 'upper-panther-creek-dispersed/',
            ),
        ],
        'secondary': {
            'name': 'Panther Creek Campground (Recreation.gov 233103)',
            'lat': 45.81972, 'lon': -121.87972,
            'status': 'secondary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 9 of 33 sites are first-come',
            'facilities': 'Vault toilets, potable water, tables, fire rings. No hookups.',
            'notes': ('Paid backup. 19 of 33 sites showed available for Sep 8 as of 2026-08-31. '
                      'Use it if the pullouts are full or you want water and a toilet after the '
                      'drive from Nampa.'),
            'access': 'WA-14 to Carson, north on Wind River Rd, right on Panther Creek Rd (FS 65).',
            'reserve_url': _RESGOV + '233103',
        },
        'tertiary': [
            {
                'name': 'Home Valley Campground (Skamania County park)',
                'lat': 45.70870, 'lon': -121.77348,
                'status': 'tertiary',
                'kind': 'developed_county',
                'cost': 'County park fee',
                'facilities': 'Showers, potable water, toilets - the only showers near the route.',
                'notes': ('Paid. Right on the Columbia and only 2.9 miles from route mile 0. '
                          'Sits between WA-14 and the BNSF main line, so expect highway and train noise.'),
                'access': 'Directly off WA-14 at Home Valley, east of Carson.',
            },
            {
                'name': 'Moss Creek Campground',
                'lat': 45.79501, 'lon': -121.63444,
                'status': 'tertiary',
                'kind': 'developed_fcfs',
                'cost': 'Per-site fee',
                'facilities': 'Vault toilets, water',
                'notes': 'Paid first-come on the Little White Salmon. Only if the group banks miles on arrival evening.',
                'access': 'FS 18 north from Willard.',
            },
        ],
    },
    'day1_cascades': {
        'primary': [
            _camp(
                'Council Lake Campground', 46.26327, -121.63178,
                'primary', 'primitive_fcfs', 'Free or low fee',
                'Vault toilet. No potable water.',
                ('On-route at mile 79.2, about 5 miles before Takhlakh. The best-documented free '
                 'High Lakes camp. Small — not six rigs in one loop. ' + _SPLIT_NOTE),
                'Short rough spur off FS 2334.',
                _FCS + 'council-lake/',
            ),
            _camp(
                'Olallie Lake Campground', 46.28868, -121.61949,
                'primary', 'primitive_fcfs', 'Free or low fee',
                'Vault toilet. No potable water.',
                'First-come. Very small, same Midway High Lakes cluster as Takhlakh.',
                'Spur off FS 2329.',
            ),
            _camp(
                'Chain of Lakes Campground', 46.29310, -121.59633,
                'primary', 'primitive_fcfs', 'Free or low fee',
                'Vault toilet. No potable water.',
                'First-come, rough access road. Spillover for the High Lakes cluster.',
                'Rough spur off FS 2329.',
            ),
            _camp(
                'Horseshoe Lake Campground', 46.30978, -121.56663,
                'primary', 'primitive_fcfs', 'Free or low fee',
                'Vault toilet. No potable water.',
                'First-come, just under a mile off route past Takhlakh.',
                'FS 2329 spur.',
            ),
            _camp(
                'Orr Creek Sno-Park', 46.350466, -121.597704,
                'primary', 'dispersed_fcfs', 'Free',
                'Vault toilet (sun vault). No potable water.',
                ('On FS 23 at mile 96.6, about 12 route miles past Takhlakh toward Adams Fork. '
                 'Push here only if High Lakes is slammed; it shortens Thursday. Elk sometimes '
                 'pass through. ' + _SPLIT_NOTE),
                'FS 23 north of Takhlakh / south of Adams Fork.',
                _FCS + 'orr-creek-sno-park/',
            ),
        ],
        'secondary': [
            _camp(
                'Near Lava Beds', 45.91383, -121.695408,
                'secondary', 'dispersed_fcfs', 'Free',
                'Informal pullouts near a pond on the way to Big Lava Bed. No facilities.',
                ('On-route at mile 30.8, Day 1 afternoon. Early-stop option, not the High Lakes '
                 'night. 10 community reviews.'),
                'Paved approach toward Big Lava Bed, ~45 min from the Columbia.',
                _FCS + 'near-lava-beds/',
            ),
            _camp(
                'Forest Route 60', 45.924556, -121.774469,
                'secondary', 'dispersed_fcfs', 'Free',
                'Several pullouts along FS 60. No facilities. Some spots are tight for larger rigs.',
                'On-route at mile 34.2 near Goose Lake / the lava-bed edge. Unrated listing.',
                'FS 60 through the Indian Heaven / lava-bed corridor.',
                _FCS + 'forest-route-60/',
            ),
            _camp(
                'Huckleberry Access', 46.091105, -121.79985,
                'secondary', 'dispersed_fcfs', 'Free',
                'Paved viewpoint with room for RVs. No toilet listed.',
                ('On-route at mile 54.5. Mount St Helens view and seasonal huckleberries. May be '
                 'day-use — read posted signs before overnighting.'),
                'FS 23 / berry-fields corridor.',
                _FCS + 'huckleberry-access/',
            ),
            _camp(
                'Forest Road 9705', 46.18798, -121.82302,
                'secondary', 'dispersed_fcfs', 'Free',
                'Several pullouts past Lewis River Horse Camp with rock fire pits. Room for cars. Quiet road. No toilet listed.',
                ('About 4.7 miles off the track near mile 57, on the Lewis River side of Day 1. '
                 'Early-stop / overflow, not the High Lakes night.'),
                'Forest Road 9705 past the Lewis River Horse Camp.',
                _FCS + 'forest-road-9705/',
            ),
            _camp(
                'Flattop Sno-Park', 46.056878, -121.628389,
                'secondary', 'dispersed_fcfs', 'Free',
                'Winter lot used as a free dispersed site in summer. No reviews on file.',
                'About 3.3 miles off the track near mile 46. Unconfirmed; scout before committing.',
                'Trout Lake / FS 23 side roads.',
                _FCS + 'flattop-sno-park/',
            ),
        ],
        'tertiary': {
            'name': 'Takhlakh Lake Campground (Recreation.gov 232861)',
            'lat': 46.28083, 'lon': -121.59861,
            'status': 'tertiary',
            'kind': 'developed_reservable',
            'cost': 'Per-site fee; 18 of 54 sites are first-come',
            'facilities': 'Vault toilets, potable water, tables, fire rings. No hookups. Non-motorised boating only.',
            'notes': ('Paid backup at the signature lake. 22 of 54 sites showed available for '
                      'Sep 9 as of 2026-08-31; zero Friday and Saturday. Use it if the free High '
                      'Lakes cluster is full or you want potable water.'),
            'access': 'FS 23 over Babyshoe Pass, then FS 2329.',
            'reserve_url': _RESGOV + '232861',
        },
    },
    'day2_cascades': {
        'primary': [
            _camp(
                'Chambers Lake Campground', 46.46549, -121.53183,
                'primary', 'primitive_fcfs', 'Free or low fee',
                'Vault toilet. No potable water.',
                ('Free first-come camp at mile 140.5, about 8 miles past Walupt near the Goat '
                 'Rocks boundary. The actual Thursday night. Availability cannot be checked in '
                 'advance. ' + _SPLIT_NOTE),
                'FS 21 spur north of the Walupt junction.',
                _FCS + 'chambers-lake/',
            ),
            _camp(
                'Cat Creek Campground', 46.34855, -121.62496,
                'primary', 'primitive_fcfs', 'Free',
                'Vault toilet. No potable water.',
                ('First-come, very small, route mile 101. Early-stop option that shortens '
                 'Thursday and lengthens Friday. ' + _SPLIT_NOTE),
                'FS 2160 just east of Adams Fork.',
            ),
        ],
        'tertiary': [
            {
                'name': 'Walupt Lake Campground (Recreation.gov 232860)',
                'lat': 46.42306, 'lon': -121.47361,
                'status': 'tertiary',
                'kind': 'developed_reservable',
                'cost': 'Per-site fee; 14 of 42 sites are first-come',
                'facilities': 'Vault toilets, potable water, boat launch. No hookups.',
                'notes': ('Paid backup at the lake itself. 7 of 42 sites showed available for '
                          'Sep 10 as of 2026-08-31. Goat Rocks trailheads leave from the campground. '
                          'The access road in is long and rough.'),
                'access': 'FS 21 then FS 2160 east - roughly 16 miles of gravel off the main route.',
                'reserve_url': _RESGOV + '232860',
            },
            {
                'name': 'Adams Fork Campground (Recreation.gov 232857)',
                'lat': 46.33889, 'lon': -121.64694,
                'status': 'tertiary',
                'kind': 'developed_reservable',
                'cost': 'Per-site fee; 7 of 23 sites are first-come',
                'facilities': 'Vault toilets, tables, fire rings. No potable water.',
                'notes': ('Paid early-stop at mile 99.6. 16 of 23 sites showed available for Sep 10. '
                          'Choosing it shortens Thursday and lengthens Friday.'),
                'access': 'On FS 21 beside the Cispus River.',
                'reserve_url': _RESGOV + '232857',
            },
        ],
    },
    'day3_cascades': {
        'primary': [
            _camp(
                'Greenhorn Creek', 46.433576, -121.940737,
                'primary', 'dispersed_fcfs', 'Free',
                'Three shaded creek sites. No toilet listed. Spots can fit a ~24 ft rig.',
                ('On the FS 25 side of the Cispus at mile 230.8, a few miles past North Fork / '
                 'Tower Rock. Best genuine dispersed night for Friday. ' + _SPLIT_NOTE),
                'South of Randle on FS 25 / Greenhorn Creek.',
                _FCS + 'greenhorn-creek/',
            ),
        ],
        'secondary': [
            _camp(
                'Skate Creek Sno-Park', 46.63837, -121.71165,
                'secondary', 'dispersed_fcfs', 'Free',
                'Pull-offs along the road; most have a fire pit. River sites exist.',
                ('On-route at mile 160.7 near Packwood. Early-stop / overflow, not the Friday '
                 'night unless the day is running long.'),
                'Skate Creek Rd (FS 52) near Packwood.',
                _FCS + 'skate-creek-sno-park/',
            ),
            _camp(
                'Packwood WA NF', 46.63448, -121.679917,
                'secondary', 'dispersed_fcfs', 'Free',
                'End-of-road site in an old quarry. No facilities.',
                'On-route at mile 158.6. Same Packwood-area overflow idea as Skate Creek.',
                'National forest road at the edge of Packwood.',
                _FCS + 'packwood-wa-nf/',
            ),
            _camp(
                'Iron Creek Dispersed', 46.427984, -121.98043,
                'secondary', 'dispersed_fcfs', 'Free',
                'Pullouts about 1/4 mile past the official Iron Creek campground.',
                ('The developed Iron Creek campground is CLOSED the entire trip week. These '
                 'pullouts may still be open — or may be wrapped into the closure. Confirm with '
                 'Cowlitz Valley Ranger District before counting on it.'),
                'FS 25 toward Mt St Helens, past the closed Iron Creek campground.',
                _FCS + 'iron-creek-dispersed-campsite/',
            ),
        ],
        'tertiary': [
            {
                'name': 'North Fork Elk Group Camp (Recreation.gov 232898)',
                'lat': 46.45250, 'lon': -121.78889,
                'status': 'tertiary',
                'kind': 'developed_group_reservable',
                'cost': 'Single group-site fee for the whole party',
                'facilities': 'Vault toilets, potable water, group shelter area, tables, fire rings.',
                'notes': ('Paid backup that actually fits six vehicles in one booking. As of '
                          '2026-08-31 it was open Fri Sep 11 and Sat Sep 12. Worth considering '
                          'if the group wants to stay together with water and a shelter.'),
                'access': 'FS 23 south from Randle along the Cispus, near North Fork Campground.',
                'reserve_url': _RESGOV + '232898',
            },
            {
                'name': 'Tower Rock Campground (Recreation.gov 232855)',
                'lat': 46.44500, 'lon': -121.86806,
                'status': 'tertiary',
                'kind': 'developed_reservable',
                'cost': 'Per-site fee; 6 of 20 sites are first-come',
                'facilities': 'Vault toilets, potable water, tables, fire rings.',
                'notes': ('Paid backup at mile 228.6. Best weekend availability found on the paid '
                          'list: 10 of 20 Friday, 8 Saturday as of 2026-08-31.'),
                'access': 'FS 23 / FS 28 along the Cispus, south of Randle.',
                'reserve_url': _RESGOV + '232855',
            },
        ],
    },
    'day4_cascades': {
        'primary': [
            _camp(
                'Panther Creek Dispersed #2', 45.834828, -121.870893,
                'primary', 'dispersed_fcfs', 'Free',
                'Fire pit. No toilet, no water. Small-rig friendly.',
                ('Same Saturday night as Tuesday: closest named pullout after Panther Creek Falls '
                 '(mile 308.4). ' + _SPLIT_NOTE),
                'Panther Creek Rd (FS 65 / 6513) off Wind River Rd.',
                _FCS + 'panther-creek-dispersed-2/',
            ),
            _camp(
                'Panther Creek Dispersed #1', 45.84326, -121.85922,
                'primary', 'dispersed_fcfs', 'Free',
                'No amenities. One of several pullouts along Panther Creek.',
                'Same cluster as #2. Spread the group here if #2 is full.',
                'FS 65 / 6513, north of the developed campground.',
                _FCS + 'panther-creek-dispersed-1/',
            ),
            _camp(
                'Upper Panther Creek Dispersed', 45.84941, -121.85544,
                'primary', 'dispersed_fcfs', 'Free',
                'Large grassy pullout with a fire ring. Unmaintained.',
                'Roomiest of the three Panther Creek pullouts. Same Saturday cluster.',
                'NF-6513 off Panther Creek Rd.',
                _FCS + 'upper-panther-creek-dispersed/',
            ),
            _camp(
                'Crest Camp', 45.90889, -121.80103,
                'primary', 'primitive_fcfs', 'Free',
                'None. No water, no toilet.',
                'Primitive site at mile 302.7 near the PCT crossing. Fits a couple of rigs. Earlier Saturday stop if Panther Creek pullouts are full.',
                'FS 60 near the PCT trailhead.',
            ),
        ],
        'secondary': [
            _camp(
                'FR-7708', 46.336418, -121.967987,
                'secondary', 'dispersed_fcfs', 'Free',
                'Creek-side site with a cold pool. No facilities.',
                'On-route at mile 244.5, Saturday morning after Greenhorn / Iron Creek.',
                'Gifford Pinchot, FS 7708 off the Cispus / Lewis divide.',
                _FCS + 'fr-7708/',
            ),
            _camp(
                'Forest Route 9039', 46.110056, -121.99432,
                'secondary', 'dispersed_fcfs', 'Free',
                'Several tucked sites. A couple will take a trailer. No facilities.',
                ('On-route at mile 272, Lewis River / Cougar side. Hunting-area notes in reviews. '
                 'Early Saturday stop that leaves loop miles for Sunday.'),
                'FS 9039 off the Lewis River corridor.',
                _FCS + 'forest-route-9039/',
            ),
            _camp(
                'Dispersed campsite off NF-90', 46.125331, -121.909858,
                'secondary', 'dispersed_fcfs', 'Free',
                'Dispersed site off NF-90. Confirm the area is open before leaving cell service.',
                'On-route at mile 281.6 on the Lewis River. Same early-stop idea as FS 9039.',
                'NF-90, Gifford Pinchot.',
                _FCS + 'dispersed-campsite-off-nf-90/',
            ),
            _camp(
                'Lone Butte Sno-Park', 46.044029, -121.859371,
                'secondary', 'dispersed_fcfs', 'Free',
                'Winter lot; free dispersed in summer. Unrated.',
                'On-route at mile 288.1, Wind River high country approaching Panther Creek.',
                'FS 30 / 60 corridor west of Indian Heaven.',
                _FCS + 'lone-butte-sno-park/',
            ),
            _camp(
                'Rush Creek Sno-Park', 46.035354, -121.880896,
                'secondary', 'dispersed_fcfs', 'Free',
                'Winter lot; free dispersed in summer. Unrated.',
                'On-route at mile 289.4, same corridor as Lone Butte and Curley Creek.',
                'FS 30 / 60 corridor.',
                _FCS + 'rush-creek-sno-park/',
            ),
            _camp(
                'Curley Creek Sno-Park', 46.026705, -121.891036,
                'secondary', 'dispersed_fcfs', 'Free',
                'Winter lot; free dispersed in summer. Unrated.',
                'On-route at mile 289.6. Third of the three sno-park pullouts in this cluster.',
                'FS 30 / 60 corridor.',
                _FCS + 'curley-creek-sno-park/',
            ),
        ],
        'tertiary': [
            {
                'name': 'Panther Creek Campground (Recreation.gov 233103)',
                'lat': 45.81972, 'lon': -121.87972,
                'status': 'tertiary',
                'kind': 'developed_reservable',
                'cost': 'Per-site fee; 9 of 33 sites are first-come',
                'facilities': 'Vault toilets, potable water, tables, fire rings.',
                'notes': ('Paid backup. Only 5 of 33 sites showed available for Sat Sep 12 as of '
                          '2026-08-31. Use it if the pullouts are full or you want water.'),
                'access': 'Panther Creek Rd (FS 65) off Wind River Rd.',
                'reserve_url': _RESGOV + '233103',
            },
            {
                'name': 'Home Valley Campground (Skamania County park)',
                'lat': 45.70870, 'lon': -121.77348,
                'status': 'tertiary',
                'kind': 'developed_county',
                'cost': 'County park fee',
                'facilities': 'Showers, potable water, toilets.',
                'notes': ('Paid. Finishing the full loop to Triangle Pass and dropping here makes '
                          'Saturday longer but buys hot showers before the drive home.'),
                'access': 'Directly off WA-14 at Home Valley.',
            },
        ],
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
    {'cat': 'Camping/Permits', 'label': 'Takhlakh Lake Campground (Day 1 paid backup)',
     'url': _RESGOV + '232861'},
    {'cat': 'Camping/Permits', 'label': 'Walupt Lake Campground (Day 2 paid backup)',
     'url': _RESGOV + '232860'},
    {'cat': 'Camping/Permits', 'label': 'North Fork Elk Group Camp (Day 3 paid backup)',
     'url': _RESGOV + '232898'},
    {'cat': 'Camping/Permits', 'label': 'Tower Rock Campground (Day 3 paid backup)',
     'url': _RESGOV + '232855'},
    {'cat': 'Camping/Permits', 'label': 'Panther Creek Campground (Tue/Sat paid backup)',
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
    'Day mileages are 85, 57, 91 and 77. Nights target free dispersed clusters on the track; '
    'paid developed campgrounds stay in each day as backups.</p>'
    '<p><strong>Nothing is reserved.</strong> The plan prefers free first-come pullouts. '
    'Six vehicles will need several adjacent sites in the same cluster. Stage 1 fire '
    'restrictions typically ban campfires at dispersed sites &mdash; bring a gas stove. '
    'Paid Recreation.gov camps remain listed if a cluster is full or you want water.</p>'
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
                'Nothing is reserved. Nights are free dispersed / primitive first-come sites; '
                'paid Recreation.gov campgrounds are backups if a cluster is full or you want '
                'water. Six vehicles will need several adjacent pullouts. Stage 1 fire '
                'restrictions typically ban campfires at dispersed sites.'
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
