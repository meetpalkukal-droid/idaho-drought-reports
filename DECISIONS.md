# Decisions Log

Running record of what was decided, why, and what's still open for the
Idaho Water User Drought Reports pipeline (Objective 2 of
`UI_Kukal_Narrative.pdf`). Newest entries at the top. See `README.md` for
current setup/usage instructions.

## Open items

- [x] Full batch run for both layers (363 polygons), 2026-09-16 cycle:
      **363/363 (100%) succeeded** after adding the geometry-fallback pass
      — 13/13 groundwater districts, 350/350 irrigation organizations. The
      30 irrigation organizations that failed via `feature_collection` (22
      with a server-side `'coordinates'` bug, 8 with no valid gridMET
      pixels for their AOI) all succeeded once resubmitted via
      `/reports/drought/coordinates` — see the "Geometry fallback" decision
      below for the full diagnosis and the confirmed fix, now automated in
      `run_pipeline.py`.
- [x] Create the GitHub remote (personal account) and push. Repo:
      https://github.com/meetpalkukal-droid/idaho-drought-reports (private).
- [ ] Add repo secrets (`CE_API_KEY`, `GW_ASSET_ID`, `IRR_ASSET_ID`) and
      enable GitHub Pages (source = GitHub Actions) — pushed, but these two
      manual steps in the GitHub UI are still outstanding as of last check.
- [x] Site design v1: per-org pages now show 3 curated current-conditions
      maps (USDM, short-term, long-term), plain-language drought-class
      summaries (now/3mo/1yr) for short-term, long-term, and USDM built
      from the CSVs, a hand-drawn long-term (1986-present) trend chart with
      hover tooltips, a glossary, and CSV downloads — see "Site design v1"
      decision below. No visual QA yet (no browser tool available this
      session) — worth a real look before calling it done.
- [ ] Site design open items: no live/interactive map (just Climate
      Engine's static PNGs); short-term/long-term/USDM summaries render as
      3 separate blocks rather than one integrated table; gm_* climate
      graphics (precip, ETo, temperature) aren't surfaced anywhere yet;
      no cross-report comparison view (e.g. map of all districts at once).
- [ ] `DEFAULT_MAX_IN_FLIGHT = 15` in `fetch_reports.py` is a conservative
      starting guess, not a confirmed-safe ceiling — worth tuning upward
      once the pipeline is running unattended reliably, to cut wall-clock
      time per cycle.
- [ ] Verify the GitHub Actions daily-cron + `state.json` cadence gate
      actually self-heals correctly across a missed/failed run once live.

## Decisions

### Site design v1: curated maps + our own class summaries + a hand-drawn long-term chart
**Decision:** Added `scripts/report_content.py` and rewrote `build_site.py`'s
page template around it. Each org/district page now has: 3 curated Climate
Engine map images (USDM, short-term blend, long-term blend -- out of the 14
images in each report zip, not all of them); three plain-language
drought-class summary blocks (short-term, long-term, USDM), each showing
now/~3-months-ago/~1-year-ago as a colored horizontal bar plus a one-line
"mostly X (Y% of area)" headline, computed from the `stb_/ltb_/dm_timeseries.csv`
class-histogram columns (which are fractional pixel counts, not
percentages -- normalized by row sum); a hand-built inline-SVG long-term
trend chart (1986-present, one point per water year) with diverging
reference bands and a hover tooltip (`site/assets/chart.js`); a shared
glossary explaining short-term/long-term blend, USDM, and the D0-D4 scale;
and CSV download links. Index pages got a client-side search box
(`site/assets/search.js`, no backend). Buffered-AOI orgs (see the geometry
fallback decision) get a disclosure block explaining the 3km buffer.
**Why -- color design:** Followed the dataviz skill's procedure. Drought
severity is a *polarity* (dry <-> wet around a neutral midpoint), which the
skill's color-formula.md names as the **diverging** job, not categorical --
so it does NOT go through the 8-hue categorical CVD validator (running that
validator on a sequential/diverging ramp fails by design per the skill's
own scope note). Instead each arm is a standard 5-step monotonic-lightness
ramp: the wet arm reuses the skill's documented sequential blue ramp
(`palette.md` steps 200/300/400/500/650), the dry arm is a matching 5-step
Reds progression (ColorBrewer-style, not in the skill's file since it only
documents blue as the default sequential hue -- picked to mirror the blue
arm's lightness steps), and the neutral midpoint is the skill's documented
diverging gray (`#f0efec` light / `#383835` dark). The same 11-class ramp
is reused for the USDM's 6 classes (folding its "no drought" into the
neutral gray and D0-D4 into the same 4 dry steps) so the whole site reads
as one consistent color language rather than 3 different schemes.
**Why -- what's hand-built vs. reused:** The maps stay as Climate Engine's
own PNGs (redoing geospatial rendering ourselves isn't worth it and isn't
what "explain things more" in the narrative was asking for). The
class-summary tables and the long-term chart are ours, computed from the
CSVs -- this is the concrete form of the narrative's "we will use the
graphics and data to do our own reports where we explain things a bit more
and expand on things," and it's also what let the earlier bug diagnosis
happen at all (parsing these same CSVs directly, rather than treating them
as opaque downloads, is what surfaced the vertex-count and area patterns).
**How to apply:** Any new report-page content should extend
`report_content.py` (data/logic) and the template in `build_site.py`
(markup), not hand-edit generated HTML. The color ramps are defined once in
`site/assets/style.css` as `--dc-c0`..`--dc-c10` custom properties -- change
them there, not per-usage. This is a v1 pass, not a final design -- no
visual QA has happened yet (this session had no browser/screenshot tool
available), so treat it as "structurally correct, unverified visually"
until someone actually looks at a rendered page.

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

### Geometry fallback: resubmit known-fixable failures via the coordinates endpoint
**Decision:** Added `run_geometry_fallback()` / `--geometry-fallback` to
`fetch_reports.py`, run automatically as a third pass in `run_pipeline.py`
after the normal + retry passes. For any polygon still failing with one of
two specific messages, it resubmits via `/reports/drought/coordinates`
using geometry read directly from our own `data/processed/<layer>.json`
(bypassing the EE FeatureCollection asset entirely for that one polygon):
unbuffered for the `'coordinates'`-bug category, buffered by
`GEOMETRY_FALLBACK_BUFFER_M` (3000m, in EPSG:5070) for the no-valid-pixels
category. Result: **363/363 (100%)** succeeded on the 2026-09-16 cycle.
**Why -- diagnosis:** The user pushed back on leaving 30 organizations
(23 of them large, "critical" entities like Twin Falls Canal Company,
Boise Project Board of Control, Fremont-Madison Irrigation District) as a
permanent gap, and on accepting the 7 tiny orgs as unfixable rather than
picking a nearby pixel. Investigated both properly instead of accepting
the first plausible theory:
  - Checked vertex counts, not just polygon-part counts, for the
    `'coordinates'`-bug failures: no clean threshold on either (successful
    polygons went up to 10,844 vertices; the smallest failure had only 329).
    So "too complex" alone doesn't explain it.
  - Tested submitting the exact same geometry via `/reports/drought/coordinates`
    instead of `feature_collection` for 3 of the 23 (smallest by vertex
    count, the one single-part outlier, and the largest/most complex) --
    **all 3 succeeded**, including Twin Falls Canal Company (93,200-character
    coordinate payload, 3 disjoint parts). This isolates the bug to
    `feature_collection`'s internal step of pulling a filtered EE Feature's
    geometry and re-serializing it -- not a limit on geometry complexity
    itself, and not anything wrong with our source data.
  - Tested the user's buffer idea directly: buffered the smallest (0.03 km²)
    and largest (1.36 km²) of the 7 no-valid-pixel polygons by 3km (in
    EPSG:5070) and resubmitted via coordinates -- **both succeeded**,
    confirming the fix without guessing at a value.
  - Ran the fallback against the real remaining 30 (not just the 5 test
    cases): **30/30 succeeded.**
**How to apply:** This fallback is now a permanent, automatic part of every
cycle, not a one-time manual fix -- new polygons hitting either failure
mode in future cycles will self-heal the same way. If a future polygon
fails with a *different* message than the two handled here, it will NOT be
caught by this fallback and needs the same kind of live diagnosis, not an
assumption that it's the same root cause. The 3km buffer is a deliberate
choice about what the report represents for those 7 tiny AOIs (their
gridMET-derived indices reflect a 3km-radius neighborhood, not the parcel
itself) -- worth a one-line disclosure on those specific report pages
during site design, not a detail to bury.

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
