# Decisions Log

Running record of what was decided, why, and what's still open for the
Idaho Water User Drought Reports pipeline (Objective 2 of
`UI_Kukal_Narrative.pdf`). Newest entries at the top. See `README.md` for
current setup/usage instructions.

## Open items

- [ ] Full batch run for both layers (363 polygons) — in progress.
- [ ] Create the GitHub remote (personal account) and push.
- [ ] Add repo secrets (`CE_API_KEY`, `GW_ASSET_ID`, `IRR_ASSET_ID`) and
      enable GitHub Pages (source = GitHub Actions) once pushed.
- [ ] Site design: curate which Climate Engine graphics appear per page
      (current-conditions map, summary table, long-term chart per the
      narrative) instead of dumping all 14 images; add plain-language
      explanations per drought index; decide whether to rebuild the
      long-term time series chart ourselves from `ltb_eoy_timeseries.csv`
      (1985(ish)-present) rather than using Climate Engine's own chart image.
- [ ] Confirm real per-cycle wall-clock time and any Earth Engine
      concurrency/quota friction at full 363-polygon scale (only tested
      with `--submit-concurrency 4` on 1 polygon so far).
- [ ] Verify the GitHub Actions daily-cron + `state.json` cadence gate
      actually self-heals correctly across a missed/failed run once live.

## Decisions

### Site content will exclude Climate Engine's bundled PDF/report.png
**Decision:** `build_site.py` skips `reports/report.pdf` and
`reports/report.png` from each downloaded zip; only `images/*.png` and
`data/*.csv` get used.
**Why:** The narrative is explicit: "we are not going to use the PDF
reports that the climate engine gives; but we will use the graphics and
data to do our own reports where we explain things a bit more."
**How to apply:** Any future rework of `build_site.py` should keep sourcing
from `images/`/`data/`, not `reports/`.

### `site_name` must be ≤35 characters
**Decision:** `slugify()` (shared between `fetch_reports.py` and
`build_site.py`) truncates to 35 characters.
**Why:** Confirmed via a real `422` response: `"Please limit length of
site_name to 35 characters!"`. Verified no collisions after truncation
across all 13 groundwater districts + 350 irrigation organizations.
**How to apply:** If the boundary layers are ever regenerated with
different names, re-run the collision check in `prep_boundaries.py`'s
output before trusting 35-char truncation again.

### Reports are submitted async (`batch=True`) and polled, not synchronous
**Decision:** `fetch_reports.py` submits every polygon with `batch=True`
(returns in ~8s with a `status_link`), then round-robin polls all
outstanding jobs until each reports `status: "success"` (or times out
after 20 min).
**Why:** A synchronous (`batch=False`) call was timed at 110–140s per
polygon for real Idaho districts. At 363 polygons sequential-sync would be
~11 hours — impractical. Async submission is cheap (~8s) and lets Earth
Engine compute reports concurrently server-side; individual jobs still take
~2–3 min, but many run in parallel instead of one at a time.
**How to apply:** If per-cycle wall-clock time at full scale (363 polygons)
turns out to be too slow even with async + polling, consider raising
`--submit-concurrency` (default 4) or investigate a true one-call
bulk-submit if Climate Engine adds one later — the current API does not
support it (see next entry).

### One API call = one polygon, not one call per shapefile
**Decision:** Loop over every feature name in each processed boundary file
and issue a separate `/reports/drought/feature_collection` call per name.
**Why:** Checked the live OpenAPI spec at `api.climateengine.org/openapi.json`
directly (more authoritative than the prose docs pages, which implied
`sub_choices` could be a list). `sub_choices` is typed as a single string.
There is no endpoint that fans a `FeatureCollection` out into many reports
in one call.
**How to apply:** Don't revisit "batch by shapefile" as an optimization
without re-checking the live OpenAPI spec first — the docs pages are not
reliable on this specific point.

### `CE_USER_EMAIL` is left empty for all scheduled/bulk runs
**Decision:** `fetch_reports.py` defaults `user_email` to `""`; the
GitHub Actions workflow does not set a `CE_USER_EMAIL` secret at all.
**Why:** A real address in that field makes Climate Engine email a copy of
*every* report generated — one email per polygon per run. We accidentally
triggered this once during initial testing (363-emails-per-cycle would
follow if left on for production). We already get the report zip link
directly in the API's JSON response, so email delivery isn't needed.
**How to apply:** Only ever set `CE_USER_EMAIL` for a deliberate manual
one-off test where the email confirmation itself is wanted.

### Earth Engine Table Upload needs a zipped shapefile, not GeoJSON
**Decision:** `prep_boundaries.py` outputs both a `.json` (GeoJSON, used
internally by the other scripts) and a `.zip` (zipped `.shp/.shx/.dbf/.prj/.cpg`,
used for the actual Earth Engine upload).
**Why:** Earth Engine's "Table Upload" dialog rejected a `.geojson` file
outright ("does not have a correct extension"), and separately rejected a
bare `.json` too — its allowed extensions for that dialog are
`shp, zip, dbf, prj, shx, cpg, fix, qix, sbn, shp.xml` only.
**How to apply:** Any future new boundary layer must go through the same
zipped-shapefile path for upload, even though our own scripts are happy
reading GeoJSON.

### Report cadence: every 5 days, not weekly
**Decision:** `run_pipeline.py` enforces a 5-day minimum between runs
(tracked via `data/reports/state.json`, committed back to the repo), and
the GitHub Actions cron runs daily but no-ops unless due.
**Why:** The underlying gridMET Drought dataset Climate Engine's drought
reports pull from is a **pentad (5-day)** product — confirmed from its
Climate Engine dataset page (`gridmetdrought_pentad_4000`). This also
matches the narrative's stated "updated every five days" cadence for
Objective 2. Running weekly would drift out of sync with the data's actual
refresh cycle and add unnecessary lag.
**How to apply:** Don't change the cadence to weekly/daily without first
checking whether gridMET Drought's own update cadence has changed.

### Automation host: GitHub Actions; website: simple static site
**Decision:** Scheduled runs happen via GitHub Actions (`.github/workflows/drought-reports.yml`,
daily cron + `state.json` gate); the site is a plain HTML/CSS/JS static
site in `site/`, deployed via GitHub Pages, meant to be simple enough for
UI RCDS to take over front-end development later.
**Why:** User's explicit choice among presented options — no server to
maintain, code lives in a git repo, and handoff to RCDS is straightforward
from a static site.
**How to apply:** Keep `site/` free of any build-tool dependency (no
bundler/framework) unless RCDS or the user asks for one later.

### Boundary layers: reprojected to EPSG:4326, reduced to a single `name` column
**Decision:** `prep_boundaries.py` reprojects both source shapefiles (NAD83
Idaho Transverse Mercator) to EPSG:4326 and reduces each to just
`name` + `geometry`. It also fixes invalid geometries via `buffer(0)`
(1 of 13 groundwater districts, 42 of 350 irrigation organizations were
invalid) before writing output.
**Why:** Climate Engine's shapefile/FeatureCollection requirements: EPSG:4326
coordinates as `[lon, lat]`, and exactly one non-numeric column identifying
each polygon (all other columns must be removed). Verified `NAME` is
unique with no blanks in both source layers before dropping the rest.
**How to apply:** Re-run this script (and re-check name uniqueness) any
time the source shapefiles are replaced or extended.

### Project accounts
- Climate Engine API key linked via `https://users.climateengine.org/v1/ee_auth`
  to Google Cloud project `id-drought-reports` (valid 60 days from
  2026-09-16, renew by resubmitting the linking form).
- Earth Engine assets uploaded under a separate, auto-created EE project
  `ee-meetpalkukal` (Earth Engine's default per-account project, distinct
  from `id-drought-reports`): `projects/ee-meetpalkukal/assets/groundwater_districts`
  and `projects/ee-meetpalkukal/assets/irrigation_organizations`, both set
  to "Anyone can read".
**Why it's two different project IDs:** Earth Engine auto-creates a
personal `ee-<username>` cloud project on registration; the user created a
second, separate project (`id-drought-reports`) specifically for the
Climate Engine connector linking step. Both are legitimate — the asset ID
is what matters for API calls, not which project hosts it, as long as
sharing is public-read.
