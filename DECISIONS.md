# Decisions Log

Running record of what was decided, why, and what's still open for the
Idaho Water User Drought Reports pipeline (Objective 2 of
`UI_Kukal_Narrative.pdf`). Newest entries at the top. See `README.md` for
current setup/usage instructions.

## Open items

- [x] Every report's "Now" data was showing gridMET Drought's PREVIOUS
      pentad, not the current one, for a completely different reason than
      the missing-districts issue below: requesting `end_date` exactly
      equal to the latest published date truncates Climate Engine's
      response back one full pentad. Confirmed via a direct A/B test and
      fixed by padding the requested end_date a few days past the target
      pentad -- see "end_date truncation bug" decision below. This
      affected ALL 65 reports' short-/long-term blend data, not just the
      6 that were missing entirely.
- [x] 6/13 groundwater districts (Bingham, Carey Valley, Galena, Henrys
      Fork, Raft River, South Valley) 404'd on the live site after the
      first data-gated run -- root cause confirmed (transient failures
      that survived the single retry pass) and fixed with a second retry
      pass plus a visible failure log; see "Second retry pass and a
      visible failure log" decision below. Needs one more forced run to
      actually backfill these 6 on the live site.
- [x] Irrigation organization scope cut to 65 total polygons (13
      groundwater + 52 irrigation), from 363 -- see "Irrigation
      organization scope cut" decision below for the full rationale.
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
      https://github.com/meetpalkukal-droid/idaho-drought-reports.
      GitHub Pages requires either a paid plan or a public repo for a
      private-repo account -- user chose public (the site itself is meant
      to be public anyway; verified no secrets exist anywhere in git
      history before flipping visibility). Repo secrets (`CE_API_KEY`,
      `GW_ASSET_ID`, `IRR_ASSET_ID`) added, Pages source set to
      "GitHub Actions".
- [x] First Actions run, push blocker found: the "Run pipeline" step
      itself exited 0 (success) both times it ran manually, but that's
      exit-code success, NOT "processed all 363 polygons" -- see the next
      item, this was a red herring at the time since the push failure hid
      the real state. The actual push blocker was never permissions or
      branch protection (both real fixes/checks, but not the cause). The
      real error, from the step's own log text: `! [rejected] main -> main
      (fetch first)` -- a plain git non-fast-forward rejection. The job
      checks out `main` at the *start* of its run; this session was
      actively pushing commits (the Bokeh chart work) directly to `main`
      during that exact window both times, so by the time the job tried
      to push its state.json commit, the remote had moved on without it.
      Self-inflicted by concurrent development, not a real production
      scenario -- but fixed the workflow to `git fetch && git rebase
      origin/main` before pushing regardless, so it's resilient to any
      future concurrent push (a
      collaborator, a second triggered run) rather than assuming it'll
      never happen again.
- [ ] First Actions run that actually pushed+deployed (2026-09-17,
      16:10-16:39): site went live at
      https://meetpalkukal-droid.github.io/idaho-drought-reports/, but
      only **13/13 groundwater districts and ~78/350 irrigation
      organizations** made it -- and the 78 are a clean, gap-free
      alphabetical run (Aberdeen through "Enterprise Irrigation
      District"), not scattered failures like the concurrency-limit
      errors from local testing. That signature means the *process*
      stopped partway through an ordered loop -- a timeout, crash, or
      resource limit -- not per-request failures (those are already
      tolerated and would leave gaps, not a clean cutoff). Root cause not
      yet confirmed: the job's own console log isn't readable without
      repo admin auth, and `data/reports/raw/` (which would show the
      real per-org error messages) is intentionally gitignored, so there
      was no way to diagnose after the fact. Added an
      `actions/upload-artifact` step (`if: always()`, 5-day retention) to
      capture `data/reports/raw/` on every future run specifically so
      this is diagnosable next time. Root cause since confirmed (see
      "Irrigation organization scope cut" decision below): Climate
      Engine's 200/hr and 500/day rate limit applies unconditionally to
      all accounts, including ones with a linked Earth Engine project --
      363 polygons cannot fit in that budget even with zero polling
      overhead (363 x (1 submit + 1 download) = 726 requests alone).
- [x] Site design v1: per-org pages now show 3 curated current-conditions
      maps (USDM, short-term, long-term), plain-language drought-class
      summaries (now/3mo/1yr) for short-term, long-term, and USDM built
      from the CSVs, a hand-drawn long-term (1986-present) trend chart with
      hover tooltips, a glossary, and CSV downloads — see "Site design v1"
      decision below.
- [x] Visual QA pass (see "Visual QA" decision below): found and fixed one
      real bug (neutral-gray class color nearly invisible against the page
      background, making a real "near normal" status look like missing
      data); ruled out an apparent mobile-overflow bug as a screenshot
      tooling artifact, not a real one.
- [x] All 14 Climate Engine report graphics were shown per page for a
      time (was 3 curated maps) -- since superseded, see below: the "All
      Climate Engine graphics" section holding the other 11 was removed
      again per user direction once the Bokeh rebuilds + class-evolution
      charts made it redundant clutter rather than useful reference.
- [x] Interactive Bokeh charts rebuilding 5 of Climate Engine's own gm_*/
      ltb_eoy graphics from the underlying CSVs (per user direction: use
      Bokeh for all charts) -- see "Interactive charts rebuilt in Bokeh"
      decision below. Validated against Climate Engine's actual published
      numbers, not just visually.
- [x] Continuous drought-class-evolution charts (stacked area, full
      ~390-day window) added -- the one thing Climate Engine's own report
      never shows at all, see "Add drought-class-evolution charts" commit.
- [x] Full-width "modern sleek professional" redesign, homepage
      map/search/list selector, and expanded lay-person explainer text --
      see "Redesign: full-width layout + homepage selector + expanded lay
      content" decision below. Visually QA'd in light mode, dark mode, and
      mobile width (~500px) for both the homepage and a report page; no
      bugs found.
- [x] Cadence gate replaced with a live data-availability check instead of
      a fixed day-count guess -- see "Data-driven cadence gate" decision
      below. Also surfaced and cleared up a real gap: state.json's
      "last_run" had drifted to a manual force-run from 2026-09-18 that
      was never re-verified against the live site afterward.
- [x] Rewrote all on-page copy (glossary, section intros, per-group
      background info, footer notes) to plain, direct language --
      dropped rhetorical-question headers, "X isn't one thing" openers,
      hedging parentheticals, and indirect "it's the index that..."
      constructions. No factual/numeric content changed. See "Plain-
      language copy pass" decision below.
- [x] Major report-page redesign: paired current-conditions maps with
      their own area data, grouped drought-class legend, interactive
      hover-for-area class bars, per-section background info (USDM/short-
      term/long-term), on-chart trend lines/captions (including a real
      Mann-Kendall trend on the long-term index chart, not just a time
      series), sentence-based percentile meters with a pin-adjacent
      percentile label, 2-column glossary, larger base text, CSV downloads
      removed -- see "Report page redesign: pairing, interactivity, trend
      integration" decision below.
- [x] "This year vs. average" and "Long-term climate trends" stat tables
      replaced with visual percentile meters and directional trend tiles
      -- see "Visual stat displays" decision below.
- [x] Chart sizing/legend fix: all Bokeh charts now use `frame_height`
      (plot area only) instead of `height` (total box including chrome),
      and the normal-band/water-year-trend charts' legends moved outside
      the plot frame -- see "Chart sizing" decision below.
- [x] Climate context charts (ETo/precipitation/temperature) stacked
      full-width vertically instead of a multi-column grid, and their
      historical bands (already real percentile data, P5-P95/P25-P75 from
      actual gridMET daily values) explicitly labeled as such in the chart
      legend and hover tooltip, not just described in the prose explainer
      -- see "Offline design workflow" decision below, including the
      date-rollover build gotcha found while doing this.
- [ ] Site design open items remaining: no live/interactive current-
      conditions map (the 3 hero maps are still Climate Engine's static
      PNGs -- rebuilding those would mean redoing raster/geospatial
      rendering ourselves, out of scope so far); no cross-report
      comparison view beyond the new homepage selector map/search/list.
- [ ] `DEFAULT_MAX_IN_FLIGHT = 15` in `fetch_reports.py` is a conservative
      starting guess, not a confirmed-safe ceiling — worth tuning upward
      once the pipeline is running unattended reliably, to cut wall-clock
      time per cycle.
- [ ] Verify the GitHub Actions daily-cron + `state.json` cadence gate
      actually self-heals correctly across a missed/failed run once live.

## Decisions

### end_date truncation bug: pad past the target pentad, never match exactly
**Decision:** `fetch_reports.py`'s `run_layer()` and `run_geometry_fallback()`
now take two separate date parameters: `end_date` (used only for local
folder naming -- `extracted/<layer>/<end_date>/` -- and the site's
displayed report period) and a new `api_end_date` (what's actually sent
to Climate Engine as the request's `end_date` field; falls back to
`end_date` if not given, for backward-compatible manual/CLI use).
`run_pipeline.py` now sets `run_date = latest_available` (the true pentad
date, from `get_latest_gridmet_drought_date()`) but
`api_end_date = latest_available + 3 days`.
**Why:** User noticed the site's "Short-term conditions: Now" date
(2026-09-07) looked stale next to the gridMET Drought max date we'd just
confirmed (2026-09-12), and separately found a real Climate Engine PDF
report (Arizona State Office, a genuine reference example) where the
report's title date and its "Current" table date matched exactly with no
lag -- which contradicted the "this is just an inherent lag, matches
Climate Engine's own site" explanation given initially. That explanation
was wrong; investigated properly instead of standing by it:
  - Downloaded the actual report generated earlier this session (Bingham
    Ground Water District, requested with `end_date=2026-09-12` --
    exactly matching the raw dataset's own published max). Its
    `stb_timeseries.csv`/`ltb_timeseries.csv` end at 2026-09-07, and
    Climate Engine's own `ltb_table` image literally prints "Current**
    (2026-09-07)" -- five days short of what was requested.
  - Ran a direct A/B test: the exact same polygon, submitted with NO
    `end_date` parameter at all. Climate Engine's own echoed default
    resolved to `"end_date":"2026-09-15"`, and *that* report's
    `stb_timeseries.csv`/`ltb_timeseries.csv` correctly extended through
    2026-09-12 -- proving the 09-12 pentad was genuinely available and
    returnable the whole time, and that requesting `end_date` as an exact
    match to the latest published date is what causes the API to
    truncate one pentad early (an off-by-one/exclusive-boundary quirk in
    Climate Engine's own filtering, not a data-availability limit).
  - This also retroactively explains why the *original* pre-session
    pipeline code (which used wall-clock `date.today()` as `end_date`,
    always naturally later than any real pentad boundary) never hit this
    bug -- only today's new precise-pentad-date gating logic introduced
    the exact-match condition that triggers it.
**How to apply:** Never pass `get_latest_gridmet_drought_date()`'s return
value directly as the API request's `end_date` -- always pad it forward
(3 days is confirmed sufficient; matches Climate Engine's own observed
default behavior). If a future change ever removes this padding, the
symptom to watch for is every report's blend "Current" date reading one
pentad older than the dataset's actual published max.

### Second retry pass and a visible failure log
**Decision:** `run_pipeline.py` now runs `run_layer(..., retry_failed=True)`
**twice** per layer (once before `run_geometry_fallback`, once after),
each preceded by a `RETRY_BACKOFF_S` (45s) pause, instead of a single
immediate retry. A new `fetch_reports.list_failed_sites(layer, run_date)`
is called at the end of each layer's passes; anything still missing is
printed as a `WARNING` in the Action log and written to a new small
tracked file, `data/reports/last_run_failures.json` (`{"groundwater_districts":
[...], "irrigation_organizations": [...]}`), committed alongside
`state.json` in the same workflow step.
**Why:** The first run under the new data-driven cadence gate (2026-09-21)
deployed with **6 of 13 groundwater districts missing** (Bingham, Carey
Valley, Galena, Henrys Fork, Raft River, South Valley) -- caught because
the user hit a 404 on one directly. Investigated properly instead of
guessing:
  - The pattern wasn't a clean alphabetical cutoff (present:
    Aberdeen/Big Lost River/Bonneville-Jefferson/Jefferson Clark/Madison/
    Magic Valley/North Snake; missing: the other 6, scattered through the
    alphabet) -- ruling out a process-stopped-partway-through failure like
    the historical "~78/350" incident, and pointing at real per-request
    failures instead.
  - Couldn't inspect the run's actual raw-status Actions artifact
    (`raw-status-<run-id>`) -- downloading it requires a GitHub token via
    an authenticated API call, and neither `gh` CLI nor a `GITHUB_TOKEN`
    is available in this environment. This is the second time this gap has
    mattered (see the original "~78/350" incident) -- the new
    `last_run_failures.json` exists specifically to not need artifact
    access to answer "did anything fail" going forward.
  - Directly resubmitted the exact failing polygon (Bingham Ground Water
    District) against the live API with no special handling: it
    succeeded in ~2 minutes with **zero code changes**, on a **plain**
    `feature_collection` call (not the coordinates-endpoint workaround the
    two other known failure categories need). This confirms it wasn't a
    geometry problem at all -- just a transient failure (concurrency,
    a momentary EE hiccup) that happened to still be failing when the
    pipeline's single retry pass ran, immediately after the first.
**How to apply:** If sites are still missing after two retries plus the
geometry fallback, check `data/reports/last_run_failures.json` first --
don't assume it needs a new fallback category without evidence. If this
recurs at a meaningful rate even with two retries, consider a longer
`RETRY_BACKOFF_S` or a third pass before assuming it's a new, different
failure mode needing its own diagnosis (the way the two `--geometry-fallback`
categories were originally found).

### Data-driven cadence gate: check Climate Engine directly, don't guess
**Decision:** `run_pipeline.py` no longer gates on "has it been >= 5 days
since our last successful run" (a blind day counter). It now calls a new
`fetch_reports.get_latest_gridmet_drought_date()`, which hits Climate
Engine's own `GET /metadata/dataset_dates?dataset=GRIDMET_DROUGHT`
endpoint and reads the real `max` date gridMET Drought is published
through. `data/reports/state.json` now stores that actual data date
(`last_data_date`) instead of a run date (`last_run`); the pipeline runs
only when the live `max` date differs from what's stored, i.e. a genuinely
new pentad has been published. `run_date` everywhere downstream (the API
`end_date` param, the local `extracted/<layer>/<run_date>/` folder name,
and the "report period ending" text on the site) is now this same real
data date, not `date.today()`.
**Why:** User asked directly for "a system where we know exactly when new
data is available," not an approximation. Confirmed live via a direct API
call (`curl .../metadata/dataset_dates?dataset=GRIDMET_DROUGHT`) that this
endpoint is real and returns e.g. `{"min": "1980-01-05", "max":
"2026-09-12"}` -- and that gridMET Drought's actual publication lag is
larger than assumed: on 2026-09-21, plain `GRIDMET` (the raw met dataset)
was current through 2026-09-17 (4 days behind), but `GRIDMET_DROUGHT` (the
derived drought product, needs a full pentad of the raw data to compute)
was only current through 2026-09-12 -- 9 days behind wall-clock, a full
pentad behind raw gridMET itself. A fixed "5 days since last run" counter
has no way to detect this kind of lag; it would confidently try to fetch
data that doesn't exist yet, or sit a day late/early relative to the
dataset's actual publication moment.
**Also fixes a real bug as a side effect:** using the actual data date as
`run_date` (rather than `today.isoformat()`) means the local
`extracted/<layer>/<run_date>/` folder name always matches what
`build_site.py` expects by default -- eliminating the exact class of
footgun already documented in "Offline design workflow" below (where a
local rebuild silently no-op'd because the system date had moved past the
cached data's folder name).
**How it fails safely:** No silent fallback to the old guess-based logic
was added on purpose -- if the metadata call itself fails (network issue,
API change), the run fails loudly and visibly in the Actions log rather
than quietly reverting to an approximation, and the daily cron retries
the next day regardless.
**How to apply:** Don't reintroduce a day-count gate. If a different
dataset's cadence ever needs the same treatment, follow the same pattern:
find its real `/metadata/dataset_dates` `dataset=` identifier by testing
candidates against the live API (there's no enum in the OpenAPI spec, and
guesses like `gridmetdrought_pentad_4000` -- the dataset's *page slug* on
climateengine.org -- return `"Invalid dataset"`; `GRIDMET_DROUGHT` is the
correct query-param value), don't assume the docs page slug is the query
value.

### Plain-language copy pass: remove AI-sounding phrasing
**Decision:** Rewrote every user-facing text block on the report page
(the glossary in `report_content.py`'s `EXPLAINER_HTML`, the three
per-section background paragraphs, and the section intros/footer/hero
text in `build_site.py`'s templates) to plain, direct sentences, per
explicit user request ("redo all language on the webpage to not sound
AI-like... straightforward and plain language while being technically
accurate"). Patterns removed:
  - Rhetorical-question headers answered in the same breath (e.g. "Why
    these maps and charts, not just 'is it a drought year'?") -> replaced
    with a plain descriptive header ("Why short-term and long-term are
    shown separately") stating the point directly.
  - "X isn't one thing" and similar cliché openers.
  - Hedging parentheticals like "(not a direct measurement of X, but a
    well-established way to Y)" -> restated as a direct sentence.
  - Indirect constructions ("it's the index most likely to...", "it's also
    the index that...") -> restated with the subject doing the thing
    directly.
  - The repeated "Use it to answer 'how has it been lately?'" quote-gimmick
    used identically in two glossary entries -> dropped in favor of just
    stating what each blend shows.
  - Reduced but did not eliminate em dashes -- kept where they're doing
    real work (a single aside in a sentence), removed where stacked
    (multiple em-dash clauses in one sentence).
**Why -- no factual changes:** Every number, formula, and technical claim
(PDSI/Z-Index/SPI definitions, USDM's NDMC/NOAA/USDA production process,
water-year convention, trend methodology) is unchanged from the
already-accurate versions written earlier this session -- this pass only
touched sentence construction and word choice, verified by rebuilding and
re-reading the rendered page rather than just diffing the Python source.
**How to apply:** Any new user-facing copy added to this site should
default to short, direct declarative sentences -- state the fact, then
(if needed) the reason, rather than opening with a question or a hedge.
Code comments and docstrings are exempt (not user-facing); this pass only
touched HTML/template strings.

### Report page redesign: pairing, interactivity, trend integration
**Decision:** A large, single coordinated redesign covering most of the
report page, per a detailed user spec given across several messages
before any implementation started (user explicitly said "don't do
anything yet, keep listening" while giving the full list). Changes:
  - **Paired current-conditions groups** (`_render_condition_group` in
    `build_site.py`, `.condition-group` in CSS): each map (short-term,
    long-term, USDM) now sits side by side with its own area
    breakdown/bars, instead of 3 maps in a row followed by 3 separate
    summary blocks below. Collapses to 1 column under 820px.
  - **Grouped legend** (`_render_legend`): dry classes cluster together
    (mild-to-severe, D0->D4) and wet classes cluster together, with a
    "Drought"/"Wet" group label, instead of one flat 11-swatch row.
  - **Interactive class bars**: `.class-bar-seg` now carries
    `data-tooltip`, shown via a custom CSS `::after`/`::before` tooltip on
    hover/focus (not just the native `title=` fallback), with
    `.class-bar:has(.class-bar-seg:hover)` lifting the container's
    `overflow:hidden` so the tooltip isn't clipped.
  - **Per-section background info**: `SHORT_TERM_BACKGROUND_HTML` /
    `LONG_TERM_BACKGROUND_HTML` / `USDM_BACKGROUND_HTML` in
    `report_content.py` -- real, specific methodology context (USDM's
    NDMC/NOAA/USDA production process and Thursday update cadence; what
    each blend actually combines) shown inline in each condition group,
    not only in the glossary further down.
  - **Trend lines/captions integrated near each chart**, replacing the
    separate "Long-term climate trends" tile-grid section entirely:
    `long_term_index_figure` and `water_year_trend_figure` now compute
    and return their Mann-Kendall trend(s) alongside the figure (not just
    a bare figure), so `build_site.py` reuses the exact same numbers for
    both the on-chart dotted trend line and an HTML caption underneath
    (`_trend_caption`). Tmax/Tmin/net-water-balance trends (no chart of
    their own) surface as trailing notes on the relevant percentile-meter
    rows instead. Each of the 4 climate-context charts also gets a
    one-line framing question above it (`.chart-question`).
  - **Percentile meters rewritten as sentences** (`_percentile_meter_row`):
    "High temp was 62.2°F this year to date — 4.7°F above the 57.5°F
    average, the 100th percentile on record," not a fragment. The
    percentile number is now a floating label positioned right above the
    pin itself (clamped to 6-94% so it stays on-track near the edges),
    not fixed at the bar's horizontal midpoint -- the midpoint position
    read as if the percentile value were always in the middle of the
    range, which isn't what it means.
  - **Temperature/water-balance summary cards side by side**
    (`.pct-card-grid`, `repeat(auto-fit, minmax(420px, 1fr))`) instead of
    stacked full-width, and the **glossary is now 2 CSS columns**
    (`columns: 2`, each entry wrapped in `.glossary-entry` with
    `break-inside: avoid`) instead of one narrow 820px column inside a
    1400px page -- both address "a whole lot of white space... has to
    scroll vertically a lot."
  - **Base font size** raised from 112.5% to 118.75% (~19px) -- "make all
    text larger."
  - **CSV data-download section removed** entirely (`{csv_links}` and the
    "Data" `<h2>` deleted from `PAGE_TEMPLATE`).
**Why -- single coordinated pass, not incremental:** The user explicitly
queued the full list across 4 messages before saying "go ahead with all,"
specifically to avoid re-doing structural work piecemeal. Implemented in
dependency order: data layer (`climate_charts.water_year_mean_series`, the
one genuinely new computation needed -- Tmean has no water-year trend
anywhere else since Climate Engine's own `gm_wy_timeseries.csv` doesn't
carry it) -> chart builders (`bokeh_charts.py`) -> content
(`report_content.py`) -> page assembly (`build_site.py`) -> CSS.
**Verified, not assumed:** Full visual QA pass (light mode, dark mode,
mobile ~500px) via the established headless-Chrome screenshot-then-Read
loop confirmed: paired groups render and collapse correctly; the grouped
legend actually clusters as 3 visual rows; trend captions carry correct
red/blue semantics per variable (re-checked explicitly, since this exact
bug -- literal rising/falling instead of a per-variable "which direction
is bad" -- was caught and fixed once already this session, see "Visual
stat displays" below); percentile pin labels stay on-track and readable
even at the mobile-width extremes (0th/100th percentile rows).
**How to apply:** `CONDITION_GROUPS` in `build_site.py` is now the single
place that defines the 3 paired current-conditions groups (map prefix,
title, description, background HTML, CSV name, class scheme) -- add a 4th
group there, not by hand-editing template HTML. Any new trend number
should go through `_trend_caption()` for consistent formatting/color
logic, not a one-off implementation.

### Chart sizing: `frame_height` (plot area) instead of `height` (total box)
**Decision:** All Bokeh figures (`_base_figure` and `class_evolution_figure`'s
direct `figure()` call) now set `frame_height=FIG_FRAME_HEIGHT` (320px, the
plotted-data rectangle only) instead of a fixed total `height`. The
normal-band charts' (`normal_band_figure`) and the water-year-trend
chart's legends, which previously overlapped the top-left corner of the
plot, are now moved outside the frame into a compact horizontal strip
below via a new `_place_legend_below()` helper (`fig.add_layout(legend,
"below")`).
**Why:** User asked for the climate-context charts to be "the same
dimensions as the Long-term trend chart." Direct DOM measurement (a JS
probe injected into the page, `getBoundingClientRect()` on every
`.bokeh-chart` div) proved the outer boxes were already pixel-identical
(828x402) even before this change -- all charts share the same `FIG_HEIGHT`
constant. The real cause of the "different size" perception was that
`normal_band_figure`'s in-frame legend (4 rows after the percentile
labeling below) visually ate into its plotted area, while the Long-term
chart has no legend at all and uses its full box for data. Switching to
`frame_height` guarantees the actual charted rectangle is equal-sized
across every chart regardless of legend/title/toolbar chrome, which is
what a viewer actually perceives as "chart size" -- more so than the outer
container box.
**How to apply:** Any new chart type added to `bokeh_charts.py` should go
through `_base_figure` (inherits `frame_height` automatically) rather than
calling `figure()` directly with its own `height`/`width`. If it has a
legend, call `_place_legend_below(fig)` after all glyphs are added so it
doesn't silently start overlapping data again.

### Visual stat displays instead of raw-number tables
**Decision:** `_render_summary_tables()` (temperature/water-balance
summary) now renders each variable as a horizontal percentile meter
(`.pct-row`/`.pct-meter`) instead of a `<table>` row: current value, diff
vs. average, a track colored with the site's diverging drought palette, a
pin at this year's percentile rank, and a marker at the 50th percentile.
`_render_trend_table()` (long-term climate trends) now renders a grid of
directional stat tiles (`.trend-tile`) with an up/down arrow, colored red
or blue, instead of a table row with a `p=` column.
**Why -- color semantics needed a variable-specific flag, not a fixed
rule:** A naive "high value = red, low value = blue" (or "rising trend =
red, falling = blue") is wrong for roughly half these variables. Red is
meant to mean "drought-amplifying," which is the HIGH end for temperature
and evaporative demand (hotter / thirstier atmosphere = concerning) but
the LOW end for precipitation and net water balance (less rain =
concerning). Every percentile meter takes an explicit
`concern_high: bool` and its own `low_label`/`high_label` text (e.g.
"Lower demand"/"Higher demand" for ETo, not a generic "wetter"/"drier"
that wouldn't fit); every trend tile takes an explicit `bad_direction`
("up" or "down") and colors relative to whether the actual slope matches
it, not relative to literal sign. **Caught via visual QA, not assumed
correct on the first pass:** the first build had Precipitation's and
Precip-Evap-demand's *declining* trends rendered in blue (reassuring)
instead of red (concerning) because the initial version colored by literal
rising/falling; fixed by adding the `bad_direction` parameter before this
shipped.
**How to apply:** If a new variable is added to either function, explicitly
decide and set its concern direction (which end/sign is drought-amplifying
for THAT variable) -- never reuse the literal high/rising=red default, and
never reuse the temperature-specific "cooler"/"warmer" footer labels for a
non-temperature variable.

### Offline design workflow: rebuild from cached data, no Actions run needed
**Decision:** Design/layout iteration (CSS, chart labeling, templates) now
happens entirely locally: `python scripts/build_site.py <run_date>`
rebuilds `site/` in seconds from the already-cached
`data/reports/extracted/<layer>/<run_date>/` payloads (no API calls), then
`python3 -m http.server 8899` from `site/` serves it for a browser or the
headless-Chrome screenshot QA loop. GitHub Actions is only needed to fetch
*new* drought data (next 5-day cycle) or to actually deploy, never just to
preview a design change.
**Bug found and fixed while setting this up:** `build_site.py`'s CLI
defaults `run_date` to `datetime.date.today()`, but the cached extracted
data is dated `2026-09-16`; once the real calendar date rolled over to
`2026-09-17` mid-session, `build(run_date="2026-09-17")` silently `continue`d
past every layer (no matching `data/reports/extracted/<layer>/2026-09-17/`
directory) and left every per-org report HTML untouched from an earlier
build -- with **exit code 0 and no error output**, since the skip is a
silent `continue`, not a raised exception. Two rebuilds' worth of changes
(chart height, then percentile-band legend labels) appeared to do nothing
because of this -- caught by checking the output HTML file's own mtime
against the edit time, not just trusting a clean exit code.
**How to apply:** For any local rebuild, pass the actual extracted-data
date explicitly: `python scripts/build_site.py 2026-09-16` (or whatever
`ls data/reports/extracted/groundwater_districts/` shows) -- don't rely on
the no-arg default once real time has moved past the cached data's date.
If this bites again, consider having `build()` warn loudly (not just
`continue`) when a layer's extracted directory for the given `run_date`
doesn't exist at all.

### Redesign: full-width layout + homepage selector + expanded lay content
**Decision:** Combined user request: "use the full page not just the
center column... give ample space to graphics and make it a theme that is
modern sleek and professional... the website may be used by people who
need larger text/graphics etc. delete 'All Climate Engine graphics'
section. and add as much detail as possible for people (lay) to
understand the results," plus a follow-up mid-turn ask to "give options on
the main page to select spatial entity via a search bar, map itself, and a
list." Implemented as:
  - `site/assets/style.css` rewritten: Inter (Google Fonts) at an 18px
    base (`html { font-size: 112.5% }`) for readability by users who need
    larger text; a `.wide` (1400px) layout class replacing the old
    centered-column container, with prose-width (`760px`) kept only on
    actual reading blocks (glossary, disclosures, intro/section text) so
    long lines of body text stay readable inside the wider page; a navy
    (`#0f2e4c`) header/nav; card treatment (shadow, radius, padding) on
    maps, summaries, charts, tables; wider grid minmax on map/chart grids
    ("ample space to graphics"); full dark-mode token block. The validated
    `--dc-c0`..`--dc-c10` diverging drought palette values were kept
    unchanged.
  - `scripts/build_site.py`: removed the `ADDITIONAL_GRAPHICS`
    ("All Climate Engine graphics") section and its render call entirely,
    per explicit instruction ("delete 'All Climate Engine graphics'
    section"). Added a shared `_render_header()` partial and rewrote all
    three page templates (`PAGE_TEMPLATE`, `INDEX_TEMPLATE`,
    `HOME_TEMPLATE`) around the new `.wide`/card layout, plus a new
    homepage hero + selector (search box, Map/List tabs).
  - `scripts/report_content.py`'s `EXPLAINER_HTML` substantially expanded
    from a short glossary into a full lay-person walkthrough: why
    short-term/long-term are shown separately, what PDSI/Z-Index/SPI
    actually measure, what a percentile means, the water-year convention,
    how to read the normal-range climate charts, ETo/evaporative demand,
    water balance, and what trend significance (p-value) means --
    "add as much detail as possible for people (lay) to understand."
  - `scripts/prep_boundaries.py`: added `write_map_geojson()`, producing a
    single simplified (`MAP_SIMPLIFY_TOLERANCE = 0.002`deg,
    ~150-200m at Idaho's latitude) `data/processed/map_boundaries.json`
    combining both layers (759KB vs. 4.8MB unsimplified) with a `layer`
    and `slug` property per feature, purpose-built for a lightweight
    homepage Leaflet map.
  - `site/assets/home.js` (new): loads `map_boundaries.json` once and
    drives all three selector modes from the same data -- a live-filter
    search box (name substring match, up to 25 results with a
    groundwater/irrigation type badge), a Leaflet map (both layers
    colored distinctly, hover tooltip, click-to-open-report), and a
    grouped/sorted list view -- switchable via tabs, satisfying "search
    bar, map itself, and a list" as three views over one dataset rather
    than three separate implementations.
**Why -- map data choice:** Reused the already-cut 65-polygon set (see
"Irrigation organization scope cut" below) for the homepage map rather
than the full 363-feature source shapefiles -- the map only needs to link
to reports that actually exist.
**Visual QA:** Full pass via the established headless-Chrome
screenshot-then-Read loop (see "Visual QA" decision below): homepage
(hero, search results, map with both layers clickable, list view grouped
by type) and a report page (header through footer, all Bokeh charts,
glossary) each checked in light mode, dark mode (CSS override injection),
and at the confirmed ~500px mobile floor -- including a full-page 500x7000
capture cropped into sections to check the Bokeh charts and stat tables
specifically, since those are the most overflow-prone elements. No bugs
found in this pass (contrast with the pre-redesign v1 QA pass, which did
find and fix a real neutral-gray-invisibility bug -- this suggests the
card/token system introduced here is more robust, not that QA was
skipped).
**How to apply:** The three homepage selector modes share one data file
(`map_boundaries.json`) and one JS module (`home.js`) -- if the org/district
list changes, only `prep_boundaries.py`'s `write_map_geojson()` output
needs to regenerate; don't hand-maintain a separate list anywhere else.

### Irrigation organization scope cut: 363 -> 65 total polygons
**Decision:** `scripts/prep_boundaries.py` now filters
`irrigation_organizations` down to a hardcoded 52-name
`IRRIGATION_ORG_PRIORITY_LIST`: the 7 Surface Water Coalition members
(A&B, American Falls Reservoir Dist #2, Burley, Milner, Minidoka, North
Side Canal Co, Twin Falls Canal Co -- the senior surface-water right
holders on the Snake River central to the groundwater-surface water
conflict this whole project is about) plus the next 45 largest
non-SWC/non-NPS organizations by acreage. Combined with all 13 groundwater
districts (unchanged), that's **65 total polygons**, down from 363.
`NATIONAL PARK SERVICE` was explicitly excluded from the acreage ranking
even though it would have placed #16 -- it's a place-of-use entry, not an
operational irrigation organization.
**Why:** Confirmed via Climate Engine's own quota policy page (quoted
verbatim): *"The API imposes rate limits of 200 requests/hour and 500
requests/day for all users (both quota limited and non-quota accounts)."*
This is a separate, unconditional limit from the EE *compute* quota that
linking our own Earth Engine project removes -- initially conflated the
two into one thing, which was the wrong read. The math makes 363 polygons
architecturally impossible regardless of code changes: 363 x (1 submit +
1 download) = 726 requests, already 45% over the daily budget with *zero*
polling overhead. This was confirmed empirically, not just from the docs:
a live run cut off cleanly at ~78/350 (not the scattered pattern of the
earlier concurrency-limit errors), and a follow-up single-polygon test
*with zero concurrent load* still got rate-limited account-wide on both
`/reports/drought/feature_collection` and `/reports/drought/coordinates`,
while a lightweight endpoint (`/home/user/quotas`) worked fine --
confirming it's specifically the reports endpoints being throttled, not a
general outage.
**Rejected alternatives:**
  - *Spread 363 across the 5-day window (~73/day)* -- would have kept
    full coverage, since 5 days x 500/day = 2500 total budget over a
    cycle vs. 500 for a single active day. User explicitly rejected this
    in favor of cutting scope to fit one active day, given the pipeline
    only runs once per cycle (the cadence gate) and the user wanted the
    full set available together rather than trickling in.
  - *Email Climate Engine for a rate-limit increase* -- user declined for
    now (skip, not permanently ruled out).
  - *Google Earth Engine paid/commercial tier* -- doesn't apply; the
    200/hr-500/day limit is Climate Engine's own API gateway, unrelated
    to what's paid to Google. There's a separate commercial "Climate
    Engine" entity (climateengine.com, distinct from the free academic
    climateengine.org) offering enterprise-tier APIs with unpublished
    pricing (contact-sales only) -- plausible but unverified as a real
    fix, and a real-money commercial decision the user chose not to
    pursue for this project.
  - *Include all 52 "Irrigation District"-named entities regardless of
    acreage* -- rejected once the actual size distribution was checked:
    they range from 466 to 280,410 acres, so "District" alone isn't a
    reliable significance signal (would add 48 more, mostly tiny, at
    the cost of pushing out larger non-district companies).
**How to apply:** If the org list is ever revisited, regenerate from
`IRRIGATION_ORG_PRIORITY_LIST` in `prep_boundaries.py` -- don't hand-edit
`data/processed/irrigation_organizations.json` directly, it's a build
output. The existing Earth Engine asset (`IRR_ASSET_ID`) still contains
all 350 features; it was never re-uploaded, since `feature_collection`
filtering by name only needs the asset to *contain* the target features,
not be limited to them -- only the local name list drives which ones get
requested.

### Interactive charts rebuilt in Bokeh, validated against Climate Engine's real numbers, not just eyeballed
**Decision:** Added `scripts/climate_charts.py` (data prep: water-year
alignment, historical percentile bands by day-of-water-year, trend
statistics) and `scripts/bokeh_charts.py` (figure builders), replacing the
hand-drawn SVG long-term chart and adding 4 new interactive charts + 2
summary tables + 1 trend-significance table, rebuilding 5 of Climate
Engine's own `gm_*`/`ltb_eoy` graphics from the same underlying CSVs (user
direction: "we will use bokeh library for all charts"). One shared
BokehJS `<script>` (CDN) per page, one `components()` call per page
covering all of that page's figures.
**Why -- validated, not assumed:** Rather than trust the numbers looked
plausible, every statistic was checked against Climate Engine's own
published values from the same report (the `gm_wb_summary`/`gm_temp_summary`/
`gm_long_term_trends` table images):
  - Found and fixed a real off-by-one bug in water-year assignment (USGS
    convention: an Oct-Dec date belongs to the *following* calendar year's
    water year -- e.g. Oct 2025 is WY2026, not WY2025). Caught because the
    "current water year" trace came back empty before the fix.
  - Cumulative precipitation matched Climate Engine's number exactly
    (11.18 in) once the water-year fix was in.
  - The "current year vs. average" summary tables initially used a
    full-water-year historical average, which didn't match Climate
    Engine's numbers (13.90 vs. our 14.78 for precip) -- switched to
    truncating the historical comparison to the same day-of-water-year the
    current (partial) year has reached, which then matched near-exactly
    (13.93 vs. 13.90) for precip/ETo/Tmax/Tmin/Tmean alike.
  - The trend-significance table initially used OLS linear regression,
    which matched Climate Engine's *averages* exactly but not its
    trend/p-values -- switched to Mann-Kendall + Sen's slope (the standard
    nonparametric trend test in hydrology), which then matched Climate
    Engine's numbers **exactly** on all 5 variables (high/low temp,
    precip, ETo, precip-ETo), confirming that's what Climate Engine
    actually uses internally (undocumented, but now known empirically).
**How to apply:** If a future chart's numbers look "close but off" to a
Climate Engine reference graphic, don't assume it's unfixable
approximation error -- as this session showed twice, it's more likely a
methodology mismatch (wrong date convention, wrong comparison window,
wrong statistical test) that can be found by testing alternate
methodologies against the same known reference numbers. `year_to_date_summary`'s
docstring still notes the remaining small discrepancies (e.g. ETo
percentile 93rd vs. Climate Engine's 100th) that weren't fully resolved.
**Also fixed during visual QA:** Bokeh figures defaulted to a fixed
640px width, which overflowed their 2-column grid cells (~430px) instead
of fitting -- switched to `sizing_mode="stretch_width"`.

### Visual QA: self-contained via local headless Chrome, not an MCP browser tool
**Decision:** No MCP browser tool (built-in browser, Chrome extension) was
actually connected in this session despite being listed as available skills
-- both were checked and neither had working tools. Instead, used the
Chrome and Edge binaries already installed on the machine (found at their
standard Windows install paths, not on `PATH`) in headless screenshot mode
directly: `chrome.exe --headless --disable-gpu --screenshot=out.png
--window-size=W,H file:///<absolute path>`, then read the resulting PNG
with the Read tool to actually see it. This is now a repeatable, self-
contained way to check any local HTML file's rendering without depending
on a browser tool being connected.
**Why:** The user explicitly asked for a way to detect and fix visual
issues without relying on them to look and report back. This works because
headless Chrome can open `file://` paths directly (unlike an MCP browser
pane running in a separate sandboxed environment), and screenshot-then-Read
is a complete visual feedback loop.
**Important caveat found the hard way:** `--window-size` has a floor around
**500px** in this Chrome build (152.0.7977.84) on Windows -- requesting
390x700 (a phone width) actually renders at `innerWidth=500` while the
`--screenshot` PNG is still saved at the requested 390px canvas, so the
screenshot silently *crops* a 500px-wide render down to 390px rather than
actually laying out at 390px. This looks exactly like a horizontal-overflow
bug (content cut off mid-card) but isn't one -- confirmed by requesting
`--window-size=500,700` (matching the real floor) and seeing the same
layout render with no cutoff at all. Diagnosed by injecting a small
on-page script that prints `window.innerWidth` and computed grid styles
directly into the screenshot (a `<pre>` block), rather than trusting the
requested window-size.
**How to apply:** For any future headless-Chrome visual check, treat
`--window-size` values below ~500 as unreliable -- verify the true
rendered width with an on-page diagnostic (or via CDP `Emulation.setDeviceMetricsOverride`,
not attempted here) before concluding a narrow-viewport layout is actually
broken. Don't re-litigate this every session -- this entry is the record.

### Fixed: near-normal drought class was nearly invisible against the page background
**Decision:** Changed `--dc-c5` (the diverging ramp's neutral midpoint) from
the dataviz skill's literal documented value (`#f0efec` light / `#383835`
dark) to `#cdccc4` light / `#4a4946` dark -- enough contrast to read as a
deliberately-filled neutral zone, not blank space.
**Why:** Caught via the headless-Chrome screenshot loop above: a real
district's "Now" short-term status was 52% Near Normal, but the class-bar
rendered as if only ~48% was filled, with the rest reading as plain white
page background -- a real drought status was visually indistinguishable
from missing data. Same problem in the long-term chart's middle reference
band. The skill's documented gray is correct in the abstract (a diverging
midpoint should recede relative to the vivid extremes) but was tuned
against a different reference surface than this page's near-white
background/surface tokens, so it over-receded to the point of invisibility
here.
**How to apply:** If the page's surface/background tokens ever change,
re-check `--dc-c5` contrast against the new values -- it's a value picked
for legibility against *this* specific background, not a portable
constant.

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
