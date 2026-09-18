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
}

# Which Climate Engine map image to pull for each "current conditions" card:
# (file prefix inside images/, card title, one-line plain-language caption).
MAP_CARDS = [
    ("usdm_map", "U.S. Drought Monitor", "The official weekly drought classification for this area."),
    ("stb_map", "Short-Term Conditions", "Blends PDSI, the Z-Index, and 30/90-day SPI -- responds quickly to recent weather."),
    ("ltb_map", "Long-Term Conditions", "Blends PDSI, the Z-Index, and 6-month to 5-year SPI -- reflects accumulated conditions."),
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
<p>This page summarizes how dry or wet conditions have been for <strong>{name}</strong> recently and over the long term, using drought indices computed from weather-station-based climate data (not a direct measurement of soil moisture or streamflow, but a well-established standard way to track drought). Everything on this page updates automatically every 5 days.</p>
</div>

<h2>Current conditions</h2>
<p class="meta section-intro">Three maps of this area's current drought status, each looking at a different time window.</p>
<div class="map-grid">
{map_cards}
</div>

{blend_sections}

<h2>Drought class evolution</h2>
<p class="meta section-intro">How the drought classification above has changed continuously over roughly the last 13 months, not just the 3 snapshots above. Hover anywhere on a chart for the exact breakdown on that date.</p>
<div class="bokeh-grid">
<div class="bokeh-chart">{stb_evolution_div}</div>
<div class="bokeh-chart">{ltb_evolution_div}</div>
<div class="bokeh-chart">{dm_evolution_div}</div>
</div>

<h2>Long-term trend (1986&ndash;present)</h2>
<p class="meta section-intro">The long-term drought blend index for every water year back to 1986 &mdash; one number per year summarizing how that year compared to normal. Positive/blue is wetter than normal, negative/red is drier. Hover a point for its exact value; scroll to zoom.</p>
<div class="bokeh-chart">{ltb_chart_div}</div>

<h2>Climate context</h2>
<p class="meta section-intro">The raw climate data behind the drought indices above: evaporative demand (how thirsty the atmosphere is), precipitation, and temperature, each compared against this area's own historical normal range. Interactive &mdash; hover for exact values.</p>
<div class="bokeh-grid">
<div class="bokeh-chart">{eto_chart_div}</div>
<div class="bokeh-chart">{precip_chart_div}</div>
<div class="bokeh-chart">{tmean_chart_div}</div>
<div class="bokeh-chart">{wy_trend_chart_div}</div>
</div>
{summary_tables}
{trend_table}

{explainer}

<h2>Data</h2>
<p class="meta section-intro">Download the raw numbers behind every chart on this page.</p>
<ul class="data-links">
{csv_links}
</ul>

<p class="footer-note">Built by the University of Idaho as part of a statewide drought-response project. Not an official regulatory product &mdash; for planning and awareness, not a substitute for your water right, delivery call, or mitigation plan records.</p>
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
<p class="lede">Tailored, jurisdiction-specific drought conditions for {gw_count} Idaho groundwater districts and {irr_count} irrigation organizations &mdash; built on Climate Engine's gridMET Drought data, updated every 5 days.</p>
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


def _render_image_cards(dest_dir: Path, layer: str, slug: str, specs: list[tuple[str, str, str]]) -> str:
    cards = []
    for prefix, title, caption in specs:
        img = _find_image(dest_dir, prefix)
        if not img:
            continue
        rel = f"../data/{layer}/{slug}/images/{img.name}"
        cards.append(
            f'<div class="map-card"><figure><img src="{rel}" alt="{title}" loading="lazy">'
            f'<figcaption><strong>{title}.</strong> {caption}</figcaption></figure></div>'
        )
    return "\n".join(cards)


def _render_class_bar(pct: dict, classes) -> str:
    segs = []
    for c in classes:
        v = pct.get(c.key, 0.0)
        if v <= 0:
            continue
        segs.append(f'<div class="class-bar-seg" style="width:{v:.2f}%;background:var({c.css_var})" title="{c.label}: {v:.1f}%"></div>')
    return f'<div class="class-bar">{"".join(segs)}</div>'


def _render_legend(classes) -> str:
    items = "".join(
        f'<span class="legend-item"><span class="legend-swatch" style="background:var({c.css_var})"></span>{c.label}</span>'
        for c in classes
    )
    return f'<div class="legend">{items}</div>'


def _render_blend_section(title: str, description: str, csv_path: Path, classes) -> str:
    snapshots = summary_snapshots(csv_path, classes)
    if not snapshots:
        return ""
    rows = []
    for snap in snapshots:
        dom = dominant_class(snap["pct"], classes)
        dom_pct = snap["pct"].get(dom.key, 0.0)
        rows.append(f"""
<div class="snapshot-row">
  <div class="snapshot-label">{snap['label']}<span class="snapshot-date">{snap['date'].isoformat()}</span></div>
  <div>
    {_render_class_bar(snap['pct'], classes)}
    <p class="snapshot-headline">Mostly <strong>{dom.label}</strong> ({dom_pct:.0f}% of area)</p>
  </div>
</div>""".strip())
    return f"""
<div class="blend-summary">
  <h3>{title}</h3>
  <p class="meta">{description}</p>
  {''.join(rows)}
  {_render_legend(classes)}
</div>""".strip()


def _ordinal(n: float) -> str:
    n = int(round(n))
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _percentile_meter_row(label: str, unit: str, r: dict, *, low_label: str, high_label: str, concern_high: bool) -> str:
    """One stat as a horizontal percentile meter instead of a table row:
    a track colored with the site's diverging drought palette (the same
    dry=red/wet=blue language used everywhere else on the page), a pin at
    this year's percentile rank, and a marker at the 50th percentile as
    the 'typical' reference point. concern_high=True means a HIGH
    percentile is the drought-amplifying direction for this variable
    (hotter, or more evaporative demand -> red at the high end);
    concern_high=False means a LOW percentile is drought-amplifying
    (less precipitation -> red at the low end). low_label/high_label are
    this specific variable's own words for each end (e.g. "Cooler"/
    "Warmer", not a generic "wetter"/"drier" that wouldn't fit ETo)."""
    pct = max(0.0, min(100.0, r["percentile"]))
    direction_class = "concern-high" if concern_high else "concern-low"
    diff_class = "up" if r["diff"] > 0 else ("down" if r["diff"] < 0 else "")
    diff_sign = "+" if r["diff"] > 0 else ""
    return f"""
<div class="pct-row">
  <div class="pct-row-head">
    <span class="pct-label">{label}</span>
    <span class="pct-current">{r['current']:.1f}{unit}</span>
    <span class="pct-diff {diff_class}">{diff_sign}{r['diff']:.1f}{unit} vs. average ({r['average']:.1f}{unit})</span>
  </div>
  <div class="pct-meter {direction_class}">
    <span class="pct-meter-avg" style="left:50%" title="Historical average, same point in the water year"></span>
    <span class="pct-meter-pin" style="left:{pct:.1f}%"></span>
  </div>
  <div class="pct-row-foot">
    <span>{low_label}</span>
    <span class="pct-rank">{_ordinal(r['percentile'])} percentile</span>
    <span>{high_label}</span>
  </div>
</div>""".strip()


def _render_summary_tables(gm_df, wy_df, current_water_year: int) -> str:
    """Rebuild of Climate Engine's gm_temp_summary + gm_wb_summary tables,
    shown as percentile meters instead of a raw numbers table -- current
    (year-to-date) value vs. the historical average through the same point
    in the water year, plus a percentile rank. See
    climate_charts.year_to_date_summary for the methodology, validated
    against Climate Engine's own published numbers in DECISIONS.md."""
    rows_temp = []
    for label, var in [("High temp", "Tmax"), ("Low temp", "Tmin"), ("Mean temp", "Tmean")]:
        r = year_to_date_summary(gm_df, var, current_water_year, cumulative=False)
        if r:
            rows_temp.append((label, "°F", r, "Cooler", "Warmer", True))

    rows_wb = []
    wb_specs = [
        ("Precipitation", "Precip", "Drier", "Wetter", False),
        ("Evap demand", "ETo", "Lower demand", "Higher demand", True),
    ]
    for label, var, low_label, high_label, concern_high in wb_specs:
        r = year_to_date_summary(gm_df, var, current_water_year, cumulative=True)
        if r:
            rows_wb.append((label, " in", r, low_label, high_label, concern_high))

    if not rows_temp and not rows_wb:
        return ""

    def _card(title: str, rows: list[tuple[str, str, dict, str, str, bool]]) -> str:
        body = "\n".join(
            _percentile_meter_row(label, unit, r, low_label=low_label, high_label=high_label, concern_high=concern_high)
            for label, unit, r, low_label, high_label, concern_high in rows
        )
        return f"""
<div class="stat-table">
  <h3>{title}</h3>
  <p class="meta">This year to date vs. the historical average through the same point in the water year.</p>
  {body}
</div>""".strip()

    parts = []
    if rows_temp:
        parts.append(_card("Temperature summary", rows_temp))
    if rows_wb:
        parts.append(_card("Water balance summary", rows_wb))
    return "\n".join(parts)


def _render_trend_table(wy_df) -> str:
    """Rebuild of Climate Engine's gm_long_term_trends table, shown as a
    grid of directional stat tiles instead of a raw numbers table:
    Mann-Kendall trend + significance per decade for each water-year
    variable."""
    if wy_df is None or wy_df.empty:
        return ""
    years = wy_df.index.to_numpy()
    # bad_direction: which slope direction is drought-amplifying for this
    # variable -- warming and rising evaporative demand are "up", but
    # declining precipitation/net water balance is "down". Colors follow
    # this (red=drought-amplifying, blue=drought-easing), not literal
    # rising/falling, matching the percentile meters above (see
    # DECISIONS.md "Chart sizing" / percentile-meter direction mapping).
    specs = [("High temp", "Tmax", "°F", "up"), ("Low temp", "Tmin", "°F", "up"),
             ("Precipitation", "Precip", "in", "down"), ("Evap demand", "ETo", "in", "up")]
    if "Precip" in wy_df.columns and "ETo" in wy_df.columns:
        wy_df = wy_df.copy()
        wy_df["Precip_minus_ETo"] = wy_df["Precip"] - wy_df["ETo"]
        specs.append(("Precip − Evap demand", "Precip_minus_ETo", "in", "down"))

    tiles = []
    for label, col, unit, bad_direction in specs:
        if col not in wy_df.columns:
            continue
        t = mann_kendall_trend(years, wy_df[col].to_numpy())
        sig = t["pvalue"] < 0.05
        rising = t["slope_per_decade"] > 0
        arrow = "▲" if rising else ("▼" if t["slope_per_decade"] < 0 else "▬")
        actual_direction = "up" if rising else ("down" if t["slope_per_decade"] < 0 else None)
        trend_class = "bad" if actual_direction == bad_direction else ("good" if actual_direction else "")
        sig_html = (
            f'<span class="trend-sig">significant trend (p={t["pvalue"]:.3f})</span>' if sig else
            f'<span class="trend-nosig">not statistically significant (p={t["pvalue"]:.3f})</span>'
        )
        tiles.append(f"""
<div class="trend-tile">
  <div class="trend-tile-label">{label}</div>
  <div class="trend-tile-value {trend_class}"><span class="trend-arrow">{arrow}</span>{t['slope_per_decade']:+.2f} {unit}/decade</div>
  <div class="trend-tile-avg">avg {t['mean']:.1f} {unit}</div>
  {sig_html}
</div>""".strip())
    if not tiles:
        return ""
    return f"""
<div class="stat-table">
  <h3>Long-term climate trends</h3>
  <p class="meta">How much each variable has changed per decade since 1986, using the Mann-Kendall trend test.</p>
  <div class="trend-grid">
  {''.join(tiles)}
  </div>
</div>""".strip()


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

            csvs = sorted((dest_dir / "data").glob("*.csv")) if (dest_dir / "data").exists() else []
            csv_links = "\n".join(
                f'<li><a href="../data/{layer}/{slug}/data/{f.name}">{f.name}</a></li>' for f in csvs
            )

            blend_sections = "\n".join(filter(None, [
                _render_blend_section(
                    "Short-term conditions", "Recent, fast-moving indices (30 days to ~9 months).",
                    dest_dir / "data" / "stb_timeseries.csv", BLEND_CLASSES,
                ),
                _render_blend_section(
                    "Long-term conditions", "Accumulated, slower-moving indices (6 months to 5 years).",
                    dest_dir / "data" / "ltb_timeseries.csv", BLEND_CLASSES,
                ),
                _render_blend_section(
                    "U.S. Drought Monitor", "The official weekly drought classification.",
                    dest_dir / "data" / "dm_timeseries.csv", USDM_CLASSES,
                ),
            ]))

            eoy_csv = dest_dir / "data" / "ltb_eoy_timeseries.csv"
            gm_csv = dest_dir / "data" / "gm_timeseries.csv"
            gm_wy_csv = dest_dir / "data" / "gm_wy_timeseries.csv"

            figs = {}
            figs["ltb"] = long_term_index_figure(read_eoy_series(eoy_csv)) if eoy_csv.exists() else None

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
            trend_table_html = ""
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
                wy_df = water_year_pivot(gm_wy_csv) if gm_wy_csv.exists() else None
                if wy_df is not None and not wy_df.empty:
                    figs["wy_trend"] = water_year_trend_figure(wy_df)
                    trend_table_html = _render_trend_table(wy_df)
                summary_tables_html = _render_summary_tables(gm_df, wy_df, current_wy)

            bokeh_script, divs = embed_figures(figs)

            page_html = PAGE_TEMPLATE.format(
                name=html.escape(name),
                layer_title=layer_title,
                layer_title_lower=layer_title.lower(),
                run_date=run_date,
                header=_render_header(home_href="../index.html", nav_html=f'<nav><a href="../index.html">&larr; All {layer_title}</a></nav>'),
                disclosure=_find_geometry_fallback_note(raw_dir, slug),
                map_cards=_render_image_cards(dest_dir, layer, slug, MAP_CARDS) or "<p>No current-conditions maps available for this report.</p>",
                blend_sections=blend_sections,
                bokeh_cdn=BOKEH_CDN_TAGS,
                stb_evolution_div=divs.get("stb_evo", "<p>No short-term data available.</p>"),
                ltb_evolution_div=divs.get("ltb_evo", "<p>No long-term data available.</p>"),
                dm_evolution_div=divs.get("dm_evo", "<p>No USDM data available.</p>"),
                ltb_chart_div=divs.get("ltb", "<p>No long-term trend data available.</p>"),
                eto_chart_div=divs.get("eto", "<p>No ETo data available.</p>"),
                precip_chart_div=divs.get("precip", "<p>No precipitation data available.</p>"),
                tmean_chart_div=divs.get("tmean", "<p>No temperature data available.</p>"),
                wy_trend_chart_div=divs.get("wy_trend", "<p>No water-year trend data available.</p>"),
                summary_tables=summary_tables_html,
                trend_table=trend_table_html,
                explainer=EXPLAINER_HTML,
                csv_links=csv_links or "<li>No data files available.</li>",
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
            header=_render_header(home_href="index.html", nav_html=""),
        ),
        encoding="utf-8",
    )

    manifest = {"run_date": run_date, "layers": list(LAYER_TITLES)}
    (SITE_DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    import sys
    build(run_date=sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat())
