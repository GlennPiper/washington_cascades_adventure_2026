# Washington Cascades Adventure Route — September 8–13, 2026

Trip-planning workspace and an offline-first Progressive Web App for a 325-mile
overlanding loop through Gifford Pinchot National Forest.

The app is generated. A Python pipeline reads the source route GPX plus the
planning tables in this repo and writes self-contained HTML with the maps, POIs,
campgrounds and schedule data baked in, so it works with no cell signal — which
matters, because there is none between Carson and Packwood.

---

## The trip

| | |
|---|---|
| **Route** | 324.8-mile loop, Gifford Pinchot National Forest |
| **Dates** | Tue Sep 8 – Sun Sep 13, 2026 |
| **Start / end** | Carson, WA (Columbia River Gorge) → Triangle Pass |
| **Meet** | Sinclair Stinker Station, 1902 N Franklin Blvd, Nampa ID. Gather 8:00 AM MDT, depart 8:15 |
| **Group** | ~6 vehicles, no split. Head count TBC |
| **Highway legs** | 376 mi out, 368 mi back (~7 hr moving each way) |
| **Fuel on route** | Carson (mi 2), Packwood (mi 156), Randle (mi 217) |

### Day split

The split is dictated by free dispersed clusters on the track (High Lakes, Chambers,
Greenhorn, Panther Creek pullouts). Paid developed campgrounds stay in the tables as
backups.

| Day | Route miles | Distance | Camp |
|---|---|---|---|
| Tue Sep 8 | travel | 376 mi highway | **Panther Creek dispersed** |
| Wed Sep 9 | 0 → 84.5 | 85 mi | **High Lakes free cluster** (Council / Olallie) |
| Thu Sep 10 | 84.5 → 141 | 57 mi | **Chambers Lake** |
| Fri Sep 11 | 141 → 232 | 91 mi | **Greenhorn Creek** |
| Sat Sep 12 | 232 → 308.5 | 77 mi | **Panther Creek dispersed** |
| Sun Sep 13 | 308.5 → 324.8 | 16 mi + 368 mi home | — |

> **Nothing is reserved.** Primary nights are free first-come sites. See
> [`planning/camping_plan.md`](planning/camping_plan.md). Six vehicles will need several
> adjacent pullouts in the same cluster. Stage 1 fire restrictions typically ban campfires
> at dispersed sites.

---

## What gets built

| Output | What it is |
|---|---|
| `index.html` | Landing page with per-platform install instructions and a QR code |
| `trip-itinerary.html` | **The main app.** Tabbed day-by-day itinerary with Leaflet maps, POI tables, campground cards, and a live arrival-time scheduler |
| `trip-reference.html` | Everything in one linear document: overview, live links, fuel, every day, hikes, emergency contacts, permits |
| `camping-plan.html` | Free-first nights, along-route overflow, and paid-backup availability |
| `fuel-plan.html` | Station list, the two fuel gaps, per-vehicle range worksheet |
| `fire-and-closures.html` | Go/no-go page: forest alerts, restriction stages, smoke thresholds |
| `lava-caves.html` | Guler Ice Cave (Wed) and Falls Creek Lava Caves (Sat): fees, gear, white-nose decon, how to find them |
| `weather.html` | Dual NWS + Open-Meteo forecast for every camp |
| `settings.html` | Trip preferences, including offline spoken notes as you approach a stop |
| `trip-plan.gpx` | Derived route with day-split tracks and labeled camps, for Gaia / onX / CalTopo / Garmin |
| `manifest.webmanifest`, `service-worker.js`, `icons/*` | PWA plumbing (generated, gitignored) |

### The itinerary page in more detail

Each day tab carries a Leaflet map, the day's stops in route-mile order, and the
campground options for that night ranked primary / secondary / tertiary.

The **arrival-time scheduler** is the part worth understanding. Each stop has a
checkbox and an editable stop duration. Given a break-camp time and a moving
speed, the page computes a running ETA down the day and an arrival time at camp,
and persists your edits to `localStorage`. Most hikes start **unchecked** so the
day's estimate begins as driving-only; you tick the ones you want and watch the
arrival time move. **Lava tubes, ice caves and fire lookouts start checked** — they are on
the day's plan; uncheck them to skip.

POI statuses drive the badges and the scheduler defaults:

| Status | Meaning | Checked by default |
|---|---|---|
| `primary` | Planned stop | yes |
| `hike_candidate` | Hike or activity to triage | no, except lava tubes, ice caves and lookouts |
| `backup` | Lower-priority option | no |
| `landmark` | A distant peak marker, not a place you drive to | no, and contributes zero miles |
| `logistics` | Fuel and services | no |
| `skip` | Excluded (usually a trailhead that duplicates its destination) | n/a |

`landmark` exists because the source GPX marks Mount Rainier, Mount Adams, Mount
St Helens and Gilbert Peak as waypoints 5–13 miles off the track. Without a status
that zeroes their offset, the scheduler would cheerfully add a 25-mile round trip
to go visit the summit of Rainier.

---

## Build it

Requires Python 3.10+.

```bash
pip install markdown pillow "qrcode[pil]"

python scripts/download_offline_tiles.py   # once; also vendors Leaflet
python scripts/fetch_highway_tracks.py     # once; needs network (OSRM)
python scripts/parse_route_gpx.py
python scripts/analyze_route.py
python scripts/build_trip_data.py
python scripts/build_pwa_icons.py
python scripts/build_deliverables.py
python scripts/build_pwa_assets.py
```

Then preview:

```bash
python -m http.server 8899
# open http://localhost:8899/index.html
```

A plain `file://` open mostly works, but service workers and the PWA install
prompt need to be served over HTTP. **Geolocation on iPad also needs HTTPS or
localhost** — `file://` will never show the blue "you are here" dot.

### iPad GPS + fullscreen tests (free)

The last version of this app failed two iPad Safari cases: `watchPosition`
started on a timer (no tap, so the permission prompt never appeared) and the
Fullscreen API, which exists on iPad but is a no-op for anything but `<video>`.
Apple's Simulator is Mac-only and cloud device farms are paid. The free stand-in
is Playwright Chromium with an iPad viewport plus scripts that reproduce those
two Safari quirks:

```bash
pip install playwright
python -m playwright install chromium
python scripts/test_ipad_maps.py
```

That is not a real iPad. It catches the logic bugs (silent GPS errors, fullscreen
fallback never applying, nav covering the map). Final check is still a physical
iPad over HTTPS: tap **My location**, allow Safari, confirm the blue dot, then
toggle **Fullscreen** twice and with the hardware Escape equivalent.

### Pipeline shape

```
wa-cascades-adv-route-2025.gpx
  │
  ├─ parse_route_gpx.py ──► planning/route_waypoints.json
  │                          planning/route_tracks.json
  │                          planning/waypoint_sym_counts.json
  │
  ├─ analyze_route.py ────► planning/route_analysis.json   (waypoints + route mile)
  │
  ├─ fetch_highway_tracks.py ► planning/highway_tracks.json (OSRM, travel days)
  │
  ├─ build_trip_data.py ──► planning/trip_data.json         ◄── the single payload
  │       reads trip_config.py + trip_core.py                    everything renders from
  │
  ├─ build_deliverables.py ► *.html + trip-plan.gpx
  │       + planning/*.md for the companion pages
  │
  └─ build_pwa_assets.py ─► manifest, service worker, robots, QR
```

### Which file owns what

| File | Owns |
|---|---|
| `scripts/trip_config.py` | **Trip identity.** Title, dates, source GPX, main track name, map bbox, meet point, agency and hospital contacts, cell dead zones, daylight table, gear notes, permits |
| `scripts/build_trip_data.py` | Day split, campground plan, fuel plan, live-conditions links |
| `scripts/trip_core.py` | POI catalog (status + note per waypoint), extra planned stops not in the source GPX, scheduler stop-time defaults, payload assembly |
| `scripts/build_deliverables.py` | All HTML and GPX generation |
| `planning/*.md` | Source text for the companion pages |
| `planning/weather_forecast_points.json` | One forecast point per day, placed at each night's camp |

---

## Retargeting to a new trip

This has been done once (San Rafael Swell 2026 → Washington Cascades 2026), and
the pipeline was refactored during it specifically to make the next one easier.
Work in this order.

**1. Drop in the new source GPX** at the repo root.

**2. Edit `scripts/trip_config.py`.** This is most of the work:

- `TRIP_TITLE`, `TRIP_DATES_HUMAN`, `TRIP_DATE_START` / `_END`
- `JS_PREFIX` — change it. It namespaces `localStorage` and the service-worker
  cache, so reusing the old prefix lets a phone with the previous trip installed
  serve stale pages.
- `ROUTE_GPX_FILENAME`, `MAIN_TRACK_NAME` (must match a `<trk><name>` exactly),
  `IGNORED_TRACK_NAMES`
- `TILE_BBOX`, `MAP_FALLBACK_CENTER`
- `NWS_ALERT_AREA` — the two-letter state for the live alerts strip
- `MEET_POINT`, `ROUTE_START`, `ROUTE_END`, `GROUP_COUNTS`
- `EMERGENCY_CONTACTS`, `HOSPITALS`, `CELL_DEAD_ZONES`, `PERMITS_NOTE`

**3. Run parse and analyze**, then read the output. `analyze_route.py` prints
every waypoint with its route mile, which is exactly what you need to choose day
boundaries and spot the campground gaps:

```bash
python scripts/parse_route_gpx.py && python scripts/analyze_route.py
```

**4. Write the POI catalog** in `scripts/trip_core.py`. Keys must match the GPX
`<name>` byte-for-byte, typos included. Waypoints with `sym` of `campsite-24` are
dropped automatically since campgrounds are handled separately. Use `POI_RENAME`
for generic duplicate names (the three waypoints all called "Gas Station"), and
update `default_minutes()` with stop budgets for the new stops.

**5. Write the day split, camps, fuel and links** in `scripts/build_trip_data.py`.
Day mile windows come from the analyze output. Check live campground availability
before committing to a split — it constrained this trip's split more than terrain did:

```bash
python scripts/check_availability.py
```

**6. Rewrite `planning/*.md`** for the companion pages, and delete or add pages by
editing the `pages` list in `write_planning_markdown_pages()` plus the nav list in
`_top_nav_html()`, both in `build_deliverables.py`. `settings.html` is generated
by `write_settings_html()` in the same module (not from markdown).

**7. Regenerate `planning/weather_forecast_points.json`** — one entry per day,
with `day_id` matching the day ids in `build_trip_data.py`.

**8. Update by hand:**
- `index.html` — title, tagline, and the button list. It is static, not generated.
- `.github/scripts/secret-scan.sh` — the `ALLOW_NUMBERS` allow-list must contain
  every public phone number in `trip_config.py`, or the deploy fails. Also refresh
  the participant `NAMES` list for the new roster.
- `.github/workflows/deploy.yml` — the staged file list and the branch trigger.

**9. Re-download offline tiles** for the new bbox: `rm -rf planning/offline_tiles`
then rerun `download_offline_tiles.py`.

### Things that will bite you

- **`MAIN_TRACK_NAME` must match exactly.** Both parse and analyze fail loudly if
  it does not, which is deliberate.
- **Any waypoint far off the track needs `landmark` status**, or it wrecks the
  scheduler's mileage.
- **The secret scan runs on the published output, not the source.** A new phone
  number in `trip_config.py` that is not in the allow-list fails the deploy.
- **Offline tiles are deliberately shallow.** Zooms 7–10, 52 tiles, about 985 KB,
  which base64-embeds into `trip-itinerary.html` and takes it to roughly 1.8 MB.
  They are for orientation; real navigation is the GPX in a proper mapping app.
  Tile count grows fast — for this bbox z11 would cost 104 tiles and push the page
  past 5 MB. If you change `TILE_ZOOMS`, the `maxNativeZoom` on the offline Leaflet
  layer follows it automatically; hardcoding it lower silently wastes every tile
  deeper than the cap, which is a mistake this repo has already made once.
- **`generated_at` in `build_trip_data.py`** feeds the service-worker cache
  version. Bump it when shipping changes to the group.

---

## Deployment

GitHub Actions builds and publishes to GitHub Pages on push to `main`. `SITE_URL`
is derived by the workflow from the repository owner and name and is used only for
the QR code, so the artifact itself is host-agnostic — every internal link is
relative. Nothing in the source references a repository name.

The deploy stages only the public files into `_publish/`. Source, planning notes
and the KML Viewer stay out of the published artifact, and a PII guard
(`.github/scripts/secret-scan.sh`) fails the build if a participant name, an
email, or a non-allow-listed phone number reaches the output.

### Moving to a new repository

Each trip deserves its own repository, since the published Pages URL is derived
from the repository name.

1. Create a **completely empty** repo on GitHub — no README, no `.gitignore`, no
   licence, or the first push is rejected.
2. Run the migration script from a clean working tree:

```bash
scripts/migrate_to_new_repo.sh git@github.com:OWNER/NEW-REPO.git
```

It verifies the tree is clean, runs a full build, and confirms the build produces
no diff against the committed deliverables — a stale-output check worth having
before the first push triggers a deploy. Then it pushes to the new remote as
`main` and prints the remaining steps.

Full history is kept by default, which preserves the record of how the app was
retargeted. Pass `--squash` for a single initial commit instead; both modes push
byte-identical file trees, so the choice is purely about `git log`.

3. In the new repo, set **Settings → Pages → Source: GitHub Actions**. The first
   deploy usually fails at the publish step because Pages was not enabled yet —
   re-run the workflow afterwards.
4. Confirm `https://OWNER.github.io/NEW-REPO/` loads and the itinerary map renders.
   The QR code regenerates against the new URL automatically.

The old repository is left untouched and makes a reasonable archive.

**One caveat if you want an agent to keep working there:** a Cursor agent's token
is scoped to a single repository, so an agent running against the old repo cannot
see or push to the new one. Authorize the Cursor GitHub App on the new repository
and start a fresh agent there.

---

## Also in here

- **`KML Viewer/`** — a standalone React + Vite tool for previewing KML/KMZ/GPX
  files locally. Not part of the trip site and not deployed. Genuinely useful when
  you get handed a new route file and want to look at it before wiring it in.
  `cd "KML Viewer" && npm install && npm run dev`
- **`scripts/check_availability.py`** — queries live Recreation.gov availability
  for the campgrounds on this route.
- **`scripts/daylight_table.py`** — regenerates `trip_config.DAYLIGHT` (sunrise,
  sunset and total daylight per trip day) from the NOAA solar algorithm.
- **`REVIEW-NOTES.md`** — decisions taken without the trip organiser present,
  assumptions that need confirming, and the open questions.
- **`Planning prompt.md`** — the brief this trip was planned from.

## Not in here

Gitignored: `Participants.md` (names, phone numbers, rig details), the generated
PWA files (`manifest.webmanifest`, `service-worker.js`, `robots.txt`, `icons/*.png`,
`assets/qr.png`), and `_publish/`. CI regenerates all of it.
