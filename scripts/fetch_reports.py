"""
Call the Climate Engine Reports API to generate a drought report for every
groundwater district / irrigation organization polygon and download the
resulting graphics + CSVs.

Requires environment variables (set as GitHub Actions secrets in production,
or a local .env for testing):
    CE_API_KEY           Climate Engine API key (Authorization header value)
    CE_USER_EMAIL         Email address tied to your Climate Engine account
    GW_ASSET_ID            EE asset ID for the uploaded groundwater_districts.geojson
    IRR_ASSET_ID            EE asset ID for the uploaded irrigation_organizations.geojson

Usage:
    python scripts/fetch_reports.py --layer groundwater_districts --limit 1   # smoke test
    python scripts/fetch_reports.py --layer groundwater_districts
    python scripts/fetch_reports.py --layer irrigation_organizations

NOTE: the Climate Engine Reports API does not publish a formal response
schema (its OpenAPI spec leaves the 200 response body untyped), so
`_find_zip_urls` below parses the response defensively by scanning for any
string value that looks like a URL to a .zip file rather than assuming
specific key names. Run with --limit 1 and inspect the saved raw JSON under
data/reports/raw/ the first time you have a real API key, and adjust
`_find_zip_urls` / the extraction logic if the real shape differs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
RAW_OUT_DIR = ROOT / "data" / "reports" / "raw"
EXTRACTED_OUT_DIR = ROOT / "data" / "reports" / "extracted"

API_BASE = "https://api.climateengine.org"
ENDPOINT = f"{API_BASE}/reports/drought/feature_collection"

LAYERS = {
    "groundwater_districts": "GW_ASSET_ID",
    "irrigation_organizations": "IRR_ASSET_ID",
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return slug[:80]


def generate_report(
    *,
    asset_id: str,
    site_name: str,
    filter_value: str,
    filter_by: str,
    api_key: str,
    user_email: str,
    end_date: str | None = None,
    synchronous: bool = True,
    timeout: int = 300,
) -> dict:
    """POST a single-feature drought report request. synchronous=True (batch=False)
    blocks until the report is ready and should return the final zip location
    directly; verify this against a real response before relying on it."""
    payload = {
        "feature_collection_asset_id": asset_id,
        "sub_choices": filter_value,
        "filter_by": filter_by,
        "report_version": "v2",
        "user_email": user_email,
        "site_name": slugify(site_name),
        "batch": not synchronous,
    }
    if end_date:
        payload["end_date"] = end_date

    resp = requests.post(
        ENDPOINT,
        json=payload,
        headers={"Authorization": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _find_zip_urls(obj) -> list[str]:
    """Recursively scan a parsed JSON response for any string that looks like
    a URL pointing at a .zip file, regardless of the surrounding key names."""
    found = []
    if isinstance(obj, dict):
        for v in obj.values():
            found.extend(_find_zip_urls(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_find_zip_urls(v))
    elif isinstance(obj, str):
        if obj.startswith("http") and urlparse(obj).path.lower().endswith(".zip"):
            found.append(obj)
    return found


def download_and_extract(zip_url: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "report.zip"
    with requests.get(zip_url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    zip_path.unlink()
    return dest_dir


def run_layer(layer: str, *, limit: int | None, end_date: str | None, sleep_s: float) -> None:
    if layer not in LAYERS:
        raise SystemExit(f"unknown layer {layer!r}, expected one of {list(LAYERS)}")

    asset_env = LAYERS[layer]
    asset_id = os.environ.get(asset_env)
    api_key = os.environ.get("CE_API_KEY")
    user_email = os.environ.get("CE_USER_EMAIL")
    if not asset_id or not api_key or not user_email:
        raise SystemExit(
            f"missing required env vars: need CE_API_KEY, CE_USER_EMAIL, and {asset_env}"
        )

    geojson_path = PROCESSED_DIR / f"{layer}.geojson"
    gdf = gpd.read_file(geojson_path)
    names = gdf["name"].tolist()
    if limit:
        names = names[:limit]

    run_date = end_date or time.strftime("%Y-%m-%d")
    raw_dir = RAW_OUT_DIR / layer / run_date
    extracted_dir = EXTRACTED_OUT_DIR / layer / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    for i, name in enumerate(names, 1):
        slug = slugify(name)
        print(f"[{i}/{len(names)}] {name} -> {slug}", file=sys.stderr)
        try:
            result = generate_report(
                asset_id=asset_id,
                site_name=name,
                filter_value=name,
                filter_by="name",
                api_key=api_key,
                user_email=user_email,
                end_date=end_date,
            )
        except requests.HTTPError as e:
            print(f"  ERROR: {e} -- {e.response.text[:500]}", file=sys.stderr)
            continue

        (raw_dir / f"{slug}.json").write_text(json.dumps(result, indent=2))

        zip_urls = _find_zip_urls(result)
        if not zip_urls:
            print(f"  WARNING: no .zip URL found in response for {name!r}; "
                  f"inspect {raw_dir / f'{slug}.json'}", file=sys.stderr)
            continue

        for zip_url in zip_urls:
            download_and_extract(zip_url, extracted_dir / slug)

        if sleep_s:
            time.sleep(sleep_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True, choices=list(LAYERS))
    parser.add_argument("--limit", type=int, default=None, help="only process the first N features (smoke test)")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD; defaults to today (snaps to nearest available pentad)")
    parser.add_argument("--sleep", type=float, default=0.5, help="seconds to sleep between requests")
    args = parser.parse_args()
    run_layer(args.layer, limit=args.limit, end_date=args.end_date, sleep_s=args.sleep)


if __name__ == "__main__":
    main()
