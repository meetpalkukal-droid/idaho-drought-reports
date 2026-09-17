"""
Reproject and clean the Idaho groundwater-district and irrigation-organization
boundary layers so they meet Climate Engine's shapefile/FeatureCollection
requirements:
  - geographic CRS (EPSG:4326), coordinates as [lon, lat]
  - exactly one non-numeric (string) column identifying each polygon
  - valid polygon/multipolygon geometries only

Run this whenever the source shapefiles change. Outputs go to
data/processed/:
  - <name>.json  GeoJSON, used internally by the other scripts in this repo
  - <name>.zip   zipped shapefile (.shp/.shx/.dbf/.prj/.cpg), for Earth
                 Engine's "Table Upload" dialog, which only accepts shp,
                 zip, dbf, prj, shx, cpg, fix, qix, sbn or shp.xml -- a
                 bare .json/.geojson is rejected there.
"""

import shutil
import zipfile
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "groundwater_districts": (ROOT / "Groundwater_Districts" / "Groundwater_Districts.shp", "NAME"),
    "irrigation_organizations": (ROOT / "Irrigation_Organizations" / "Irrigation_Organizations.shp", "NAME"),
}
OUT_DIR = ROOT / "data" / "processed"

# Climate Engine's own reports API rate-limits at 200 req/hour and 500
# req/day, UNCONDITIONALLY -- linking our own Earth Engine project removes
# the separate EE *compute* quota, but not this one (confirmed via their
# published quota policy page, see DECISIONS.md). At ~1 submit + ~2-3
# status polls + 1 download per polygon, all 350 irrigation organizations
# cannot fit in a single day's budget alongside the 13 groundwater
# districts -- a live run confirmed this empirically (a clean cutoff
# partway through, then the account got rate-limited account-wide for
# hours). Restricted to a curated 52: the 7 Surface Water Coalition
# members (the senior surface-water right holders on the Snake River,
# central to Idaho's groundwater-surface water conflict this project is
# about) plus the next 45 largest by acreage -- user-directed selection,
# see DECISIONS.md "Irrigation organization scope cut" for the full
# rationale and the rejected alternatives (spreading across the 5-day
# window, paying for a higher limit).
IRRIGATION_ORG_PRIORITY_LIST = [
    "A & B IRRIGATION DISTRICT",
    "AMERICAN FALLS RESERVOIR DIST #2",
    "BURLEY IRRIGATION DISTRICT",
    "MILNER IRRIGATION DISTRICT",
    "MINIDOKA IRRIGATION DISTRICT",
    "NORTH SIDE CANAL COMPANY LTD",
    "TWIN FALLS CANAL COMPANY",
    "PAHSIMEROI IRRIGATION DIST",
    "FREMONT MADISON IRRIGATION DISTRICT",
    "BOISE PROJECT BOARD OF CONTROL",
    "BIG WOOD CANAL COMPANY",
    "OAKLEY CANAL CO",
    "SOUTHWEST IRRIGATION DISTRICT",
    "BLACK CANYON IRRIGATION DISTRICT",
    "LAKE RESERVOIR CO",
    "ABERDEEN SPRINGFIELD CANAL CO",
    "NAMPA & MERIDIAN IRRIGATION DISTRICT",
    "WILDER IRRIGATION DISTRICT",
    "BOISE KUNA IRRIGATION DISTRICT",
    "LAST CHANCE CANAL CO LTD",
    "SALMON RIVER CANAL CO LTD",
    "BIG LOST RIVER IRRIGATION DISTRICT",
    "GEM IRRIGATION DISTRICT",
    "NORTH FORK RESERVOIR CO",
    "PROGRESSIVE IRRIGATION DISTRICT",
    "IDAHO IRRIGATION DISTRICT",
    "CONSOLIDATED IRRIGATION CO",
    "NORTH FREMONT CANAL SYSTEMS INC",
    "EGIN BENCH CANALS INC",
    "PIONEER IRRIGATION DISTRICT",
    "TWIN LAKES CANAL CO",
    "MUD LAKE WATER USERS INC",
    "NEW SWEDEN IRRIGATION DISTRICT",
    "FALLS IRRIGATION DISTRICT",
    "GOOSE CREEK IRRIGATION DISTRICT",
    "BURGESS CANAL & IRRIGATING CO",
    "CRANE CREEK RESERVOIR ADMINISTRATION BOARD",
    "BUTTE & MARKET LAKE CANAL CO",
    "EMMETT IRRIGATION DISTRICT",
    "BELL RAPIDS MUTUAL IRRIGATION CO/STATE OF IDAHO",
    "SNAKE RIVER VALLEY IRRIGATION DISTRICT",
    "KING HILL IRRIGATION DISTRICT",
    "SOUTHEAST IDAHO CANAL CO",
    "FARMERS COOPERATIVE DITCH CO",
    "PEOPLES CANAL & IRRIGATION CO",
    "LOWER PAYETTE DITCH CO",
    "CANYON CREEK CANAL CO INC",
    "BLACKFOOT IRRIGATION CO",
    "FARMERS COOPERATIVE IRRIGATION CO LTD",
    "NEW YORK IRRIGATION DISTRICT",
    "TETON PIPELINE ASSN INC",
    "LOST VALLEY RESERVOIR CO",
]


def clean_layer(shp_path: Path, name_col: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(shp_path)

    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

    gdf = gdf.to_crs(epsg=4326)

    out = gpd.GeoDataFrame(
        {"name": gdf[name_col].astype(str).str.strip()},
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )

    dupes = out["name"][out["name"].duplicated(keep=False)]
    if not dupes.empty:
        raise ValueError(f"{shp_path.name}: duplicate names found: {sorted(dupes.unique())}")
    if (out["name"] == "").any():
        raise ValueError(f"{shp_path.name}: blank name values found")
    if not out.geometry.is_valid.all():
        raise ValueError(f"{shp_path.name}: geometries still invalid after buffer(0) fix")

    return out


def write_zipped_shapefile(gdf: gpd.GeoDataFrame, out_name: str) -> Path:
    tmp_dir = OUT_DIR / f"_{out_name}_shp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    shp_path = tmp_dir / f"{out_name}.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    zip_path = OUT_DIR / f"{out_name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(tmp_dir.iterdir()):
            zf.write(f, arcname=f.name)

    shutil.rmtree(tmp_dir)
    return zip_path


# Simplification tolerance (degrees) for the homepage selector map only --
# the full-precision geometry above is what's sent to Climate Engine, this
# is purely for a lightweight, fast-loading Leaflet map. ~0.002deg is
# roughly 150-200m at Idaho's latitude, small relative to these polygons'
# scale but cuts combined file size from ~4.8MB to ~675KB.
MAP_SIMPLIFY_TOLERANCE = 0.002


def write_map_geojson(layers: dict[str, gpd.GeoDataFrame]) -> Path:
    import re as _re

    frames = []
    for layer_key, gdf in layers.items():
        simplified = gdf.copy()
        simplified["geometry"] = gdf.geometry.simplify(MAP_SIMPLIFY_TOLERANCE, preserve_topology=True)
        simplified["layer"] = layer_key
        simplified["slug"] = simplified["name"].map(lambda n: _re.sub(r"[^A-Za-z0-9]+", "_", n).strip("_")[:35])
        frames.append(simplified)

    import pandas as pd
    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    out_path = OUT_DIR / "map_boundaries.json"
    combined.to_file(out_path, driver="GeoJSON")
    return out_path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cleaned_layers = {}
    for out_name, (shp_path, name_col) in SOURCES.items():
        cleaned = clean_layer(shp_path, name_col)

        if out_name == "irrigation_organizations":
            missing = set(IRRIGATION_ORG_PRIORITY_LIST) - set(cleaned["name"])
            if missing:
                raise ValueError(f"priority list names not found in source data: {sorted(missing)}")
            cleaned = cleaned[cleaned["name"].isin(IRRIGATION_ORG_PRIORITY_LIST)].reset_index(drop=True)

        json_path = OUT_DIR / f"{out_name}.json"
        cleaned.to_file(json_path, driver="GeoJSON")

        zip_path = write_zipped_shapefile(cleaned, out_name)
        cleaned_layers[out_name] = cleaned

        print(f"{shp_path.name}: {len(cleaned)} features -> {json_path}, {zip_path}")

    map_path = write_map_geojson(cleaned_layers)
    print(f"Homepage selector map: {map_path}")


if __name__ == "__main__":
    main()
