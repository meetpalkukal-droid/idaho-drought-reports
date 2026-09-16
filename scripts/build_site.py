"""
Build the static site from the most recently fetched Climate Engine drought
report outputs.

This is a first-pass scaffold: it discovers whatever image/CSV files Climate
Engine returned for each polygon and lays out a simple page per
district/organization plus an index. The exact filenames inside a Climate
Engine report zip aren't documented anywhere, so once we have a real sample
(run fetch_reports.py --limit 1 with real credentials), re-check
`_classify_asset` below and adjust it to pick out the specific current-
conditions map / summary table / time-series chart the narrative calls for,
and to add the plain-language interpretation text per index.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd

from fetch_reports import slugify

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
EXTRACTED_DIR = ROOT / "data" / "reports" / "extracted"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"

LAYER_TITLES = {
    "groundwater_districts": "Groundwater Districts",
    "irrigation_organizations": "Irrigation Organizations",
}

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name} — Idaho Drought Report</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<nav><a href="../index.html">&larr; All {layer_title}</a></nav>
<h1>{name}</h1>
<p class="meta">Report period ending {run_date}. Updated every 5 days from Climate Engine gridMET Drought data.</p>
{images}
{csv_links}
</body>
</html>
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{layer_title} — Idaho Drought Reports</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<nav><a href="../index.html">&larr; Home</a></nav>
<h1>{layer_title}</h1>
<ul>
{items}
</ul>
</body>
</html>
"""

HOME_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Idaho Water User Drought Reports</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<h1>Idaho Water User Drought Reports</h1>
<p>Tailored drought conditions for Idaho irrigation organizations and groundwater districts, updated every 5 days.</p>
<ul>
{items}
</ul>
</body>
</html>
"""


def _classify_asset(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        return "image"
    if suffix == ".csv":
        return "csv"
    return "other"


def build(run_date: str) -> None:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "assets").mkdir(exist_ok=True)

    home_items = []
    for layer, layer_title in LAYER_TITLES.items():
        layer_extracted_dir = EXTRACTED_DIR / layer / run_date
        if not layer_extracted_dir.exists():
            continue

        layer_site_dir = SITE_DIR / layer
        layer_data_dir = SITE_DATA_DIR / layer
        layer_site_dir.mkdir(parents=True, exist_ok=True)
        layer_data_dir.mkdir(parents=True, exist_ok=True)

        gdf = gpd.read_file(PROCESSED_DIR / f"{layer}.json")
        slug_to_name = {slugify(name): name for name in gdf["name"]}

        index_items = []
        for site_dir in sorted(layer_extracted_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            slug = site_dir.name
            name = slug_to_name.get(slug, slug)

            dest_dir = layer_data_dir / slug
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            # Skip reports/ (Climate Engine's bundled PDF + a rendered PNG of
            # that same PDF) and the CSV-schema README -- per the project
            # narrative we build our own reports from the graphics/data, not
            # Climate Engine's PDF.
            shutil.copytree(site_dir, dest_dir, ignore=shutil.ignore_patterns("reports", "README.md"))

            images, csvs = [], []
            for f in sorted(dest_dir.rglob("*")):
                if not f.is_file():
                    continue
                rel = f"../data/{layer}/{slug}/{f.relative_to(dest_dir)}"
                kind = _classify_asset(f)
                if kind == "image":
                    images.append(f'<img src="{rel}" alt="{f.name}">')
                elif kind == "csv":
                    csvs.append(f'<li><a href="{rel}">{f.name}</a></li>')

            page_html = PAGE_TEMPLATE.format(
                name=name,
                layer_title=layer_title,
                run_date=run_date,
                images="\n".join(images) or "<p>No graphics found in this report yet.</p>",
                csv_links=("<h2>Data (CSV)</h2><ul>" + "".join(csvs) + "</ul>") if csvs else "",
            )
            (layer_site_dir / f"{slug}.html").write_text(page_html, encoding="utf-8")
            index_items.append(f'<li><a href="{slug}.html">{name}</a></li>')

        (layer_site_dir / "index.html").write_text(
            INDEX_TEMPLATE.format(layer_title=layer_title, items="\n".join(index_items)),
            encoding="utf-8",
        )
        home_items.append(f'<li><a href="{layer}/index.html">{layer_title}</a></li>')

    (SITE_DIR / "index.html").write_text(
        HOME_TEMPLATE.format(items="\n".join(home_items)), encoding="utf-8"
    )

    manifest = {"run_date": run_date, "layers": list(LAYER_TITLES)}
    (SITE_DATA_DIR).mkdir(parents=True, exist_ok=True)
    (SITE_DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    import sys
    build(run_date=sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat())
