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

# Individual jobs took ~2-5 min in testing.
POLL_INTERVAL_S = 15
JOB_TIMEOUT_S = 20 * 60
IN_PROGRESS_STATUSES = {"running", "pending", "queued", "in_progress", "started"}

# How many jobs may be submitted-but-not-yet-terminal at once. 183
# concurrent jobs reliably exceeded Earth Engine's concurrent interactive
# request quota (see module docstring); this is a conservative starting
# point, not a value confirmed safe at its own ceiling -- see DECISIONS.md.
DEFAULT_MAX_IN_FLIGHT = 15


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
    """POST an async (batch=True) single-feature report request. Returns
    immediately (~8s in testing) with a report_link (where the zip will
    eventually land) and a status_link (a status.json to poll)."""
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
        ENDPOINT,
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


def _previously_failed_or_missing(raw_dir: Path, all_names: list[str]) -> list[str]:
    """Compare all_names against raw_dir/<slug>.json status files from a
    prior run of the same layer+date; returns names that either never got a
    status file (submit-phase error) or ended in a non-success status."""
    slug_to_name = {slugify(n): n for n in all_names}
    todo = []
    for name in all_names:
        slug = slugify(name)
        status_path = raw_dir / f"{slug}.json"
        if not status_path.exists():
            todo.append(name)
            continue
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            todo.append(name)
            continue
        if status.get("status") != "success":
            todo.append(name)
    return todo


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

    to_submit = list(names)
    in_flight: dict[str, dict] = {}  # slug -> {"name":..., "status_link":..., "report_link":..., "submitted_at":...}
    done = 0
    total = len(names)

    def _submit_next() -> None:
        name = to_submit.pop(0)
        slug = slugify(name)
        try:
            job = submit_report(
                asset_id=asset_id,
                site_name=name,
                filter_value=name,
                filter_by="name",
                api_key=api_key,
                user_email=user_email,
                end_date=end_date,
            )
        except requests.HTTPError as e:
            nonlocal done
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True, choices=list(LAYERS))
    parser.add_argument("--limit", type=int, default=None, help="only process the first N features (smoke test)")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD; defaults to today (snaps to nearest available pentad)")
    parser.add_argument("--max-in-flight", type=int, default=DEFAULT_MAX_IN_FLIGHT, help="max concurrently-running jobs")
    parser.add_argument("--retry-failed", action="store_true", help="only (re)process names missing a successful report for --end-date (or today)")
    args = parser.parse_args()
    run_layer(
        args.layer,
        limit=args.limit,
        end_date=args.end_date,
        max_in_flight=args.max_in_flight,
        retry_failed=args.retry_failed,
    )


if __name__ == "__main__":
    main()
