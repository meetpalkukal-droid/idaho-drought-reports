"""
Reproject and clean the Idaho groundwater-district and irrigation-organization
boundary layers so they meet Climate Engine's shapefile/FeatureCollection
requirements:
  - geographic CRS (EPSG:4326), coordinates as [lon, lat]
  - exactly one non-numeric (string) column identifying each polygon
  - valid polygon/multipolygon geometries only

Run this whenever the source shapefiles change. Outputs go to
data/processed/ as GeoJSON, ready to upload as Earth Engine table assets
(Assets tab -> New -> Table Upload, or the earthengine CLI).
"""

from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "groundwater_districts": (ROOT / "Groundwater_Districts" / "Groundwater_Districts.shp", "NAME"),
    "irrigation_organizations": (ROOT / "Irrigation_Organizations" / "Irrigation_Organizations.shp", "NAME"),
}
OUT_DIR = ROOT / "data" / "processed"


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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for out_name, (shp_path, name_col) in SOURCES.items():
        cleaned = clean_layer(shp_path, name_col)
        out_path = OUT_DIR / f"{out_name}.geojson"
        cleaned.to_file(out_path, driver="GeoJSON")
        print(f"{shp_path.name}: {len(cleaned)} features -> {out_path}")


if __name__ == "__main__":
    main()
