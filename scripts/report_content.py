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


# --- Plain-language explainer text --------------------------------------

EXPLAINER_HTML = """
<h2>What these numbers mean</h2>
<p class="meta section-intro">This section explains every index, chart, and term used on this page in plain language, roughly in the order they appear above.</p>
<dl class="glossary">
  <dt>Why these maps and charts, not just "is it a drought year"?</dt>
  <dd>Drought isn't one thing -- a place can be short on recent rain but
  fine on multi-year reservoir storage, or the reverse. This page
  deliberately separates <strong>short-term</strong> conditions (did it
  rain this month?) from <strong>long-term</strong> conditions
  (has the last several years been dry overall?), because those two
  situations call for different responses and are easy to confuse if
  only one number is shown.</dd>

  <dt>Short-term blend</dt>
  <dd>Combines four drought indices sensitive to conditions over the last
  30 days to about 9 months: the Palmer Drought Severity Index (PDSI), the
  Palmer Z-Index, and the Standardized Precipitation Index at 30- and
  90-day windows (SPI-30d, SPI-90d). It reflects recent, fast-moving
  conditions -- a dry spell or a good storm shows up here within weeks.
  Use it to answer "how has it been lately?"</dd>

  <dt>Long-term blend</dt>
  <dd>Combines PDSI, the Z-Index, and SPI at 6-month, 1-year, 2-year, and
  5-year windows. It reflects accumulated, slower-moving conditions --
  multi-year drought or multi-year wet spells -- and changes more slowly
  than the short-term blend, since a single wet month barely moves a
  5-year average. Use it to answer "has this been part of a longer dry or
  wet stretch?"</dd>

  <dt>What do the PDSI, Z-Index, and SPI numbers actually measure?</dt>
  <dd><strong>PDSI</strong> (Palmer Drought Severity Index) estimates
  cumulative moisture surplus/deficit using precipitation, temperature, and
  a simple soil-moisture accounting model -- it's the oldest and most
  widely known U.S. drought index. The <strong>Z-Index</strong> is PDSI's
  short-term building block, essentially "this month's moisture anomaly"
  before it accumulates into the fuller PDSI. <strong>SPI</strong>
  (Standardized Precipitation Index) is simpler: it only looks at
  precipitation, standardized so a value of 0 always means "average for
  this time of year," -1 means notably drier than average, and +1 means
  notably wetter -- the number after "SPI" (30d, 90d, 6mo, 1yr, 2yr, 5yr)
  is the window it's averaged over. All three center on 0 = normal,
  negative = dry, positive = wet, which is why the charts on this page use
  red for negative and blue for positive throughout.</dd>

  <dt>U.S. Drought Monitor (USDM)</dt>
  <dd>The official weekly drought-classification map produced by NOAA,
  USDA, and the National Drought Mitigation Center, shown here for the
  same area for context alongside the short- and long-term blends above.
  Unlike the blends (which are purely computed from climate data), USDM
  categories are set weekly by expert authors who also weigh in local
  reports on streamflow, reservoir levels, and observed impacts -- it's
  the index most likely to match what you'd hear in the news or from
  USDA/FSA disaster declarations.</dd>

  <dt>Drought classes (D0-D4)</dt>
  <dd>D0 = Abnormally Dry, D1 = Moderate Drought, D2 = Severe Drought,
  D3 = Extreme Drought, D4 = Exceptional Drought -- the standard USDM
  severity scale, also used here to classify the short- and long-term
  blend index values (an index below -2.0 is treated as D4-equivalent, and
  so on; the exact cutoffs are in each chart's legend). On the wet side,
  the same scale is mirrored: Abnormally Wet through Exceptionally Wet.</dd>

  <dt>Percentile</dt>
  <dd>Where this year's value ranks against every other year on record for
  this same location. A precipitation percentile of 20 means this year is
  drier than 80% of years and wetter than only 20% -- low percentiles are
  dry, high percentiles are wet, and 50 is exactly the historical median.</dd>

  <dt>Water year</dt>
  <dd>The 12-month period Oct 1 &ndash; Sep 30, labeled by the year it
  ends in -- "water year 2026" runs Oct 1, 2025 through Sep 30, 2026. This
  is the standard accounting period for Western water management, since it
  starts at the beginning of the snow-accumulation season rather than the
  calendar year.</dd>

  <dt>"This year vs. historical normal range" charts (ETo, precipitation, temperature)</dt>
  <dd>The colored band is the range this location's climate data has shown
  in past years for each point in the water year (the dark band is the
  middle 50% of years, the light band the middle 90%); the solid line
  traces this water year specifically. When the line sits above the band,
  conditions are unusually warm/wet/high-demand for that time of year; below
  the band, unusually cool/dry/low-demand.</dd>

  <dt>Evaporative demand (ETo)</dt>
  <dd>Reference evapotranspiration -- an estimate of how much water a
  well-watered reference crop would lose to the atmosphere on a given day,
  based on temperature, humidity, wind, and sunlight. It's a proxy for
  "how thirsty is the atmosphere," independent of whether it actually
  rained -- a hot, dry, windy stretch raises ETo even with no precipitation
  at all, which is why it's tracked separately from precipitation rather
  than combined into one number.</dd>

  <dt>Water balance (precipitation &minus; evaporative demand)</dt>
  <dd>A simple net moisture indicator: precipitation received minus water
  the atmosphere is pulling out. A negative water balance doesn't
  necessarily mean a crop was under-watered (irrigation supplies the
  difference), but it does indicate how much the local climate itself was
  able to supply versus how much extra demand irrigation had to cover.</dd>

  <dt>Trend and statistical significance</dt>
  <dd>The long-term climate trends table estimates how much each variable
  has changed per decade using the Mann-Kendall trend test, a standard
  method in climate science chosen because it doesn't assume the data
  follows a smooth statistical pattern the way simpler methods do. The
  significance column (p-value) is the chance that an apparent trend this
  size could show up in random year-to-year noise even if there were no
  real underlying trend -- a p-value under 0.05 (marked with *) is
  conventionally treated as "probably a real trend, not just noise";
  anything higher means the data doesn't clearly support a trend either
  way, not that conditions are necessarily stable.</dd>
</dl>
<p class="source-note">Source data: Climate Engine's gridMET Drought
product, built on the gridMET daily surface meteorological dataset. gridMET
Drought is published on a 5-day (pentad) cadence, which is why this report
updates every 5 days. The interactive charts on this page (drought class
evolution, the normal-range climate charts, the long-term trend, and the
statistics tables) are computed directly from that same data by this
project, not copied from Climate Engine's own report images.</p>
""".strip()
