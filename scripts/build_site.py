"""
Build the static site from the most recently fetched Climate Engine drought
report outputs.

Per the project narrative, this does NOT reuse Climate Engine's bundled PDF
report -- it curates specific graphics (the current-conditions maps) and
builds its own content from the CSVs: plain-language drought-class
summaries (now / 3 months ago / 1 year ago) and a hand-drawn long-term
(1986-present) trend chart. See report_content.py for the data work and
DECISIONS.md for the design rationale.
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
    render_long_term_svg,
    summary_snapshots,
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

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — Idaho Drought Report</title>
<link rel="stylesheet" href="../assets/style.css">
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
<p class="meta">Long-term drought blend index, one value per water year. Hover or tab through a point for its exact value.</p>
<div class="chart-wrap">
{chart_svg}
</div>

{explainer}

<h2>Data</h2>
<ul class="data-links">
{csv_links}
</ul>

<script src="../assets/chart.js"></script>
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


def _render_map_cards(dest_dir: Path, layer: str, slug: str) -> str:
    cards = []
    for prefix, title, caption in MAP_CARDS:
        img = _find_image(dest_dir, prefix)
        if not img:
            continue
        rel = f"../data/{layer}/{slug}/images/{img.name}"
        cards.append(
            f'<div class="map-card"><figure><img src="{rel}" alt="{title} map" loading="lazy">'
            f'<figcaption><strong>{title}.</strong> {caption}</figcaption></figure></div>'
        )
    return "\n".join(cards) or "<p>No current-conditions maps available for this report.</p>"


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
            chart_svg = render_long_term_svg(read_eoy_series(eoy_csv), chart_id=f"ltc-{slug}") if eoy_csv.exists() else ""

            page_html = PAGE_TEMPLATE.format(
                name=html.escape(name),
                layer_title=layer_title,
                layer_title_lower=layer_title.lower(),
                run_date=run_date,
                disclosure=_find_geometry_fallback_note(raw_dir, slug),
                map_cards=_render_map_cards(dest_dir, layer, slug),
                blend_sections=blend_sections,
                chart_svg=chart_svg,
                explainer=EXPLAINER_HTML,
                csv_links=csv_links or "<li>No data files available.</li>",
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
