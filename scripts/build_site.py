"""
Build the static site from the most recently fetched Climate Engine drought
report outputs.

Per the project narrative, this does NOT reuse Climate Engine's bundled PDF
report -- it curates every other graphic and builds its own content from
the CSVs: plain-language drought-class summaries (now / 3 months ago / 1
year ago) and interactive Bokeh charts/tables rebuilding Climate Engine's
own gm_*/ltb_eoy graphics from the same underlying data (per user
direction -- see DECISIONS.md "Interactive charts rebuilt in Bokeh" for
the validation against Climate Engine's actual published numbers). See
report_content.py and climate_charts.py for the data work.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import geopandas as gpd

from fetch_reports import slugify
from report_content import (
    BLEND_CLASSES,
    USDM_CLASSES,
    EXPLAINER_HTML,
    LONG_TERM_BACKGROUND_HTML,
    SHORT_TERM_BACKGROUND_HTML,
    USDM_BACKGROUND_HTML,
    dominant_class,
    read_eoy_series,
    summary_snapshots,
)
from climate_charts import (
    add_tmean,
    class_evolution_df,
    load_gm_daily,
    mann_kendall_trend,
    normal_band_data,
    water_year_mean_series,
    water_year_pivot,
    year_to_date_summary,
)
from bokeh_charts import (
    BOKEH_CDN_TAGS,
    class_evolution_figure,
    embed_figures,
    long_term_index_figure,
    normal_band_figure,
    water_year_trend_figure,
)

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
EXTRACTED_DIR = ROOT / "data" / "reports" / "extracted"
RAW_DIR = ROOT / "data" / "reports" / "raw"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"

LAYER_TITLES = {
    "groundwater_districts": "Groundwater Districts",
    "irrigation_organizations": "Irrigation Organizations",
    "water_districts": "Water Districts",
}

# Each "current conditions" group pairs one Climate Engine map image with
# its own area breakdown (bars) side by side, instead of showing all 3 maps
# in one row and all 3 bar summaries separately below -- per user request
# ("group the short term conditions map with the area bar charts side by
# side... short and long term maps can be combined with the short and long
# term information"). (map image prefix, group title, map caption,
# description, background-info HTML, timeseries CSV name, class scheme).
CONDITION_GROUPS = [
    (
        "stb_map", "Short-term conditions",
        "Blends PDSI, the Z-Index, and 30/90-day SPI.",
        "Recent, fast-moving indices (30 days to ~9 months).",
        SHORT_TERM_BACKGROUND_HTML, "stb_timeseries.csv", BLEND_CLASSES,
    ),
    (
        "ltb_map", "Long-term conditions",
        "Blends PDSI, the Z-Index, and 6-month to 5-year SPI.",
        "Accumulated, slower-moving indices (6 months to 5 years).",
        LONG_TERM_BACKGROUND_HTML, "ltb_timeseries.csv", BLEND_CLASSES,
    ),
    (
        "usdm_map", "U.S. Drought Monitor",
        "The official weekly drought classification for this area.",
        "The official weekly drought classification.",
        USDM_BACKGROUND_HTML, "dm_timeseries.csv", USDM_CLASSES,
    ),
]

SITE_NAME = "Idaho Water User Drought Reports"

HEADER_TEMPLATE = """<header class="site-header">
<div class="wide">
<div><a href="{home_href}"><span class="brand">{site_name}</span></a><div class="tagline">Drought conditions for Idaho water users, updated every 5 days</div></div>
{nav}
</div>
</header>"""

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — Idaho Drought Report</title>
<link rel="stylesheet" href="../assets/style.css">
{bokeh_cdn}
</head>
<body>
{header}
<main><div class="wide">
<h1>{name}</h1>
<p class="meta">{layer_title} &middot; report period ending {run_date} &middot; updated every 5 days from Climate Engine's gridMET Drought data.</p>
{disclosure}
<div class="intro-note">
<p>This page shows how dry or wet conditions have been for <strong>{name}</strong>, both recently and over the long term. The drought indices are computed from weather-station climate data -- not a direct measurement of soil moisture or streamflow, but a standard way to track drought. It updates automatically every 5 days.</p>
</div>

<h2>Current conditions</h2>
<p class="meta section-intro">Three views of this area's current drought status, each shown with its own area breakdown.</p>
{condition_groups}

<h2>Drought class evolution</h2>
<p class="meta section-intro">How the classifications above have changed day by day over the last 13 months, not just at the three snapshots shown. Hover anywhere on a chart for the exact area breakdown on that date.</p>
<div class="bokeh-grid">
<div class="bokeh-chart">{stb_evolution_div}</div>
<div class="bokeh-chart">{ltb_evolution_div}</div>
<div class="bokeh-chart">{dm_evolution_div}</div>
</div>

<h2>Long-term trend (1986&ndash;present)</h2>
<p class="meta section-intro">One number per water year back to 1986, summarizing how that year compared to normal. Positive/blue is wetter than normal, negative/red is drier. The dotted line is a Mann-Kendall trend fit through the points. Hover a point for its exact value; scroll to zoom.</p>
<div class="bokeh-chart">{ltb_chart_div}{ltb_trend_caption}</div>

<h2>Climate context</h2>
<p class="meta section-intro">The raw climate data behind the drought indices above: evaporative demand, precipitation, and temperature, each compared to this area's own historical range, with its own long-term trend. Hover any chart for exact values.</p>
<p class="chart-question">How thirsty has the atmosphere been this year compared to the historical range?</p>
<div class="bokeh-chart">{eto_chart_div}{eto_trend_caption}</div>
<p class="chart-question">How does this year's precipitation compare to normal?</p>
<div class="bokeh-chart">{precip_chart_div}{precip_trend_caption}</div>
<p class="chart-question">How does this year's temperature compare to normal?</p>
<div class="bokeh-chart">{tmean_chart_div}{tmean_trend_caption}</div>
<p class="chart-question">Are precipitation and evaporative demand trending up or down over the long run?</p>
<div class="bokeh-chart">{wy_trend_chart_div}{wy_trend_caption}</div>

{summary_tables}

{explainer}

<p class="footer-note">Built by the University of Idaho as part of a statewide drought-response project. This is not an official regulatory product. Use it for planning and awareness, not as a substitute for your water right, delivery call, or mitigation plan records.</p>
</div></main>
{bokeh_script}
</body>
</html>
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{layer_title} — Idaho Drought Reports</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
{header}
<main><div class="wide">
<h1>{layer_title}</h1>
<p class="meta">{count} {layer_title_lower}, updated every 5 days.</p>
<input class="search-box" type="search" placeholder="Search by name&hellip;" aria-label="Search {layer_title_lower}">
<ul class="entry-list">
{items}
</ul>
</div></main>
<script src="../assets/search.js"></script>
</body>
</html>
"""

HOME_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site_name}</title>
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
</head>
<body>
{header}
<main><div class="wide">
<div class="hero">
<h1>{site_name}</h1>
<p class="lede">Drought conditions for {gw_count} Idaho groundwater districts, {irr_count} Surface Water Coalition irrigation organizations, and {wd_count} Idaho water districts, built on Climate Engine's gridMET Drought data and updated every 5 days.</p>
<p class="meta">Report period ending {run_date}.</p>
</div>

<h2>Find your district or organization</h2>
<input class="search-box" id="home-search" type="search" placeholder="Search by name&hellip;" aria-label="Search all districts and organizations">
<ul id="home-search-results" hidden></ul>

<div class="selector-tabs" role="tablist">
<button class="selector-tab" role="tab" aria-selected="true" aria-controls="panel-map" data-tab="map">Map</button>
<button class="selector-tab" role="tab" aria-selected="false" aria-controls="panel-list" data-tab="list">List</button>
</div>
<div class="selector-panel active" id="panel-map" role="tabpanel">
<div class="map-legend">
<span><span class="swatch" style="background:#1d5fa8"></span>Groundwater districts</span>
<span><span class="swatch" style="background:#1baf7a"></span>Irrigation organizations</span>
<span><span class="swatch" style="background:#c9862a"></span>Water districts</span>
</div>
<div id="home-map"></div>
<p class="meta" style="margin-top:10px;">Click a boundary to open its report.</p>
</div>
<div class="selector-panel" id="panel-list">
<div id="home-list"></div>
</div>

<p class="footer-note">Built by the University of Idaho as part of a statewide drought-response project.</p>
</div></main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script src="assets/home.js"></script>
</body>
</html>
"""


def _render_header(*, home_href: str, nav_html: str = "") -> str:
    return HEADER_TEMPLATE.format(home_href=home_href, site_name=SITE_NAME, nav=nav_html)


def _find_image(dest_dir: Path, prefix: str) -> Path | None:
    matches = sorted((dest_dir / "images").glob(f"{prefix}_*.png"))
    return matches[0] if matches else None


def _render_class_bar(pct: dict, classes) -> str:
    """Each segment carries data-tooltip (a custom-styled CSS hover
    tooltip, see .class-bar-seg in style.css) plus a plain title attribute
    as a fallback, so hovering any colored segment shows its exact area --
    per user request that these bars be interactive."""
    segs = []
    for c in classes:
        v = pct.get(c.key, 0.0)
        if v <= 0:
            continue
        tip = f"{c.label}: {v:.1f}% of area"
        segs.append(
            f'<div class="class-bar-seg" tabindex="0" style="width:{v:.2f}%;background:var({c.css_var})" '
            f'title="{tip}" data-tooltip="{tip}"></div>'
        )
    return f'<div class="class-bar">{"".join(segs)}</div>'


def _class_index(c) -> int:
    return int(c.css_var.rsplit("c", 1)[1])


def _render_legend(classes) -> str:
    """Groups swatches by dry/normal/wet instead of one flat row, so the
    legend reads as two clustered severity scales (reds together, blues
    together) rather than one long undifferentiated strip -- per user
    request to make it "more systematic." Dry classes are ordered mild to
    severe (D0->D4) left to right, matching conventional USDM legend order;
    wet classes mild to extreme."""
    dry = sorted((c for c in classes if _class_index(c) < 5), key=lambda c: -_class_index(c))
    normal = [c for c in classes if _class_index(c) == 5]
    wet = sorted((c for c in classes if _class_index(c) > 5), key=_class_index)

    def _chip(c) -> str:
        return f'<span class="legend-item"><span class="legend-swatch" style="background:var({c.css_var})"></span>{c.label}</span>'

    groups = []
    if dry:
        groups.append(f'<div class="legend-group"><span class="legend-group-label">Drought</span>{"".join(_chip(c) for c in dry)}</div>')
    if normal:
        groups.append(f'<div class="legend-group">{"".join(_chip(c) for c in normal)}</div>')
    if wet:
        groups.append(f'<div class="legend-group"><span class="legend-group-label">Wet</span>{"".join(_chip(c) for c in wet)}</div>')
    return f'<div class="legend">{"".join(groups)}</div>'


def _render_condition_group(
    *, map_prefix: str, group_title: str, map_caption: str, description: str,
    background_html: str, dest_dir: Path, layer: str, slug: str,
    csv_path: Path, classes,
) -> str:
    """One paired card: the Climate Engine map image for this index group
    side by side with its own area breakdown (bars), instead of all 3 maps
    in one row followed by all 3 bar summaries separately below -- per
    user request to pair each map with its own data."""
    img = _find_image(dest_dir, map_prefix)
    map_html = (
        f'<figure class="condition-map"><img src="../data/{layer}/{slug}/images/{img.name}" alt="{group_title}" loading="lazy">'
        f'<figcaption>{map_caption}</figcaption></figure>'
        if img else '<p class="meta">No map available for this report.</p>'
    )

    snapshots = summary_snapshots(csv_path, classes) if csv_path.exists() else None
    if not snapshots:
        data_html = '<p class="meta">No area breakdown available for this report.</p>'
    else:
        rows = []
        for snap in snapshots:
            dom = dominant_class(snap["pct"], classes)
            dom_pct = snap["pct"].get(dom.key, 0.0)
            rows.append(f"""
<div class="snapshot-row">
  <div class="snapshot-label">{snap['label']}<span class="snapshot-date">{snap['date'].isoformat()}</span></div>
  <div>
    {_render_class_bar(snap['pct'], classes)}
    <p class="snapshot-headline">Mostly <strong>{dom.label}</strong> ({dom_pct:.0f}% of area). Hover any segment to see the exact area for each class.</p>
  </div>
</div>""".strip())
        data_html = f"{''.join(rows)}\n{_render_legend(classes)}"

    if not img and not snapshots:
        return ""
    return f"""
<div class="condition-group">
  <div class="condition-media">{map_html}</div>
  <div class="condition-data">
    <h3>{group_title}</h3>
    <p class="meta">{description}</p>
    {background_html}
    {data_html}
  </div>
</div>""".strip()


def _ordinal(n: float) -> str:
    n = int(round(n))
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _trend_caption(t: dict | None, unit: str, *, bad_direction: str, prefix: str = "Long-term trend") -> str:
    """A one-line trend sentence shared by the climate-context charts, the
    long-term index chart, and the percentile-meter rows below -- a single
    source of formatting so trend info reads consistently everywhere it
    appears, instead of a single separate table. bad_direction/color
    mapping matches the percentile meters (red=drought-amplifying for THIS
    variable, not literal rising/falling -- see _percentile_meter_row)."""
    if not t:
        return ""
    rising = t["slope_per_decade"] > 0
    actual_direction = "up" if rising else ("down" if t["slope_per_decade"] < 0 else None)
    cls = "bad" if actual_direction == bad_direction else ("good" if actual_direction else "")
    sig = t["pvalue"] < 0.05
    sig_text = "a statistically significant change" if sig else "not a statistically significant change"
    return (
        f'<p class="trend-caption">{prefix}: '
        f'<span class="trend-inline {cls}">{t["slope_per_decade"]:+.2f} {unit}/decade</span> '
        f'since 1986 &mdash; {sig_text} (p={t["pvalue"]:.3f}).</p>'
    )


def _percentile_meter_row(
    label: str, unit: str, r: dict, *, low_label: str, high_label: str, concern_high: bool,
    trend_html: str = "",
) -> str:
    """One stat as a sentence plus a horizontal percentile meter instead of
    a table row: a track colored with the site's diverging drought
    palette (the same dry=red/wet=blue language used everywhere else on
    the page), a pin at this year's percentile rank labeled right next to
    the pin itself (not centered on the bar, which read as if the
    percentile were fixed at the midpoint), and a marker at the 50th
    percentile as the 'typical' reference point. concern_high=True means a
    HIGH percentile is the drought-amplifying direction for this variable
    (hotter, or more evaporative demand -> red at the high end);
    concern_high=False means a LOW percentile is drought-amplifying (less
    precipitation -> red at the low end). low_label/high_label are this
    specific variable's own words for each end (e.g. "Cooler"/"Warmer",
    not a generic "wetter"/"drier" that wouldn't fit ETo)."""
    pct = max(0.0, min(100.0, r["percentile"]))
    label_pct = max(6.0, min(94.0, pct))  # keep the floating label on-track near the edges
    direction_class = "concern-high" if concern_high else "concern-low"
    if r["diff"] > 0:
        diff_phrase = f"{r['diff']:.1f}{unit} above"
    elif r["diff"] < 0:
        diff_phrase = f"{abs(r['diff']):.1f}{unit} below"
    else:
        diff_phrase = "right at"
    sentence = (
        f"<strong>{label}</strong> was <strong>{r['current']:.1f}{unit}</strong> this year to date "
        f"&mdash; {diff_phrase} the {r['average']:.1f}{unit} average, the {_ordinal(r['percentile'])} "
        f"percentile on record."
    )
    return f"""
<div class="pct-row">
  <p class="pct-sentence">{sentence}</p>
  <div class="pct-meter {direction_class}">
    <span class="pct-meter-avg" style="left:50%" title="Historical average, same point in the water year"></span>
    <span class="pct-meter-pin" style="left:{pct:.1f}%"></span>
    <span class="pct-meter-pin-label" style="left:{label_pct:.1f}%">{_ordinal(r['percentile'])} pct.</span>
  </div>
  <div class="pct-row-foot">
    <span>{low_label}</span>
    <span>{high_label}</span>
  </div>
  {trend_html}
</div>""".strip()


def _render_summary_tables(gm_df, wy_df, current_water_year: int, wy_trends: dict) -> str:
    """Rebuild of Climate Engine's gm_temp_summary + gm_wb_summary tables,
    shown as percentile meters instead of a raw numbers table -- current
    (year-to-date) value vs. the historical average through the same point
    in the water year, plus a percentile rank and (via wy_trends, computed
    once in build() and reused here) each variable's long-term trend --
    integrating that trend info here instead of only in one separate table
    further down the page. See climate_charts.year_to_date_summary for the
    year-to-date methodology, validated against Climate Engine's own
    published numbers in DECISIONS.md."""
    rows_temp = []
    for label, var, wy_key in [("High temp", "Tmax", "Tmax"), ("Low temp", "Tmin", "Tmin"), ("Mean temp", "Tmean", "Tmean")]:
        r = year_to_date_summary(gm_df, var, current_water_year, cumulative=False)
        if r:
            trend_html = _trend_caption(wy_trends.get(wy_key), "°F", bad_direction="up", prefix="Trend")
            rows_temp.append((label, "°F", r, "Cooler", "Warmer", True, trend_html))

    rows_wb = []
    wb_specs = [
        ("Precipitation", "Precip", "Drier", "Wetter", False, "down"),
        ("Evap demand", "ETo", "Lower demand", "Higher demand", True, "up"),
    ]
    for label, var, low_label, high_label, concern_high, bad_direction in wb_specs:
        r = year_to_date_summary(gm_df, var, current_water_year, cumulative=True)
        if r:
            trend_html = _trend_caption(wy_trends.get(var), "in", bad_direction=bad_direction, prefix="Trend")
            rows_wb.append((label, " in", r, low_label, high_label, concern_high, trend_html))

    if not rows_temp and not rows_wb:
        return ""

    def _card(title: str, rows: list[tuple]) -> str:
        body = "\n".join(
            _percentile_meter_row(label, unit, r, low_label=low_label, high_label=high_label,
                                   concern_high=concern_high, trend_html=trend_html)
            for label, unit, r, low_label, high_label, concern_high, trend_html in rows
        )
        return f"""
<div class="stat-table pct-card">
  <h3>{title}</h3>
  <p class="meta">This year to date vs. the historical average through the same point in the water year.</p>
  {body}
</div>""".strip()

    parts = []
    if rows_temp:
        parts.append(_card("Temperature summary", rows_temp))
    if rows_wb:
        net_trend_html = _trend_caption(wy_trends.get("Precip_minus_ETo"), "in", bad_direction="down",
                                         prefix="Net water balance (precip &minus; evap demand) trend")
        wb_card = _card("Water balance summary", rows_wb)
        if net_trend_html:
            wb_card = wb_card[:-len("</div>")] + net_trend_html + "</div>"
        parts.append(wb_card)
    if not parts:
        return ""
    return f'<div class="pct-card-grid">{"".join(parts)}</div>'


def _find_geometry_fallback_note(raw_dir: Path, slug: str) -> str:
    sidecar_path = raw_dir / "_geometry_fallback.json"
    if not sidecar_path.exists():
        return ""
    sidecar = json.loads(sidecar_path.read_text())
    entry = sidecar.get(slug)
    if not entry:
        return ""
    buffer_km = entry["buffer_m"] / 1000
    return (
        f'<div class="disclosure"><strong>Note on this report\'s area:</strong> '
        f"this jurisdiction's boundary is small relative to the underlying climate "
        f"data grid (4km resolution). To produce a valid report, conditions were "
        f"computed over a {buffer_km:.0f}km buffer around the boundary rather than "
        f"the boundary alone.</div>"
    )


def build(run_date: str) -> None:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "assets").mkdir(exist_ok=True)

    home_cards = []
    for layer, layer_title in LAYER_TITLES.items():
        layer_extracted_dir = EXTRACTED_DIR / layer / run_date
        if not layer_extracted_dir.exists():
            continue

        layer_site_dir = SITE_DIR / layer
        layer_data_dir = SITE_DATA_DIR / layer
        if layer_site_dir.exists():
            shutil.rmtree(layer_site_dir)
        if layer_data_dir.exists():
            shutil.rmtree(layer_data_dir)
        layer_site_dir.mkdir(parents=True, exist_ok=True)
        layer_data_dir.mkdir(parents=True, exist_ok=True)

        raw_dir = RAW_DIR / layer / run_date
        gdf = gpd.read_file(PROCESSED_DIR / f"{layer}.json")
        slug_to_name = {slugify(name): name for name in gdf["name"]}

        index_items = []
        for site_dir in sorted(layer_extracted_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            slug = site_dir.name
            name = slug_to_name.get(slug, slug)

            dest_dir = layer_data_dir / slug
            # Skip reports/ (Climate Engine's bundled PDF + a rendered PNG of
            # that same PDF) and the CSV-schema README -- per the project
            # narrative we build our own reports from the graphics/data, not
            # Climate Engine's PDF.
            shutil.copytree(site_dir, dest_dir, ignore=shutil.ignore_patterns("reports", "README.md"))

            condition_groups = "\n".join(filter(None, [
                _render_condition_group(
                    map_prefix=map_prefix, group_title=group_title, map_caption=map_caption,
                    description=description, background_html=background_html,
                    dest_dir=dest_dir, layer=layer, slug=slug,
                    csv_path=dest_dir / "data" / csv_name, classes=classes,
                )
                for map_prefix, group_title, map_caption, description, background_html, csv_name, classes in CONDITION_GROUPS
            ]))

            eoy_csv = dest_dir / "data" / "ltb_eoy_timeseries.csv"
            gm_csv = dest_dir / "data" / "gm_timeseries.csv"
            gm_wy_csv = dest_dir / "data" / "gm_wy_timeseries.csv"

            figs = {}
            figs["ltb"], ltb_trend = long_term_index_figure(read_eoy_series(eoy_csv)) if eoy_csv.exists() else (None, None)

            for fig_key, csv_name, classes, title in [
                ("stb_evo", "stb_timeseries.csv", BLEND_CLASSES, "Short-Term Blend Evolution"),
                ("ltb_evo", "ltb_timeseries.csv", BLEND_CLASSES, "Long-Term Blend Evolution"),
                ("dm_evo", "dm_timeseries.csv", USDM_CLASSES, "U.S. Drought Monitor Evolution"),
            ]:
                csv_path = dest_dir / "data" / csv_name
                figs[fig_key] = (
                    class_evolution_figure(class_evolution_df(csv_path, [c.key for c in classes]), classes, title)
                    if csv_path.exists() else None
                )

            summary_tables_html = ""
            wy_trends: dict = {}
            eto_trend_caption = precip_trend_caption = tmean_trend_caption = wy_trend_caption = ""
            if gm_csv.exists():
                gm_df = add_tmean(load_gm_daily(gm_csv))
                current_wy = int(gm_df["water_year"].max())
                figs["eto"] = normal_band_figure(
                    normal_band_data(gm_df, "ETo", cumulative=False, current_water_year=current_wy),
                    title="Reference ETo Rate", y_label="ETo (in/day)",
                )
                figs["precip"] = normal_band_figure(
                    normal_band_data(gm_df, "Precip", cumulative=True, current_water_year=current_wy),
                    title="Cumulative Precipitation", y_label="Precip (in)",
                )
                figs["tmean"] = normal_band_figure(
                    normal_band_data(gm_df, "Tmean", cumulative=False, current_water_year=current_wy),
                    title="Mean Temperature", y_label="Temp (°F)",
                )

                # Long-term (1986-present) trends, computed once here and
                # reused for both the on-chart trend lines/captions AND the
                # percentile-meter trend notes below -- a single source of
                # numbers instead of the two disagreeing (see DECISIONS.md
                # "Visual stat displays").
                wy_df = water_year_pivot(gm_wy_csv) if gm_wy_csv.exists() else None
                if wy_df is not None and not wy_df.empty:
                    years_wy = wy_df.index.to_numpy()
                    for col in ("Tmax", "Tmin"):
                        if col in wy_df.columns:
                            wy_trends[col] = mann_kendall_trend(years_wy, wy_df[col].to_numpy())
                    figs["wy_trend"], pe_trends = water_year_trend_figure(wy_df)
                    wy_trends.update(pe_trends)  # "Precip", "ETo"
                    if "Precip" in wy_df.columns and "ETo" in wy_df.columns:
                        wy_trends["Precip_minus_ETo"] = mann_kendall_trend(
                            years_wy, (wy_df["Precip"] - wy_df["ETo"]).to_numpy()
                        )
                # Tmean isn't in Climate Engine's own gm_wy_timeseries.csv
                # (only in the daily series we synthesize it from).
                tmean_years, tmean_vals = water_year_mean_series(gm_df, "Tmean", exclude_water_year=current_wy)
                if len(tmean_years) > 2:
                    wy_trends["Tmean"] = mann_kendall_trend(tmean_years, tmean_vals)

                eto_trend_caption = _trend_caption(wy_trends.get("ETo"), "in", bad_direction="up",
                                                    prefix="Long-term trend")
                precip_trend_caption = _trend_caption(wy_trends.get("Precip"), "in", bad_direction="down",
                                                       prefix="Long-term trend")
                tmean_trend_caption = _trend_caption(wy_trends.get("Tmean"), "°F", bad_direction="up",
                                                      prefix="Long-term trend")
                wy_trend_caption = (
                    _trend_caption(wy_trends.get("Precip"), "in", bad_direction="down", prefix="Precipitation trend")
                    + _trend_caption(wy_trends.get("ETo"), "in", bad_direction="up", prefix="Evaporative demand trend")
                )
                summary_tables_html = _render_summary_tables(gm_df, wy_df, current_wy, wy_trends)

            ltb_trend_caption = _trend_caption(ltb_trend, "index pts", bad_direction="down", prefix="Trend")

            bokeh_script, divs = embed_figures(figs)

            page_html = PAGE_TEMPLATE.format(
                name=html.escape(name),
                layer_title=layer_title,
                layer_title_lower=layer_title.lower(),
                run_date=run_date,
                header=_render_header(home_href="../index.html", nav_html=f'<nav><a href="../index.html">&larr; All {layer_title}</a></nav>'),
                disclosure=_find_geometry_fallback_note(raw_dir, slug),
                condition_groups=condition_groups or "<p>No current-conditions data available for this report.</p>",
                bokeh_cdn=BOKEH_CDN_TAGS,
                stb_evolution_div=divs.get("stb_evo", "<p>No short-term data available.</p>"),
                ltb_evolution_div=divs.get("ltb_evo", "<p>No long-term data available.</p>"),
                dm_evolution_div=divs.get("dm_evo", "<p>No USDM data available.</p>"),
                ltb_chart_div=divs.get("ltb", "<p>No long-term trend data available.</p>"),
                ltb_trend_caption=ltb_trend_caption,
                eto_chart_div=divs.get("eto", "<p>No ETo data available.</p>"),
                eto_trend_caption=eto_trend_caption,
                precip_chart_div=divs.get("precip", "<p>No precipitation data available.</p>"),
                precip_trend_caption=precip_trend_caption,
                tmean_chart_div=divs.get("tmean", "<p>No temperature data available.</p>"),
                tmean_trend_caption=tmean_trend_caption,
                wy_trend_chart_div=divs.get("wy_trend", "<p>No water-year trend data available.</p>"),
                wy_trend_caption=wy_trend_caption,
                summary_tables=summary_tables_html,
                explainer=EXPLAINER_HTML,
                bokeh_script=bokeh_script,
            )
            (layer_site_dir / f"{slug}.html").write_text(page_html, encoding="utf-8")
            index_items.append(f'<li><a href="{slug}.html">{html.escape(name)}</a></li>')

        (layer_site_dir / "index.html").write_text(
            INDEX_TEMPLATE.format(
                layer_title=layer_title,
                layer_title_lower=layer_title.lower(),
                count=len(index_items),
                items="\n".join(index_items),
                header=_render_header(home_href="../index.html", nav_html='<nav><a href="../index.html">&larr; Home</a></nav>'),
            ),
            encoding="utf-8",
        )
        home_cards.append((layer, layer_title, len(index_items)))

    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    map_src = PROCESSED_DIR / "map_boundaries.json"
    if map_src.exists():
        shutil.copy(map_src, SITE_DATA_DIR / "map_boundaries.json")

    counts = {layer: n for layer, _, n in home_cards}
    (SITE_DIR / "index.html").write_text(
        HOME_TEMPLATE.format(
            site_name=SITE_NAME,
            run_date=run_date,
            gw_count=counts.get("groundwater_districts", 0),
            irr_count=counts.get("irrigation_organizations", 0),
            wd_count=counts.get("water_districts", 0),
            header=_render_header(home_href="index.html", nav_html=""),
        ),
        encoding="utf-8",
    )

    manifest = {"run_date": run_date, "layers": list(LAYER_TITLES)}
    (SITE_DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    import sys
    build(run_date=sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat())
