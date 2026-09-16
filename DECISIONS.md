# Decisions Log

Running record of what was decided, why, and what's still open for the
Idaho Water User Drought Reports pipeline (Objective 2 of
`UI_Kukal_Narrative.pdf`). Newest entries at the top. See `README.md` for
current setup/usage instructions.

## Open items

- [x] Full batch run for both layers (363 polygons), 2026-09-16 cycle:
      **333/363 (91.7%) succeeded** — 13/13 groundwater districts, 320/350
      irrigation organizations. The remaining 30 irrigation organizations
      failed identically across two `--retry-failed` passes (i.e. not
      transient) — see the two decisions below for the breakdown and next
      steps.
- [ ] 22 irrigation organizations persistently fail with a server-side
      `'coordinates'` error, unchanged across 2 retries (list in the
      decision below). Next experiment if revisited: try `simplify_geometry`
      on just these polygons, since several are large multi-part entities
      (Twin Falls Canal Company, North Side Canal Company, Boise Project
      Board of Control, Fremont-Madison Irrigation District, ...).
- [ ] 8 irrigation organizations persistently get "No valid long-term
      drought blend pixels" / "No valid USDM pixels" for their AOI —
      polygons too small relative to gridMET's 4km grid. Not fixable by
      retrying or by `simplify_geometry`; needs a content decision later
      (exclude from the site with an explanatory note, or find a workaround
      like a small buffer around the polygon).
- [ ] Create the GitHub remote (personal account) and push.
- [ ] Add repo secrets (`CE_API_KEY`, `GW_ASSET_ID`, `IRR_ASSET_ID`) and
      enable GitHub Pages (source = GitHub Actions) once pushed.
- [ ] Site design: curate which Climate Engine graphics appear per page
      (current-conditions map, summary table, long-term chart per the
      narrative) instead of dumping all 14 images; add plain-language
      explanations per drought index; decide whether to rebuild the
      long-term time series chart ourselves from `ltb_eoy_timeseries.csv`
      (1985(ish)-present) rather than using Climate Engine's own chart image.
- [ ] `DEFAULT_MAX_IN_FLIGHT = 15` in `fetch_reports.py` is a conservative
      starting guess, not a confirmed-safe ceiling — worth tuning upward
      once the pipeline is running unattended reliably, to cut wall-clock
      time per cycle.
- [ ] Verify the GitHub Actions daily-cron + `state.json` cadence gate
      actually self-heals correctly across a missed/failed run once live.

## Decisions

### The built site is never committed to git; only `state.json` is
**Decision:** `.gitignore` now excludes all of `site/` except
`site/assets/` (hand-authored CSS). The GitHub Actions workflow only
`git add`s `data/reports/state.json` to decide whether anything ran this
cycle, and deploys `site/` to GitHub Pages via `actions/upload-pages-artifact`
straight from the runner's local filesystem, not from a git commit.
**Why:** Caught before it caused damage, but worth recording: the first
full 333-polygon `build_site.py` run produced **548MB across 7,012 files**
in `site/`. Committing that to git every 5 days would balloon the repo by
tens of GB per year, since git retains every historical blob version
forever (unlike a deploy artifact, which is naturally ephemeral). The
`actions/upload-pages-artifact` + `actions/deploy-pages` steps were already
in the workflow from the start and don't need git involved at all --
`site/` is entirely a reproducible build artifact of
`data/reports/extracted/`, which is itself entirely reproducible from the
API, so there's nothing to lose by never persisting either in git.
**How to apply:** Don't add new generated output under `site/` to git even
for convenience/debugging -- if something there needs to survive between
Actions runs, it belongs in `data/reports/state.json` or a similarly small,
deliberately-tracked file, not by committing the site itself.

### Submission is throttled to a max number of concurrently-running jobs, with automatic retry
**Decision:** `fetch_reports.py` now submits with a sliding window
(`--max-in-flight`, default 15): it only submits a new polygon once an
earlier one has finished, rather than firing off every polygon at once. It
also writes a status file per polygon (`data/reports/raw/<layer>/<date>/<slug>.json`)
regardless of outcome (including submit-phase errors), and a `--retry-failed`
flag reprocesses only polygons missing a `status: "success"` file for that
date. `run_pipeline.py` now runs one automatic retry pass per layer after
the main pass.
**Why:** The first full production-scale run (350 irrigation organizations,
submitted with only a 4-thread HTTP submit pool and no cap on concurrently
*running* jobs) put ~183 jobs in flight simultaneously and hit real,
confirmed failures: 41 jobs failed with Earth Engine's own
`"Too Many Requests: concurrency limit exceeded"` error
(see https://developers.google.com/earth-engine/guides/usage#concurrent_interactive_requests),
and Climate Engine's submit endpoint itself started rejecting further
requests (with a misleading `404 "Endpoint Removed"` body, not a real
deprecation) once ~186 submissions had gone out — almost certainly its own
overload protection, not an actual API change. This resolved the
"might need a quota bump someday" open item from the async-submission
decision below into a confirmed, reproducible constraint.
**How to apply:** If `--max-in-flight 15` still produces concurrency
errors at full scale, lower it further; if a full cycle proves reliable and
wall-clock time matters, raise it gradually rather than jumping back to
unthrottled. Don't remove the retry pass even if throttling seems to fully
fix concurrency errors -- 14 irrigation organizations failed on the first
run with an unrelated server-side `'coordinates'` error, independent of
concurrency (see next entry), and transient network errors are expected at
some background rate regardless.

### A server-side `'coordinates'` error persistently affects 22 geometrically complex entities
**Decision:** No code fix attempted yet; tracked as an open item for a
future session. These 350 - 30 = 320 successes are treated as the complete
2026-09-16 irrigation-organizations cycle for now.
**Why:** 22 of 350 irrigation organizations failed with a bare
`Error: 'coordinates'` from Climate Engine's own report generator (fetched
each failure's `error_link` for the full message — no stack trace beyond
that), identically across two separate `--retry-failed` passes run minutes
apart — i.e. confirmed persistent, not transient/concurrency-related (no
"Too Many Requests" text). Affects some of Idaho's largest, most
geometrically complex service areas: A & B Irrigation District, American
Falls Reservoir Dist #2, Big Wood Canal Company, Boise Kuna Irrigation
District, Boise Project Board of Control, Cambridge Ditch Co, Canyon Creek
Canal Co Inc, Eastern Idaho Water Co, East Greenacres Irrigation District,
Egin Bench Canals Inc, Farmers Cooperative Ditch Co, Fremont-Madison
Irrigation District, Granite Twin Lakes Water Users, Lost Valley Reservoir
Co, New York Irrigation District, North Side Canal Company Ltd, Salmon
River Canal Co Ltd, Settlers Irrigation District, Thurman Mill Ditch Co
Ltd, Twin Falls Canal Company, Upper Wood River Water Users Assn, Wilder
Irrigation District, Wood River Valley Irrigation District — strongly
suggests a bug in Climate Engine's handling of complex (likely
multi-part/scattered-parcel) geometries rather than anything on our end.
**How to apply:** Next experiment if revisited: try `simplify_geometry`
(the API exposes a maxError-in-meters param we haven't used yet) on just
these 22 polygons. If that doesn't help, it's worth an email to Climate
Engine support with a specific site name + its `error_link` (each one's
saved in `data/reports/raw/irrigation_organizations/2026-09-16/<slug>.json`).

### 8 irrigation organizations have no valid drought-index pixels for their AOI
**Decision:** No fix attempted; these are excluded from the 2026-09-16
cycle's output. Needs a content/design decision later, not a pipeline fix.
**Why:** Colson Creek Irrigation Co, Deer Park Water Assn Inc, Lindsey
Creek Water Assn Inc, Reflection Ridge Estates Water Association, Secluded
Acres Estates Water Assn, The Lone Spring Water Co Ltd, Williams Irrigation
Co, and one more failed with "No valid long-term drought blend pixels were
found" / "No valid USDM pixels were found for the submitted AOI and mask
settings" — persistent across retries. gridMET Drought is a 4km-resolution
grid; these are likely small polygons that don't overlap a valid pixel
center, not a bug.
**How to apply:** When doing site design, decide how to handle these:
options include a small buffer around the polygon before querying (changes
what "the report" represents, so worth a deliberate choice, not a silent
pipeline tweak), or simply noting on the site that a jurisdiction is too
small for gridMET's resolution and pointing users to the nearest larger
enclosing district's report instead.

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
