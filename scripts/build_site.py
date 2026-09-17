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
    load_gm_daily,
    mann_kendall_trend,
    normal_band_data,
    water_year_pivot,
    year_to_date_summary,
)
from bokeh_charts import (
    BOKEH_CDN_TAGS,
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

# The remaining 11 of Climate Engine's 14 report graphics (everything except
# the 3 maps above, which are pure raster/no underlying data). Shown in
# full per the project's instruction not to skip any Climate Engine
# graphic, even though several (the *_table images) duplicate what the
# hand-built blend-summary bars above already show, and *_wy_precip_eto and
# *_long_term_trends are annual statistics rather than the ~390-day window
# most of this page focuses on.
ADDITIONAL_GRAPHICS = [
    ("dm_table", "U.S. Drought Monitor -- Class Table", "Climate Engine's own table for the USDM snapshot shown above."),
    ("stb_table", "Short-Term Blend -- Class Table", "Climate Engine's own table for the short-term conditions shown above."),
    ("ltb_table", "Long-Term Blend -- Class Table", "Climate Engine's own table for the long-term conditions shown above."),
    ("ltb_eoy_timeseries", "Long-Term Blend -- Historical Trend (Climate Engine version)", "Climate Engine's own rendering of the same 1986-present series charted interactively in Climate Context below."),
    ("gm_eto_rate", "Reference ETo Rate (Climate Engine version)", "Climate Engine's own rendering of the same chart shown interactively below."),
    ("gm_precip_cum", "Cumulative Precipitation (Climate Engine version)", "Climate Engine's own rendering of the same chart shown interactively below."),
    ("gm_temp_summary", "Temperature Summary (Climate Engine version)", "Climate Engine's own table for the same statistics shown interactively below."),
    ("gm_tmean_rate", "Mean Temperature (Climate Engine version)", "Climate Engine's own rendering of the same chart shown interactively below."),
    ("gm_wb_summary", "Water Balance Summary (Climate Engine version)", "Climate Engine's own table for the same statistics shown interactively below."),
    ("gm_wy_precip_eto_trends", "Water-Year Precipitation & ETo Trends (Climate Engine version)", "Climate Engine's own rendering of the same chart shown interactively below."),
    ("gm_long_term_trends", "Long-Term Climate Trends (Climate Engine version)", "Climate Engine's own table for the same trend statistics shown interactively below."),
]

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
<nav><a href="../index.html">&larr; All {layer_title}</a></nav>
<h1>{name}</h1>
<p class="meta">Report period ending {run_date} &middot; updated every 5 days from Climate Engine's gridMET Drought data.</p>
{disclosure}
<h2>Current conditions</h2>
<div class="map-grid">
{map_cards}
</div>

{blend_sections}

<h2>Long-term trend (1986&ndash;present)</h2>
<p class="meta">Long-term drought blend index, one value per water year. Interactive -- hover a point for its exact value, scroll to zoom.</p>
<div class="bokeh-chart">{ltb_chart_div}</div>

<h2>Climate context</h2>
<p class="meta">Rebuilt from the same climate data Climate Engine's own report graphics use (see "All Climate Engine graphics" below for their versions) -- interactive, hover for exact values.</p>
<div class="bokeh-grid">
<div class="bokeh-chart">{eto_chart_div}</div>
<div class="bokeh-chart">{precip_chart_div}</div>
<div class="bokeh-chart">{tmean_chart_div}</div>
<div class="bokeh-chart">{wy_trend_chart_div}</div>
</div>
{summary_tables}
{trend_table}

<h2>All Climate Engine graphics</h2>
<p class="meta">Every graphic from this report's underlying Climate Engine data, including the ones rebuilt as interactive charts above.</p>
<div class="map-grid">
{additional_graphics}
</div>

{explainer}

<h2>Data</h2>
<ul class="data-links">
{csv_links}
</ul>

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
<nav><a href="../index.html">&larr; Home</a></nav>
<h1>{layer_title}</h1>
<p class="meta">{count} {layer_title_lower}, updated every 5 days.</p>
<input class="search-box" type="search" placeholder="Search by name&hellip;" aria-label="Search {layer_title_lower}">
<ul class="entry-list">
{items}
</ul>
<script src="../assets/search.js"></script>
</body>
</html>
"""

HOME_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Idaho Water User Drought Reports</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<h1>Idaho Water User Drought Reports</h1>
<p>Tailored, jurisdiction-specific drought conditions for Idaho irrigation organizations and groundwater districts &mdash; built on Climate Engine's gridMET Drought data, updated every 5 days.</p>
<p class="meta">Report period ending {run_date}.</p>
<div class="layer-cards">
{cards}
</div>
</body>
</html>
"""


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


def _render_summary_tables(gm_df, wy_df, current_water_year: int) -> str:
    """Rebuild of Climate Engine's gm_temp_summary + gm_wb_summary tables:
    current (year-to-date) value vs. the historical average through the
    same point in the water year, diff, % of average, percentile rank.
    See climate_charts.year_to_date_summary for the methodology, validated
    against Climate Engine's own published numbers in DECISIONS.md."""
    rows_temp = []
    for label, var in [("High temp (°F)", "Tmax"), ("Low temp (°F)", "Tmin"), ("Mean temp (°F)", "Tmean")]:
        r = year_to_date_summary(gm_df, var, current_water_year, cumulative=False)
        if r:
            rows_temp.append((label, r))

    rows_wb = []
    for label, var in [("Precipitation (in)", "Precip"), ("Evap demand (in)", "ETo")]:
        r = year_to_date_summary(gm_df, var, current_water_year, cumulative=True)
        if r:
            rows_wb.append((label, r))

    if not rows_temp and not rows_wb:
        return ""

    def _table(title: str, rows: list[tuple[str, dict]]) -> str:
        body = "".join(
            f"<tr><td>{label}</td><td>{r['current']:.1f}</td><td>{r['average']:.1f}</td>"
            f"<td>{r['diff']:+.1f}</td><td>{r['pct_of_avg']:.0f}%</td><td>{_ordinal(r['percentile'])}</td></tr>"
            for label, r in rows
        )
        return f"""
<div class="stat-table">
  <h3>{title}</h3>
  <table>
    <thead><tr><th></th><th>This year</th><th>Average</th><th>Diff</th><th>% of avg</th><th>Percentile</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</div>""".strip()

    parts = []
    if rows_temp:
        parts.append(_table("Temperature summary", rows_temp))
    if rows_wb:
        parts.append(_table("Water balance summary", rows_wb))
    return "\n".join(parts)


def _render_trend_table(wy_df) -> str:
    """Rebuild of Climate Engine's gm_long_term_trends table: Mann-Kendall
    trend + significance per decade for each water-year variable."""
    if wy_df is None or wy_df.empty:
        return ""
    years = wy_df.index.to_numpy()
    specs = [("High temp", "Tmax", "°F"), ("Low temp", "Tmin", "°F"),
             ("Precipitation", "Precip", "in"), ("Evap demand", "ETo", "in")]
    if "Precip" in wy_df.columns and "ETo" in wy_df.columns:
        wy_df = wy_df.copy()
        wy_df["Precip_minus_ETo"] = wy_df["Precip"] - wy_df["ETo"]
        specs.append(("Precip − Evap demand", "Precip_minus_ETo", "in"))

    rows = []
    for label, col, unit in specs:
        if col not in wy_df.columns:
            continue
        t = mann_kendall_trend(years, wy_df[col].to_numpy())
        sig = t["pvalue"] < 0.05
        rows.append(
            f"<tr><td>{label}</td><td>{t['mean']:.1f} {unit}</td>"
            f"<td>{t['slope_per_decade']:+.2f} {unit}/decade</td>"
            f"<td class=\"{'sig' if sig else ''}\">{'* ' if sig else ''}p = {t['pvalue']:.3f}</td></tr>"
        )
    if not rows:
        return ""
    return f"""
<div class="stat-table">
  <h3>Long-term climate trends</h3>
  <p class="meta">Mann-Kendall trend test; * marks a statistically significant trend (p &lt; 0.05).</p>
  <table>
    <thead><tr><th></th><th>Average</th><th>Trend</th><th>Significance</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
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
                disclosure=_find_geometry_fallback_note(raw_dir, slug),
                map_cards=_render_image_cards(dest_dir, layer, slug, MAP_CARDS) or "<p>No current-conditions maps available for this report.</p>",
                blend_sections=blend_sections,
                bokeh_cdn=BOKEH_CDN_TAGS,
                ltb_chart_div=divs.get("ltb", "<p>No long-term trend data available.</p>"),
                eto_chart_div=divs.get("eto", "<p>No ETo data available.</p>"),
                precip_chart_div=divs.get("precip", "<p>No precipitation data available.</p>"),
                tmean_chart_div=divs.get("tmean", "<p>No temperature data available.</p>"),
                wy_trend_chart_div=divs.get("wy_trend", "<p>No water-year trend data available.</p>"),
                summary_tables=summary_tables_html,
                trend_table=trend_table_html,
                additional_graphics=_render_image_cards(dest_dir, layer, slug, ADDITIONAL_GRAPHICS) or "<p>No additional graphics available for this report.</p>",
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
            ),
            encoding="utf-8",
        )
        home_cards.append(
            f'<div class="layer-card"><h2>{layer_title}</h2>'
            f'<p>{len(index_items)} {layer_title.lower()} with current reports.</p>'
            f'<a href="{layer}/index.html">Browse &rarr;</a></div>'
        )

    (SITE_DIR / "index.html").write_text(
        HOME_TEMPLATE.format(run_date=run_date, cards="\n".join(home_cards)), encoding="utf-8"
    )

    manifest = {"run_date": run_date, "layers": list(LAYER_TITLES)}
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    import sys
    build(run_date=sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat())
