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


# --- Long-term trend chart (inline SVG) --------------------------------
#
# A single series (the long-term blend index, one value per year), so per
# the dataviz skill it needs no legend box -- the section heading names it.
# Colors are referenced as CSS custom properties (defined once in
# style.css for light/dark) so one SVG works in both themes, matching the
# pattern in the skill's palette.md.

_CHART_W = 720
_CHART_H = 220
# _PAD_R reserves room for the end-of-line label ("YYYY: +X.XX", ~85px at
# this font size) rendered to the RIGHT of the last point -- it needs real
# space, not just a few px of margin.
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 36, 92, 12, 24
_Y_DOMAIN = (-3.0, 3.0)  # covers the full c0-c10 class range with margin

# Reference bands behind the line, one per severity arm (not the full
# 11-class resolution -- 3 bands per side reads cleanly at this chart size;
# the exact class breakdown lives in the summary tables below the chart).
_BANDS = [
    (-3.0, -1.5, "--dc-c1"),
    (-1.5, -0.5, "--dc-c3"),
    (-0.5, 0.5, "--dc-c5"),
    (0.5, 1.5, "--dc-c7"),
    (1.5, 3.0, "--dc-c9"),
]


def _y(value: float) -> float:
    lo, hi = _Y_DOMAIN
    v = max(lo, min(hi, value))
    frac = (v - lo) / (hi - lo)
    return _CHART_H - _PAD_B - frac * (_CHART_H - _PAD_T - _PAD_B)


def render_long_term_svg(series: list[tuple[int, float]], *, chart_id: str) -> str:
    """Inline SVG for the 1986-present long-term blend trend. Includes
    diverging reference bands, a 2px single-series line (dataviz skill mark
    spec), an end marker+label for the latest value, and per-point circles
    with data-* attributes that assets/chart.js turns into a hover
    tooltip+crosshair (the skill's default interaction for a line chart)."""
    if not series:
        return "<p>No long-term trend data available.</p>"

    years = [y for y, _ in series]
    x0, x1 = years[0], years[-1]
    span = max(1, x1 - x0)
    plot_w = _CHART_W - _PAD_L - _PAD_R

    def x(year: int) -> float:
        return _PAD_L + (year - x0) / span * plot_w

    band_rects = "".join(
        f'<rect x="{_PAD_L}" y="{_y(hi):.1f}" width="{plot_w:.1f}" '
        f'height="{(_y(lo) - _y(hi)):.1f}" fill="var({var})" opacity="0.35"/>'
        for lo, hi, var in _BANDS
    )

    points = [(x(yr), _y(val), yr, val) for yr, val in series]
    path_d = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py, _, _ in points)

    dots = "".join(
        f'<circle class="ltc-pt" cx="{px:.1f}" cy="{py:.1f}" r="4" '
        f'data-year="{yr}" data-value="{val:.2f}" tabindex="0"/>'
        for px, py, yr, val in points
    )

    last_x, last_y, last_year, last_val = points[-1]
    end_label = (
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="5" class="ltc-end-dot"/>'
        f'<text x="{last_x + 8:.1f}" y="{last_y + 4:.1f}" '
        f'class="ltc-end-label" text-anchor="start">{last_year}: {last_val:+.2f}</text>'
    )

    # Sparse x-axis ticks (start, a few mid-points, end) -- never one per year.
    tick_years = sorted(set([x0, x0 + span // 2, x1]))
    ticks = "".join(
        f'<text x="{x(yr):.1f}" y="{_CHART_H - 6}" class="ltc-tick" text-anchor="middle">{yr}</text>'
        for yr in tick_years
    )
    zero_y = _y(0)
    zero_line = (
        f'<line x1="{_PAD_L}" y1="{zero_y:.1f}" x2="{_CHART_W - _PAD_R}" y2="{zero_y:.1f}" '
        f'class="ltc-zeroline"/>'
    )

    return f"""
<svg class="long-term-chart" id="{chart_id}" viewBox="0 0 {_CHART_W} {_CHART_H}"
     role="img" aria-label="Long-term drought blend index, {x0} to {x1}">
  {band_rects}
  {zero_line}
  <path d="{path_d}" class="ltc-line" fill="none"/>
  {dots}
  {end_label}
  {ticks}
</svg>
<div class="ltc-tooltip" data-for="{chart_id}" hidden></div>
""".strip()


# --- Plain-language explainer text --------------------------------------

EXPLAINER_HTML = """
<h2>What these numbers mean</h2>
<dl class="glossary">
  <dt>Short-term blend</dt>
  <dd>Combines four drought indices sensitive to conditions over the last
  30 days to about 9 months: the Palmer Drought Severity Index (PDSI), the
  Palmer Z-Index, and the Standardized Precipitation Index at 30- and
  90-day windows (SPI-30d, SPI-90d). It reflects recent, fast-moving
  conditions -- a dry spell or a good storm shows up here quickly.</dd>

  <dt>Long-term blend</dt>
  <dd>Combines PDSI, the Z-Index, and SPI at 6-month, 1-year, 2-year, and
  5-year windows. It reflects accumulated, slower-moving conditions --
  multi-year drought or multi-year wet spells -- and changes more slowly
  than the short-term blend.</dd>

  <dt>U.S. Drought Monitor (USDM)</dt>
  <dd>The official weekly drought-classification map produced by NOAA,
  USDA, and the National Drought Mitigation Center, shown here for the
  same area for context alongside the short- and long-term blends above.</dd>

  <dt>Drought classes (D0-D4)</dt>
  <dd>D0 = Abnormally Dry, D1 = Moderate Drought, D2 = Severe Drought,
  D3 = Extreme Drought, D4 = Exceptional Drought -- the standard USDM
  severity scale, also used here to classify the short- and long-term
  blend index values (an index below -2.0 is treated as D4-equivalent, and
  so on).</dd>
</dl>
<p class="source-note">Source data: Climate Engine's gridMET Drought
product, built on the gridMET daily surface meteorological dataset. gridMET
Drought is published on a 5-day (pentad) cadence, which is why this report
updates every 5 days.</p>
""".strip()
