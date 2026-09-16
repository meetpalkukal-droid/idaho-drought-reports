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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for out_name, (shp_path, name_col) in SOURCES.items():
        cleaned = clean_layer(shp_path, name_col)

        json_path = OUT_DIR / f"{out_name}.json"
        cleaned.to_file(json_path, driver="GeoJSON")

        zip_path = write_zipped_shapefile(cleaned, out_name)

        print(f"{shp_path.name}: {len(cleaned)} features -> {json_path}, {zip_path}")


if __name__ == "__main__":
    main()
