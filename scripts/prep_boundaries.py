"""
Reproject and clean the Idaho groundwater-district, irrigation-organization,
and water-district boundary layers so they meet Climate Engine's
shapefile/FeatureCollection requirements:
  - geographic CRS (EPSG:4326), coordinates as [lon, lat]
  - exactly one non-numeric (string) column identifying each polygon
  - valid polygon/multipolygon geometries only

Run this whenever the source shapefiles change (or to refresh water
districts from IDWR's live service). Outputs go to data/processed/:
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
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "processed"

WATER_DISTRICTS_URL = "https://gis.idwr.idaho.gov/hosting/rest/services/Regulatory/WaterDistricts/MapServer/0/query"

# Climate Engine's own reports API rate-limits at 200 req/hour and 500
# req/day, UNCONDITIONALLY -- confirmed via their published quota policy
# page, see DECISIONS.md. Irrigation organizations were originally cut from
# 363 down to a curated 52 (7 Surface Water Coalition + 45 by acreage) to
# fit this budget in a single pass; now cut further to JUST the 7 SWC
# members (the senior surface-water right holders on the Snake River,
# central to the groundwater-surface water conflict this project is about)
# to make room for adding all of Idaho's water districts instead -- see
# DECISIONS.md "Add water districts, cut irrigation orgs to SWC-only" for
# the full rationale and the 3-part chunked-submission strategy that keeps
# the resulting ~121-polygon total comfortably under the hourly quota.
IRRIGATION_ORG_PRIORITY_LIST = [
    "A & B IRRIGATION DISTRICT",
    "AMERICAN FALLS RESERVOIR DIST #2",
    "BURLEY IRRIGATION DISTRICT",
    "MILNER IRRIGATION DISTRICT",
    "MINIDOKA IRRIGATION DISTRICT",
    "NORTH SIDE CANAL COMPANY LTD",
    "TWIN FALLS CANAL COMPANY",
]


def load_shapefile(shp_path: Path, name_col: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(shp_path)
    return gpd.GeoDataFrame(
        {"name": gdf[name_col].astype(str).str.strip()},
        geometry=gdf.geometry,
        crs=gdf.crs,
    )


def load_water_districts() -> gpd.GeoDataFrame:
    """Idaho water districts (created under Idaho Code 42-604), fetched
    live from IDWR's own ArcGIS REST service -- there's no local shapefile
    for this layer, unlike groundwater districts/irrigation organizations.
    Active status only: Inactive districts (21 of 122) have no current
    watermaster or operations, so they add nothing to a current-conditions
    drought site -- user-directed scope choice, see DECISIONS.md. DISTAME
    alone isn't unique (several districts share a name, e.g. three separate
    "Birch Creek" districts), so the boundary name combines the DISTRICT
    code with DISTAME, matching Climate Engine's single-unique-name-column
    requirement."""
    resp = requests.get(
        WATER_DISTRICTS_URL,
        params={
            "where": "STATUS='Active'",
            "outFields": "DISTRICT,DISTAME,STATUS",
            "outSR": "4326",
            "f": "geojson",
        },
        timeout=60,
    )
    resp.raise_for_status()
    features = resp.json()["features"]
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    name = gdf["DISTRICT"].astype(str).str.strip() + " " + gdf["DISTAME"].astype(str).str.strip()
    return gpd.GeoDataFrame({"name": name}, geometry=gdf.geometry, crs="EPSG:4326")


SOURCES = {
    "groundwater_districts": lambda: load_shapefile(ROOT / "Groundwater_Districts" / "Groundwater_Districts.shp", "NAME"),
    "irrigation_organizations": lambda: load_shapefile(ROOT / "Irrigation_Organizations" / "Irrigation_Organizations.shp", "NAME"),
    "water_districts": load_water_districts,
}


def clean_layer(raw: gpd.GeoDataFrame, source_label: str) -> gpd.GeoDataFrame:
    gdf = raw.copy()
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

    gdf = gdf.to_crs(epsg=4326)

    out = gpd.GeoDataFrame(
        {"name": gdf["name"].astype(str).str.strip()},
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )

    dupes = out["name"][out["name"].duplicated(keep=False)]
    if not dupes.empty:
        raise ValueError(f"{source_label}: duplicate names found: {sorted(dupes.unique())}")
    if (out["name"] == "").any():
        raise ValueError(f"{source_label}: blank name values found")
    if not out.geometry.is_valid.all():
        raise ValueError(f"{source_label}: geometries still invalid after buffer(0) fix")

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
# scale but cuts combined file size substantially.
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
    for out_name, loader in SOURCES.items():
        raw = loader()
        cleaned = clean_layer(raw, out_name)

        if out_name == "irrigation_organizations":
            missing = set(IRRIGATION_ORG_PRIORITY_LIST) - set(cleaned["name"])
            if missing:
                raise ValueError(f"priority list names not found in source data: {sorted(missing)}")
            cleaned = cleaned[cleaned["name"].isin(IRRIGATION_ORG_PRIORITY_LIST)].reset_index(drop=True)

        json_path = OUT_DIR / f"{out_name}.json"
        cleaned.to_file(json_path, driver="GeoJSON")

        zip_path = write_zipped_shapefile(cleaned, out_name)
        cleaned_layers[out_name] = cleaned

        print(f"{out_name}: {len(cleaned)} features -> {json_path}, {zip_path}")

    map_path = write_map_geojson(cleaned_layers)
    print(f"Homepage selector map: {map_path}")


if __name__ == "__main__":
    main()
