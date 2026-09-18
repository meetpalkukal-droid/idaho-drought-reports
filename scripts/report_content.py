"""
Turns raw Climate Engine drought-report CSVs into the content build_site.py
renders: plain-language drought-class summaries (now / 3 months ago / 1 year
ago) and a hand-built long-term (1986-present) trend chart, replacing
Climate Engine's own PDF/table images per the project narrative ("we will
use the graphics and data to do our own reports where we explain things a
bit more").

Color design follows the dataviz skill's diverging-palette formula: drought
severity is a polarity (dry <-> wet around a neutral midpoint), so it gets
the palette's documented diverging pair (blue <-> red, gray midpoint) as a
5-step-per-arm sequential ramp on each side. The categorical CVD validator
doesn't apply to sequential/diverging ramps (see the skill's color-formula.md
"Scope" note) -- the check there is lightness monotonicity, which these
ramps satisfy by construction (each arm is a standard 5-step Reds/Blues
progression, light-to-dark = near-normal-to-extreme).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class DroughtClass:
    key: str          # CSV column name, e.g. "c0"
    label: str         # plain-language label
    css_var: str        # CSS custom property name carrying this class's color


# Short-term blend (PDSI, Palmer Z-Index, SPI-30d/90d) and long-term blend
# (PDSI, Z-Index, SPI 6mo/1yr/2yr/5yr) share the same c0-c10 class scheme
# (see the CSV README bundled in every report zip): c0 = most extreme dry
# (index < -2.0) through c5 = near-normal (-0.5 to 0.5) to c10 = most
# extreme wet (> 2.0).
BLEND_CLASSES = [
    DroughtClass("c0", "Exceptional Drought (D4)", "--dc-c0"),
    DroughtClass("c1", "Extreme Drought (D3)", "--dc-c1"),
    DroughtClass("c2", "Severe Drought (D2)", "--dc-c2"),
    DroughtClass("c3", "Moderate Drought (D1)", "--dc-c3"),
    DroughtClass("c4", "Abnormally Dry (D0)", "--dc-c4"),
    DroughtClass("c5", "Near Normal", "--dc-c5"),
    DroughtClass("c6", "Abnormally Wet", "--dc-c6"),
    DroughtClass("c7", "Moderately Wet", "--dc-c7"),
    DroughtClass("c8", "Severely Wet", "--dc-c8"),
    DroughtClass("c9", "Extremely Wet", "--dc-c9"),
    DroughtClass("c10", "Exceptionally Wet", "--dc-c10"),
]

# U.S. Drought Monitor: drought categories only (no wet side), c0-c5.
USDM_CLASSES = [
    DroughtClass("c0", "No Drought", "--dc-c5"),
    DroughtClass("c1", "Abnormally Dry (D0)", "--dc-c4"),
    DroughtClass("c2", "Moderate Drought (D1)", "--dc-c3"),
    DroughtClass("c3", "Severe Drought (D2)", "--dc-c2"),
    DroughtClass("c4", "Extreme Drought (D3)", "--dc-c1"),
    DroughtClass("c5", "Exceptional Drought (D4)", "--dc-c0"),
]


def read_class_timeseries(csv_path: Path, classes: list[DroughtClass]) -> list[dict]:
    """Returns rows as [{"date": date, "pct": {class_key: 0-100, ...}}, ...],
    oldest first. Source columns are fractional pixel counts, not
    percentages (see CSV README) -- normalized here by row sum."""
    rows = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            d = datetime.strptime(r["Date"], "%Y-%m-%d").date()
            raw = {c.key: float(r[c.key]) for c in classes}
            total = sum(raw.values())
            pct = {k: (v / total * 100 if total else 0.0) for k, v in raw.items()}
            rows.append({"date": d, "pct": pct})
    rows.sort(key=lambda r: r["date"])
    return rows


def _nearest(rows: list[dict], target: date) -> dict | None:
    if not rows:
        return None
    return min(rows, key=lambda r: abs((r["date"] - target).days))


def dominant_class(pct: dict, classes: list[DroughtClass]) -> DroughtClass:
    return max(classes, key=lambda c: pct.get(c.key, 0.0))


def summary_snapshots(csv_path: Path, classes: list[DroughtClass]) -> list[dict] | None:
    """[{"label": "Now", "date": ..., "pct": {...}}, ...] for now / ~3 months
    ago / ~1 year ago, each snapped to the nearest available row. Returns
    None if the CSV has no rows."""
    rows = read_class_timeseries(csv_path, classes)
    if not rows:
        return None
    latest = rows[-1]["date"]
    targets = [
        ("Now", latest),
        ("3 months ago", latest - timedelta(days=90)),
        ("1 year ago", latest - timedelta(days=365)),
    ]
    out = []
    for label, target in targets:
        row = _nearest(rows, target)
        out.append({"label": label, "date": row["date"], "pct": row["pct"]})
    return out


def read_eoy_series(csv_path: Path) -> list[tuple[int, float]]:
    """[(year, long-term-blend index value), ...], oldest first."""
    out = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            out.append((int(r["Year"]), float(r["Value"])))
    out.sort(key=lambda p: p[0])
    return out


# --- Per-section background info (short-term/long-term/USDM) -----------
# Shown inline right where each is relevant, not just in the glossary
# further down the page -- per user request for real background on each
# index group, not just a definition. Content is standard, publicly
# documented methodology (Palmer indices, SPI, and the USDM's own stated
# production process), written in lay language.

SHORT_TERM_BACKGROUND_HTML = """
<p class="section-background">Short-term conditions combine four indices
that respond to weather within days or weeks: the <strong>Palmer Drought
Severity Index (PDSI)</strong>, the <strong>Palmer Z-Index</strong> (PDSI's
short-term component), and the <strong>Standardized Precipitation
Index</strong> at 30- and 90-day windows (SPI-30d, SPI-90d). A single wet
or dry spell can change this map from one report to the next. It shows
recent conditions, not the multi-year picture.</p>
""".strip()

LONG_TERM_BACKGROUND_HTML = """
<p class="section-background">Long-term conditions use the same PDSI and
Z-Index, combined with the Standardized Precipitation Index at longer
windows: 6 months, 1 year, 2 years, and 5 years. A single storm or dry
month has little effect on these longer averages. This map shows whether
the past several years have been wetter or drier than normal overall,
which matters more for reservoir storage, groundwater recharge, and
multi-year planning than short-term conditions do.</p>
""".strip()

USDM_BACKGROUND_HTML = """
<p class="section-background">The U.S. Drought Monitor is produced by the
National Drought Mitigation Center (University of
Nebraska&ndash;Lincoln), NOAA, and the USDA, and updated every Thursday.
The short- and long-term blends above are computed directly from climate
data. USDM categories are set weekly by a panel of authors who combine
those indices with ground reports: streamflow gauges, reservoir levels,
soil moisture, and local observations. It's also the index that triggers
USDA disaster-relief and crop-insurance programs, and the one most often
cited in the news.</p>
""".strip()


# --- Plain-language explainer text --------------------------------------

EXPLAINER_HTML = """
<h2>What these numbers mean</h2>
<p class="meta section-intro">Definitions for every index, chart, and term on this page, in the order they appear above.</p>
<dl class="glossary">
  <div class="glossary-entry">
  <dt>Why short-term and long-term are shown separately</dt>
  <dd>A place can be short on recent rain while its multi-year reservoir
  storage is fine, or the reverse. <strong>Short-term</strong> conditions
  answer whether it's rained recently. <strong>Long-term</strong>
  conditions answer whether the past several years have been dry overall.
  Those call for different responses, so this page keeps them separate
  instead of combining them into one number.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Short-term blend</dt>
  <dd>Combines four drought indices that respond to conditions over the
  last 30 days to about 9 months: the Palmer Drought Severity Index
  (PDSI), the Palmer Z-Index, and the Standardized Precipitation Index at
  30- and 90-day windows (SPI-30d, SPI-90d). It shows recent conditions --
  a dry spell or a good storm shows up here within weeks.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Long-term blend</dt>
  <dd>Combines PDSI, the Z-Index, and SPI at 6-month, 1-year, 2-year, and
  5-year windows. It changes slowly, since a single wet month has little
  effect on a 5-year average, so it reflects whether the past several
  years have been part of a longer dry or wet stretch.</dd>
  </div>

  <div class="glossary-entry">
  <dt>What do the PDSI, Z-Index, and SPI numbers actually measure?</dt>
  <dd><strong>PDSI</strong> (Palmer Drought Severity Index) estimates
  cumulative moisture surplus or deficit from precipitation, temperature,
  and a soil-moisture accounting model. It's the oldest and most widely
  used U.S. drought index. The <strong>Z-Index</strong> is PDSI's
  short-term component: the moisture anomaly for the current month,
  before it accumulates into PDSI. <strong>SPI</strong> (Standardized
  Precipitation Index) looks only at precipitation: a value of 0 means
  average for the time of year, -1 means notably drier than average, and
  +1 means notably wetter. The number after "SPI" (30d, 90d, 6mo, 1yr,
  2yr, 5yr) is the averaging window. All three center on 0 for normal,
  negative for dry, and positive for wet, which is why the charts on this
  page use red for negative and blue for positive.</dd>
  </div>

  <div class="glossary-entry">
  <dt>U.S. Drought Monitor (USDM)</dt>
  <dd>The official weekly drought classification produced by NOAA, the
  USDA, and the National Drought Mitigation Center, shown here alongside
  the short- and long-term blends above. Those blends are computed
  directly from climate data. USDM categories are set weekly by authors
  who also review streamflow, reservoir levels, and observed impacts --
  it's the index most likely to match USDA/FSA disaster declarations and
  news reports.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Drought classes (D0-D4)</dt>
  <dd>D0 = Abnormally Dry, D1 = Moderate Drought, D2 = Severe Drought,
  D3 = Extreme Drought, D4 = Exceptional Drought. This is the standard
  USDM severity scale, also used here to classify the short- and
  long-term blend values (an index below -2.0 counts as D4, and so on;
  exact cutoffs are in each chart's legend). The wet side mirrors it:
  Abnormally Wet through Exceptionally Wet.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Percentile</dt>
  <dd>Where this year's value ranks against every other year on record
  for this location. A precipitation percentile of 20 means this year is
  drier than 80% of years on record and wetter than the remaining 20%.
  Low percentiles are dry, high percentiles are wet, and 50 is the
  historical median.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Water year</dt>
  <dd>The 12-month period from Oct 1 to Sep 30, labeled by the year it
  ends in: water year 2026 runs Oct 1, 2025 through Sep 30, 2026. This is
  the standard accounting period for water management in the western
  U.S., since it starts at the beginning of the snow-accumulation season
  rather than the calendar year.</dd>
  </div>

  <div class="glossary-entry">
  <dt>"This year vs. historical normal range" charts (ETo, precipitation, temperature)</dt>
  <dd>The colored band shows the range this location's climate data has
  covered in past years, for each point in the water year: the dark band
  is the middle 50% of years, the light band the middle 90%. The solid
  line traces this water year. When the line is above the band,
  conditions are warmer, wetter, or higher-demand than usual for that
  time of year; below the band, they're cooler, drier, or lower-demand.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Evaporative demand (ETo)</dt>
  <dd>Reference evapotranspiration: an estimate of how much water a
  well-watered reference crop would lose to the atmosphere on a given
  day, based on temperature, humidity, wind, and sunlight. It measures
  how much moisture the atmosphere is pulling out, independent of
  whether it rained -- a hot, dry, windy stretch raises ETo even with no
  precipitation, which is why it's tracked separately from
  precipitation.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Water balance (precipitation &minus; evaporative demand)</dt>
  <dd>Precipitation received minus water the atmosphere is pulling out.
  A negative water balance doesn't necessarily mean a crop was
  under-watered, since irrigation can supply the difference -- it shows
  how much of that demand the local climate covered on its own, versus
  how much irrigation had to make up.</dd>
  </div>

  <div class="glossary-entry">
  <dt>Trend and statistical significance</dt>
  <dd>The trend notes on the charts above estimate how much each
  variable has changed per decade, using the Mann-Kendall trend test and
  the Sen's slope estimator for the rate. This method doesn't assume the
  data follows a smooth statistical pattern, which is why it's standard
  in climate science. The p-value is the probability that a trend this
  size could appear by chance, with no real underlying trend behind it.
  A p-value under 0.05 is conventionally treated as a real trend rather
  than noise; anything higher means the data doesn't clearly support a
  trend either way, not that conditions are stable.</dd>
  </div>
</dl>
<p class="source-note">Source data: Climate Engine's gridMET Drought
product, based on the gridMET daily surface meteorological dataset.
gridMET Drought updates every 5 days, which sets this report's update
cadence. The interactive charts on this page -- drought class evolution,
the normal-range climate charts, the long-term trend, and the statistics
-- are computed directly from that data, not copied from Climate
Engine's report images.</p>
""".strip()
