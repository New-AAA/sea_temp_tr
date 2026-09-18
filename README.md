# Türkiye Sea-Water Temperature Archive

Sea-water temperature observations for Türkiye, reconstructed from MGM's
(Meteoroloji Genel Müdürlüğü) Piri Reis marine portal:
<https://pirireis.mgm.gov.tr/deniz-suyu-sicakliklari>

The live page only ever shows **the latest reading**. The history is recovered by
replaying every Internet Archive capture of that page since 2021 and pulling the
readings out of each one.

## What's in the archive

As collected on 2026-09-16 (counts grow each time `live` runs):

| | |
|---|---|
| Observations | **8,111** |
| Stations | **109** |
| Distinct dates | **128** |
| Coverage | 2021-02-07 → 2026-09-16 |
| Sources | 77 MGM captures + 39 e-Devlet captures + live fetches |
| QC-flagged | 2 (kept, but marked) |

Per basin: Karadeniz 35 stations, Ege 29, Akdeniz 24, Marmara 17, Van Gölü 4.

**The record is episodic, not a regular time series.** Coverage is whatever the
Internet Archive happened to capture — 6 to 26 distinct dates per year, clustered
in summer. It supports seasonal and cross-basin comparison; it does not support
claims about trends between two arbitrary dates. Run `live` regularly to build
genuinely dense coverage from here on.

## The second source (e-Devlet)

`https://www.turkiye.gov.tr/deniz-suyu-sicakliklari` mirrors the same MGM feed,
but the Archive captured it on *different* days — so `seatemp.py edevlet` lifts
coverage from 91 to 128 distinct days (+2,745 observations). Captures before
2021-02 are excluded.

It is a messier source than the primary one, in three ways:

**No station IDs.** Stations are identified by name only. Normalising to
letters-and-digits and folding `FENERİ`→`FENER` matches 95% of rows; the rest are
stations MGM *relabelled* mid-period (`ENEZ ANA MENDİREK ( BATI )` →
`ENEZ TALİ MENDİREK`, `MARMARA ADASI BARINAK` → `MARMARA BARINAK`, and seven
more). Each rename in `edevlet._RENAMES` was confirmed by two independent checks
across the 39 captures: the two names never appear in the same capture, and the
old label stops exactly when the new one starts. All ten pairs showed that clean
handover, which is why they are treated as renames rather than as distinct
instruments. Anything without that evidence stays unmatched and is reported, not
guessed at — currently nothing is unmatched.

**No measurement date on 38 of 39 captures.** The older page template renders
`<caption> Tarihinde Güncellenen …</caption>` with the date left blank; only the
2026 template fills it in. Those rows are dated from the capture time instead:
MGM refreshes the bulk synoptic reading at 06:00, so a capture taken before 06:00
still shows the previous day. That rule is backed by three checks — the single
stamped capture (taken 00:41, stamped the previous day), and the two overlapping
captures taken before 06:00, which agree far better with the previous day
(median 0.10–0.20 °C) than with their own (0.30 °C).

Those rows carry `date_inferred = 1`, are shown with a `≈` in the dashboard, and
**may be off by one day**. Adjacent-day sea temperatures differ by only ~0.2 °C,
so the archive cannot prove the assignment for the 8 captures that land next to a
day already held; the other 29 new days are isolated, where a ±1 day error would
still leave them genuinely new.

**One timestamp for the whole page**, versus MGM's per-station times. So a row is
imported only when that station has *no* reading at all on that day: the source
adds days rather than competing with better-timestamped rows. 148 rows were
skipped as already covered.

Every row records `source` (`mgm` / `turkiye.gov.tr`) and `date_inferred`, in the
database and in `observations.csv`, so any analysis can exclude the softer data.

## How it works

The page is a Next.js app. Every server-rendered copy embeds the complete station
payload in a `<script id="__NEXT_DATA__">` JSON blob, so the data is read straight
out of the HTML — no JS execution, no HTML scraping, no brittle selectors. This
structure has held unchanged across every capture from 2021 to today.

Two details that matter:

- Captures are enumerated via the **Memento TimeMap** endpoint rather than the CDX
  API. Both list the same captures, but CDX was returning "temporarily offline"
  while TimeMap stayed up. All URL spellings (http/https, `www`, trailing slash)
  normalise to the same capture set, so one query is complete.
- Snapshots are fetched with Wayback's `id_` modifier, which returns the originally
  archived bytes with no injected toolbar. Those bytes arrive still gzipped with no
  `Content-Encoding` header, so the fetcher sniffs the magic number and inflates
  them itself.

## The dashboard

```bash
python3 seatemp.py serve        # then open http://127.0.0.1:8765/
```

It reads the SQLite database directly, so it always reflects whatever you have
collected — run `live` and reload the page. No build step and no dependencies: the
server is a single stdlib handler and every chart is inline SVG drawn in vanilla
JS. Options: `--port 9000`, `--host 0.0.0.0` (exposes it on the LAN).

Four views: a **station map** drawn over Türkiye's coastline, **seasonal averages
by sea**, a **per-station history**, and a sortable **table** of the selected
date's readings. The header button toggles light/dark.

**Station comparison** puts up to three stations side by side, in two views:
*Mevsimsel ortalama* (monthly means, joined into lines — a full 12-month cycle is
a real aggregate, so a line is honest there) and *Tüm ölçümler* (every reading as
a dot). Beside them is a table of the days on which **all** selected stations have
a reading, with each temperature and the spread between the warmest and coolest,
plus per-station means computed over those shared days so the numbers compare
like for like. **CSV indir** exports the shared-date table.

The three-station cap is a colour-safety limit, not an arbitrary one: the dot view
is an all-pairs form, and only the palette's first three slots are validated for
all-pairs separation under colour-vision deficiency in both light and dark. Slots
are tied to the A/B/C selectors rather than to rank, so swapping one station never
repaints the others, and every station is labelled with its letter badge — colour
alone never carries identity.

Picking a station — from the dropdown, or by clicking it on the map — shows its
history two ways: the dot chart *and* a scrollable, sortable list of **every
measurement** held for it, flagged rows included. **CSV indir** exports just that
station's readings.

Views are deep-linkable:
`?date=2025-08-13&scale=rel&station=17034&theme=dark`
`?cmp=17026,17340,17290&cmpview=series`

The basemap (`seatemp/basemap.json`, ~19 KB) is a simplified coastline plus Lake
Van, stored as lon/lat rings and drawn as plain SVG paths — no tile server, no
mapping library, and it works offline. Stations are placed by their real
coordinates on an equirectangular projection with a cos(latitude) correction, so
they land on the coast rather than merely near it, and the four Lake Van stations
sit on the lake. The basemap is chrome: muted land, hairline coastline, no colour
that competes with the readings.

Boundaries derive from public-domain sources — Natural Earth (Lake Van) and an
open country-boundary GeoJSON — simplified with Douglas-Peucker to 1,222 points.

Three deliberate choices in the display:

- **The map's colour scale is fixed at 0–32 °C by default**, so a February map and
  an August map are directly comparable. The cost is that on any single day the
  dots look similar — every station really is warm in September. *O güne göre*
  stretches the ramp to the selected day for within-day contrast, and the caption
  says so, because dates are then no longer comparable.
- **Station history is drawn as unconnected dots.** Coverage is episodic; a joining
  line would imply continuous sampling that does not exist.
- **QC-flagged readings are excluded from the charts** but still listed, marked
  with ⚑, rather than hidden.

Every chart carries explicit `width`/`height` attributes alongside its `viewBox`:
with `height:auto` and no intrinsic dimensions, Firefox and Safari collapse an SVG
to zero height while Chrome renders it anyway. A JS failure also now shows a red
banner instead of silently leaving blank cards.

## Publishing

`serve` reads the database live. `publish` freezes whatever is in it right now
into a static copy that needs no Python at all:

```bash
python3 seatemp.py publish              # writes site/
python3 seatemp.py publish --serve      # ... and serves it on :8765
python3 seatemp.py publish --out /var/www/seatemp
```

| File | What it is |
|---|---|
| `index.html` | The whole dashboard, ~350 KB, with the data baked in. |
| `data.json` | The same payload on its own, for other tools. |
| `observations.csv` | Every reading, joined with its station. |
| `stations.csv` | Station list with coverage counts. |

`index.html` carries its payload in an inline `<script type="application/json">`
instead of calling `/api/data`, and loads nothing from the network — no fonts, no
CDN, no tiles. So it works on any static host, behind any path, from a USB stick,
or by double-clicking it. The same file still runs against the live API when it is
served by `seatemp.py serve`, so there is only one dashboard to maintain.

The version stamp in the header shows the publication time rather than the file's
mtime, which is what tells you how fresh a published copy is.

## Usage

```bash
pip install -r requirements.txt

python3 seatemp.py all      # full run: fetch + live + basins + qc + export + stats
```

Individual steps:

| Command | Does |
|---|---|
| `fetch` | Download and ingest Wayback captures. Resumable — skips what's cached. |
| `live` | Append the current reading from the live site. |
| `edevlet` | Import the e-Devlet mirror (extra capture days). |
| `parse` | Rebuild the database from cached pages, fully offline. |
| `basins` | Re-apply the sea-basin rules (after editing `seatemp/basins.py`). |
| `qc` | Recompute quality-control flags. |
| `export` | Write `data/observations.csv` and `data/stations.csv`. |
| `stats` | Summarise the archive. |
| `serve` | Run the local dashboard (`--host`, `--port`). |
| `publish` | Freeze the current state into a static site in `site/` (`--out`, `--serve`). |

`fetch --refetch` forces re-download of already-cached captures.

Every raw page is cached under `data/raw/` as gzipped HTML, so the database can be
rebuilt offline at any time and re-runs cost no network traffic.

## Data model

`data/seatemp.db` (SQLite):

- **`observations`** — `(ist_no, veri_zamani)` primary key, `sicaklik`,
  `first_snapshot`, `qc_flag`. The composite key is what deduplicates the archive:
  the same reading appears in many captures, and consecutive captures minutes apart
  contribute zero new rows.
- **`stations`** — `ist_no`, name, province/district, coordinates, `basin`,
  `first_seen`, `last_seen`.
- **`snapshots`** — provenance for every page fetched: source, URL, cache path,
  HTTP status, record count, status.

`veri_zamani` is the **measurement** instant in UTC (from MGM), not the capture
time — so a reading is dated correctly even when archived hours later.

CSV exports carry the same content joined and flattened.

## Basins

MGM's payload has no basin field, so it's derived from province plus coordinates
(`seatemp/basins.py`). Provinces touching two seas get an explicit, documented cut:

| Province | Rule |
|---|---|
| İstanbul | lat ≥ 41.15 → Karadeniz, else Marmara |
| Kocaeli | lat ≥ 41.00 → Karadeniz, else Marmara |
| Çanakkale | lon ≥ 26.35 → Marmara (Dardanelles), else Ege |
| Balıkesir | lat ≥ 40.20 → Marmara, else Ege |
| Muğla | lon ≥ 28.00 → Akdeniz, else Ege |

The Aegean/Mediterranean split along the Muğla coast is a convention, not a natural
boundary; this one puts Datça in the Aegean and Marmaris eastward in the
Mediterranean. Edit the rules and re-run `basins` to adopt a different convention.

Van Gölü is a lake, not a sea, but MGM reports it on the same page, so it's kept
as its own basin rather than silently mixed into the sea statistics.

## Quality control

Two readings in the source feed are physically impossible and are flagged:

| Date | Station | Value | Seasonal median |
|---|---|---|---|
| 2023-01-27 | Marmara Barınak | 35.7 °C | 10.7 °C |
| 2023-02-16 | Akçakoca Feneri | 29.6 °C | 9.6 °C |

Both are single-point sensor faults — the same stations read 8–12 °C on the
surrounding dates.

The test is a robust z-score (median + MAD) within each basin-month, flagged at
|z| > 10. The threshold is deliberately high because Turkish coastal water shows
large *genuine* excursions: Black Sea summer upwelling drops Bartın, Cide and
Zonguldak by 10–13 °C within days and reaches |z| ≈ 8. There is a clean gap
between that real signal and the two faults at z = +24 and +15.

**Nothing is deleted.** Flagged rows stay in the database and the CSV with the
reason recorded, so consumers choose whether to filter. `stats` excludes them from
its temperature extremes.

## Sanity check

Monthly means reproduce the expected physical picture — Mediterranean warmest
year-round, Black Sea and Lake Van coldest, Lake Van with the sharpest seasonal
swing (4 °C → 24 °C) as a shallow continental water body should have:

| Month | Karadeniz | Marmara | Ege | Akdeniz | Van Gölü |
|---|---|---|---|---|---|
| Jan | 10.1 | 10.9 | 15.2 | 17.5 | 4.2 |
| Apr | 11.2 | 13.1 | 16.9 | 19.2 | 9.5 |
| Jul | 24.8 | 25.6 | 25.2 | 28.2 | 23.7 |
| Oct | 20.1 | 20.2 | 21.6 | 25.3 | 16.9 |

## Layout

```
seatemp.py           CLI entry point
seatemp/
  config.py          paths, URLs, politeness settings
  http.py            retry/backoff, gzip sniffing
  wayback.py         TimeMap capture enumeration
  parse.py           __NEXT_DATA__ extraction
  store.py           SQLite schema, dedup upsert, migrations
  basins.py          sea-basin assignment rules
  qc.py              outlier flagging
  pipeline.py        fetch/parse/export/stats commands
  serve.py           local dashboard server
  publish.py         static export (self-contained page + CSV/JSON)
  dashboard.html     the dashboard itself (inline SVG, no dependencies)
  basemap.json       simplified Türkiye coastline + Lake Van (lon/lat rings)
  edevlet.py         second source: parsing, name matching, date inference
data/
  raw/               cached gzipped pages (one per capture)
  seatemp.db         SQLite database
  observations.csv   flat export
  stations.csv       station list with observation counts
site/                publish output: index.html, data.json, both CSVs
```

## Notes on the source

Data is published by MGM (Turkish State Meteorological Service). Fetching is rate
limited to roughly one request every 1.5 s with retry/backoff, and identifies
itself in the User-Agent. Check MGM's terms before redistributing the data.
# sea_temp_tr
