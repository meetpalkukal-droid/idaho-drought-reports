"""
Call the Climate Engine Reports API to generate a drought report for every
groundwater district / irrigation organization polygon and download the
resulting graphics + CSVs.

Requires environment variables (set as GitHub Actions secrets in production,
or a local .env for testing):
    CE_API_KEY           Climate Engine API key (Authorization header value)
    GW_ASSET_ID            EE asset ID for the uploaded groundwater_districts.json
    IRR_ASSET_ID            EE asset ID for the uploaded irrigation_organizations.json

Optional:
    CE_USER_EMAIL   Leave unset for scheduled/bulk runs -- a real address here
                       makes Climate Engine email a copy of every report (one
                       email per polygon, every run). Only set it for manual
                       one-off testing where you want the email confirmation.

Usage:
    python scripts/fetch_reports.py --layer groundwater_districts --limit 1   # smoke test
    python scripts/fetch_reports.py --layer groundwater_districts
    python scripts/fetch_reports.py --layer irrigation_organizations
    python scripts/fetch_reports.py --layer irrigation_organizations --retry-failed
    python scripts/fetch_reports.py --layer irrigation_organizations --geometry-fallback

Architecture (confirmed against real API responses -- see README "Confirmed
API behavior" and DECISIONS.md): a single feature_collection call is scoped
to ONE polygon (sub_choices/filter_by select it), and a synchronous
(batch=False) call blocks for 1-3+ minutes per polygon -- far too slow to
run 363 times in sequence. So this submits every polygon with batch=True
(returns in ~8s with a status_link to poll).

A first full run against all 350 irrigation organizations confirmed a real
constraint: submitting everything at once (183 concurrent jobs) blew
through Earth Engine's per-project concurrent interactive request quota --
41 jobs failed with an explicit "Too Many Requests: concurrency limit
exceeded" error, and Climate Engine's own submit endpoint started
rejecting further requests too (with a misleading 404 "Endpoint Removed"
body) once ~186 jobs were in flight. So submission is throttled to at most
MAX_IN_FLIGHT concurrently-running jobs (a sliding window: only submit a
new one once an earlier one finishes), not just rate-limited on how fast
we can POST.

Two further failure categories turned out to be fixable, not fundamental
(see DECISIONS.md for the diagnosis): a server-side bug in
feature_collection's geometry handling (bare `'coordinates'` error, hit
complex multi-part polygons) and gridMET's 4km grid missing tiny polygons
entirely ("No valid ... pixels"). Both are worked around by
--geometry-fallback, which resubmits just those names via
/reports/drought/coordinates using geometry read directly from our own
processed boundary file -- unbuffered for the first category (confirmed
fix: the bug is specific to feature_collection's internal extraction, not
the geometry itself), buffered by GEOMETRY_FALLBACK_BUFFER_M for the second
(confirmed fix: guarantees the AOI overlaps a valid gridMET pixel).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Callable

import geopandas as gpd
import requests

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
RAW_OUT_DIR = ROOT / "data" / "reports" / "raw"
EXTRACTED_OUT_DIR = ROOT / "data" / "reports" / "extracted"

API_BASE = "https://api.climateengine.org"
FEATURE_COLLECTION_ENDPOINT = f"{API_BASE}/reports/drought/feature_collection"
COORDINATES_ENDPOINT = f"{API_BASE}/reports/drought/coordinates"
DATASET_DATES_ENDPOINT = f"{API_BASE}/metadata/dataset_dates"


def get_latest_gridmet_drought_date(api_key: str) -> date:
    """Queries Climate Engine's own dataset metadata for the actual max
    date gridMET Drought pentad data is published through, instead of
    guessing from a fixed day count. Confirmed live (see DECISIONS.md
    "Data-driven cadence gate"): dataset=GRIDMET_DROUGHT returns e.g.
    {"Data": {"min": "1980-01-05", "max": "2026-09-12"}} -- that max value
    is the real signal for "has a new pentad actually been published,"
    which a blind N-days-since-last-run counter can never know."""
    resp = requests.get(
        DATASET_DATES_ENDPOINT,
        params={"dataset": "GRIDMET_DROUGHT"},
        headers={"Authorization": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return date.fromisoformat(resp.json()["Data"]["max"])

LAYERS = {
    "groundwater_districts": "GW_ASSET_ID",
    "irrigation_organizations": "IRR_ASSET_ID",
}

# Individual jobs took ~2-5 min in testing.
POLL_INTERVAL_S = 15
JOB_TIMEOUT_S = 20 * 60
IN_PROGRESS_STATUSES = {"running", "pending", "queued", "in_progress", "started"}

# How many jobs may be submitted-but-not-yet-terminal at once. 183
# concurrent jobs reliably exceeded Earth Engine's concurrent interactive
# request quota (see module docstring); this is a conservative starting
# point, not a value confirmed safe at its own ceiling -- see DECISIONS.md.
DEFAULT_MAX_IN_FLIGHT = 15

# Confirmed via live testing (see DECISIONS.md) against the smallest (0.03
# km^2) and largest (1.36 km^2) of the 7 "no valid pixels" polygons --
# both succeeded with a 3km buffer against gridMET's 4km grid.
GEOMETRY_FALLBACK_BUFFER_M = 3000
BUFFER_WORKING_EPSG = 5070  # CONUS Albers equal-area, for a metric buffer


def slugify(name: str) -> str:
    # Climate Engine rejects site_name longer than 35 characters (confirmed
    # via a real 422 response). Verified this doesn't create collisions
    # across either of our 13/350-feature layers before relying on it.
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return slug[:35]


def submit_report(
    *,
    asset_id: str,
    site_name: str,
    filter_value: str,
    filter_by: str,
    api_key: str,
    user_email: str = "",
    end_date: str | None = None,
    timeout: int = 60,
) -> dict:
    """POST an async (batch=True) single-feature report request against a
    FeatureCollection asset. Returns immediately (~8s in testing) with a
    report_link (where the zip will eventually land) and a status_link (a
    status.json to poll)."""
    payload = {
        "feature_collection_asset_id": asset_id,
        "sub_choices": filter_value,
        "filter_by": filter_by,
        "report_version": "v2",
        "user_email": user_email,
        "site_name": slugify(site_name),
        "batch": True,
    }
    if end_date:
        payload["end_date"] = end_date

    resp = requests.post(
        FEATURE_COLLECTION_ENDPOINT,
        json=payload,
        headers={"Authorization": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json().get("Data", {})
    return {
        "site_name": data.get("Site name", site_name),
        "report_link": data.get("Report link"),
        "status_link": data.get("Status link"),
        "raw": data,
    }


def _geometry_to_coords_str(geom) -> str:
    """Serialize a shapely Polygon/MultiPolygon to the coordinates string
    format Climate Engine's /reports/drought/coordinates endpoint expects
    (confirmed against real successful responses -- see DECISIONS.md).
    Interior rings (holes) are dropped; none of our boundary layers rely on
    holes for anything meaningful to a drought report's spatial extent."""
    if geom.geom_type == "MultiPolygon":
        return json.dumps([[list(p.exterior.coords)] for p in geom.geoms])
    return json.dumps([list(geom.exterior.coords)])


def submit_report_coordinates(
    *,
    geometry,
    site_name: str,
    api_key: str,
    user_email: str = "",
    end_date: str | None = None,
    timeout: int = 60,
) -> dict:
    """POST an async (batch=True) report request with explicit polygon
    coordinates instead of an EE FeatureCollection reference. Used as a
    fallback for polygons that fail via feature_collection -- see module
    docstring."""
    payload = {
        "coordinates": _geometry_to_coords_str(geometry),
        "report_version": "v2",
        "user_email": user_email,
        "site_name": slugify(site_name),
        "batch": True,
    }
    if end_date:
        payload["end_date"] = end_date

    resp = requests.post(
        COORDINATES_ENDPOINT,
        json=payload,
        headers={"Authorization": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json().get("Data", {})
    return {
        "site_name": data.get("Site name", site_name),
        "report_link": data.get("Report link"),
        "status_link": data.get("Status link"),
        "raw": data,
    }


def download_and_extract(zip_url: str, dest_dir: Path) -> Path:
    # Climate Engine's images/ filenames embed a per-request UUID, so a
    # re-fetch for the same org (a retry, or re-running a smoke test) would
    # otherwise leave the old UUID's files sitting alongside the new ones
    # rather than being replaced by them.
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
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


def process_jobs(
    job_specs: list[tuple[str, Callable[[], dict]]],
    *,
    raw_dir: Path,
    extracted_dir: Path,
    max_in_flight: int,
) -> None:
    """Generic sliding-window submit/poll/download engine. job_specs is a
    list of (name, submit_fn) pairs; submit_fn() must return a dict with
    status_link/report_link (as submit_report / submit_report_coordinates
    do) or raise requests.HTTPError. Writes a status file per name to
    raw_dir/<slug>.json regardless of outcome, and downloads+extracts into
    extracted_dir/<slug>/ on success."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    to_submit = list(job_specs)
    in_flight: dict[str, dict] = {}
    done = 0
    total = len(job_specs)

    def _submit_next() -> None:
        nonlocal done
        name, submit_fn = to_submit.pop(0)
        slug = slugify(name)
        try:
            job = submit_fn()
        except requests.HTTPError as e:
            done += 1
            body = e.response.text[:300] if e.response is not None else str(e)
            print(f"  [{done}/{total}] SUBMIT ERROR for {name!r}: {e} -- {body}", file=sys.stderr)
            (raw_dir / f"{slug}.json").write_text(json.dumps({"status": "submit_error", "message": body}, indent=2))
            return
        if not job.get("status_link"):
            done += 1
            print(f"  [{done}/{total}] SUBMIT WARNING: no status_link for {name!r}", file=sys.stderr)
            (raw_dir / f"{slug}.json").write_text(json.dumps({"status": "submit_error", "message": "no status_link"}, indent=2))
            return
        in_flight[slug] = {"name": name, "status_link": job["status_link"], "report_link": job.get("report_link"), "submitted_at": time.time()}
        print(f"  submitted {name!r} -> {slug} ({len(in_flight)} in flight)", file=sys.stderr)

    while to_submit or in_flight:
        while to_submit and len(in_flight) < max_in_flight:
            _submit_next()

        for slug, job in list(in_flight.items()):
            try:
                r = requests.get(job["status_link"], timeout=30)
            except requests.RequestException as e:
                print(f"  [{slug}] status check failed: {e}", file=sys.stderr)
                continue
            if r.status_code != 200:
                if time.time() - job["submitted_at"] > JOB_TIMEOUT_S:
                    status = {"status": "timeout"}
                else:
                    continue
            else:
                status = r.json()
                if status.get("status") in IN_PROGRESS_STATUSES:
                    if time.time() - job["submitted_at"] > JOB_TIMEOUT_S:
                        status = {"status": "timeout"}
                    else:
                        continue

            done += 1
            (raw_dir / f"{slug}.json").write_text(json.dumps(status, indent=2))
            del in_flight[slug]

            if status.get("status") == "success":
                zip_url = status.get("report_link") or job.get("report_link")
                if zip_url:
                    try:
                        download_and_extract(zip_url, extracted_dir / slug)
                    except requests.RequestException as e:
                        print(f"  [{done}/{total}] DOWNLOAD ERROR for {job['name']!r}: {e}", file=sys.stderr)
                print(f"  [{done}/{total}] {job['name']!r} success", file=sys.stderr)
            else:
                print(f"  [{done}/{total}] {job['name']!r} ended with status {status.get('status')!r}: {status.get('message')}", file=sys.stderr)

        if to_submit or in_flight:
            time.sleep(POLL_INTERVAL_S)


def _read_statuses(raw_dir: Path, all_names: list[str]) -> dict[str, dict | None]:
    """name -> parsed status dict, or None if no status file exists yet."""
    result = {}
    for name in all_names:
        status_path = raw_dir / f"{slugify(name)}.json"
        if not status_path.exists():
            result[name] = None
            continue
        try:
            result[name] = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            result[name] = None
    return result


def _previously_failed_or_missing(raw_dir: Path, all_names: list[str]) -> list[str]:
    statuses = _read_statuses(raw_dir, all_names)
    return [n for n, s in statuses.items() if s is None or s.get("status") != "success"]


def list_failed_sites(layer: str, run_date: str) -> list[str]:
    """Names that don't have a status:"success" file for this run_date --
    the same check run_layer(retry_failed=True) uses to decide what to
    resubmit, exposed publicly so run_pipeline.py can print an end-of-run
    summary. This is the only way to see what actually failed without
    downloading the raw-status Actions artifact (which needs a GitHub
    token we don't have -- see DECISIONS.md "Second retry pass")."""
    raw_dir = RAW_OUT_DIR / layer / run_date
    geojson_path = PROCESSED_DIR / f"{layer}.json"
    all_names = gpd.read_file(geojson_path)["name"].tolist()
    return _previously_failed_or_missing(raw_dir, all_names)


def run_layer(
    layer: str,
    *,
    limit: int | None,
    end_date: str | None,
    max_in_flight: int = DEFAULT_MAX_IN_FLIGHT,
    retry_failed: bool = False,
) -> None:
    if layer not in LAYERS:
        raise SystemExit(f"unknown layer {layer!r}, expected one of {list(LAYERS)}")

    asset_env = LAYERS[layer]
    asset_id = os.environ.get(asset_env)
    api_key = os.environ.get("CE_API_KEY")
    # Left unset/empty on purpose for scheduled runs: a real address here makes
    # Climate Engine email a copy of every single report (one email per polygon,
    # every 5 days). Only set CE_USER_EMAIL for one-off manual testing.
    user_email = os.environ.get("CE_USER_EMAIL", "")
    if not asset_id or not api_key:
        raise SystemExit(f"missing required env vars: need CE_API_KEY and {asset_env}")

    geojson_path = PROCESSED_DIR / f"{layer}.json"
    gdf = gpd.read_file(geojson_path)
    all_names = gdf["name"].tolist()

    run_date = end_date or time.strftime("%Y-%m-%d")
    raw_dir = RAW_OUT_DIR / layer / run_date
    extracted_dir = EXTRACTED_OUT_DIR / layer / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    if retry_failed:
        names = _previously_failed_or_missing(raw_dir, all_names)
        print(f"--retry-failed: {len(names)}/{len(all_names)} still need a successful report for {run_date}", file=sys.stderr)
    else:
        names = all_names
    if limit:
        names = names[:limit]
    if not names:
        print("Nothing to do.", file=sys.stderr)
        return

    print(f"Processing {len(names)} report(s) for {layer}, up to {max_in_flight} in flight at once...", file=sys.stderr)
    job_specs = [
        (name, lambda n=name: submit_report(
            asset_id=asset_id, site_name=n, filter_value=n, filter_by="name",
            api_key=api_key, user_email=user_email, end_date=end_date,
        ))
        for name in names
    ]
    process_jobs(job_specs, raw_dir=raw_dir, extracted_dir=extracted_dir, max_in_flight=max_in_flight)


# Failure messages confirmed (via live testing, see DECISIONS.md) to be
# fixable by resubmitting via /reports/drought/coordinates rather than
# feature_collection, and whether that resubmission needs the geometry
# buffered first.
_COORDINATES_BUG_MESSAGE = "'coordinates'"


def _fallback_kind(message: str | None) -> str | None:
    if message == _COORDINATES_BUG_MESSAGE:
        return "unbuffered"
    if message and message.startswith("No valid"):
        return "buffered"
    return None


def run_geometry_fallback(
    layer: str,
    *,
    end_date: str | None,
    max_in_flight: int = DEFAULT_MAX_IN_FLIGHT,
) -> None:
    """Resubmit, via /reports/drought/coordinates, any polygon still failing
    after run_layer(..., retry_failed=True) with one of the two confirmed-
    fixable error messages (see module docstring / DECISIONS.md)."""
    api_key = os.environ.get("CE_API_KEY")
    user_email = os.environ.get("CE_USER_EMAIL", "")
    if not api_key:
        raise SystemExit("missing required env var: CE_API_KEY")

    geojson_path = PROCESSED_DIR / f"{layer}.json"
    gdf = gpd.read_file(geojson_path).set_index("name")

    run_date = end_date or time.strftime("%Y-%m-%d")
    raw_dir = RAW_OUT_DIR / layer / run_date
    extracted_dir = EXTRACTED_OUT_DIR / layer / run_date

    statuses = _read_statuses(raw_dir, gdf.index.tolist())
    targets = []  # (name, kind)
    for name, status in statuses.items():
        if status is None or status.get("status") == "success":
            continue
        kind = _fallback_kind(status.get("message"))
        if kind:
            targets.append((name, kind))

    if not targets:
        print("No geometry-fallback-eligible failures found.", file=sys.stderr)
        return
    print(f"Geometry fallback: {len(targets)} name(s) eligible ({sum(1 for _,k in targets if k=='unbuffered')} unbuffered, "
          f"{sum(1 for _,k in targets if k=='buffered')} buffered)", file=sys.stderr)

    # Record which slugs used a buffered AOI, so build_site.py can disclose
    # it on those specific pages -- the buffer changes what the report
    # represents (a 3km neighborhood, not the parcel itself), which is a
    # deliberate, disclosed choice, not a detail to bury (see DECISIONS.md).
    sidecar_path = raw_dir / "_geometry_fallback.json"
    sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {}
    for name, kind in targets:
        if kind == "buffered":
            sidecar[slugify(name)] = {
                "name": name,
                "buffer_m": GEOMETRY_FALLBACK_BUFFER_M,
            }
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    def _geometry_for(name: str, kind: str):
        geom = gdf.loc[name, "geometry"]
        if kind == "buffered":
            proj = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(epsg=BUFFER_WORKING_EPSG)
            buffered = proj.buffer(GEOMETRY_FALLBACK_BUFFER_M)
            geom = gpd.GeoSeries(buffered, crs=BUFFER_WORKING_EPSG).to_crs(epsg=4326).iloc[0]
        return geom

    job_specs = [
        (name, lambda n=name, k=kind: submit_report_coordinates(
            geometry=_geometry_for(n, k), site_name=n,
            api_key=api_key, user_email=user_email, end_date=end_date,
        ))
        for name, kind in targets
    ]
    process_jobs(job_specs, raw_dir=raw_dir, extracted_dir=extracted_dir, max_in_flight=max_in_flight)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True, choices=list(LAYERS))
    parser.add_argument("--limit", type=int, default=None, help="only process the first N features (smoke test)")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD; defaults to today (snaps to nearest available pentad)")
    parser.add_argument("--max-in-flight", type=int, default=DEFAULT_MAX_IN_FLIGHT, help="max concurrently-running jobs")
    parser.add_argument("--retry-failed", action="store_true", help="only (re)process names missing a successful report for --end-date (or today)")
    parser.add_argument("--geometry-fallback", action="store_true", help="resubmit known-fixable failures via the coordinates endpoint instead of feature_collection")
    args = parser.parse_args()
    if args.geometry_fallback:
        run_geometry_fallback(args.layer, end_date=args.end_date, max_in_flight=args.max_in_flight)
    else:
        run_layer(
            args.layer,
            limit=args.limit,
            end_date=args.end_date,
            max_in_flight=args.max_in_flight,
            retry_failed=args.retry_failed,
        )


if __name__ == "__main__":
    main()
