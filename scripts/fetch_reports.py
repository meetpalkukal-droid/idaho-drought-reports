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

Architecture (confirmed against real API responses -- see README "Confirmed
API behavior"): a single feature_collection call is scoped to ONE polygon
(sub_choices/filter_by select it), and a synchronous (batch=False) call
blocks for 1-3+ minutes per polygon -- far too slow to run 363 times in
sequence. So this submits every polygon with batch=True (returns in ~8s
with a status_link to poll), then polls all outstanding jobs in a single
round-robin loop until each reports status "success" (or an error/timeout),
then downloads+extracts the resulting zip.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Terminal-state polling: individual jobs took ~2-3 min in testing.
POLL_INTERVAL_S = 20
POLL_TIMEOUT_S = 20 * 60
IN_PROGRESS_STATUSES = {"running", "pending", "queued", "in_progress", "started"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return slug[:80]


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


def poll_all(jobs: dict[str, dict]) -> dict[str, dict]:
    """jobs: slug -> job dict (must have 'status_link'). Round-robin polls
    every outstanding job's status_link until each reaches a terminal state
    (status != IN_PROGRESS_STATUSES) or POLL_TIMEOUT_S elapses. Returns
    slug -> final status dict (may include {'status': 'timeout'})."""
    pending = dict(jobs)
    results: dict[str, dict] = {}
    t0 = time.time()

    while pending:
        for slug, job in list(pending.items()):
            if not job.get("status_link"):
                results[slug] = {"status": "error", "message": "no status_link in submit response"}
                del pending[slug]
                continue
            try:
                r = requests.get(job["status_link"], timeout=30)
            except requests.RequestException as e:
                print(f"  [{slug}] status check failed: {e}", file=sys.stderr)
                continue
            if r.status_code != 200:
                continue  # zip/status not written to GCS yet
            data = r.json()
            if data.get("status") not in IN_PROGRESS_STATUSES:
                results[slug] = data
                del pending[slug]
                print(f"  [{slug}] {data.get('status')} after {time.time()-t0:.0f}s", file=sys.stderr)

        if pending and time.time() - t0 > POLL_TIMEOUT_S:
            for slug in pending:
                results[slug] = {"status": "timeout"}
            print(f"  TIMEOUT: {len(pending)} job(s) still pending after {POLL_TIMEOUT_S}s: {list(pending)}", file=sys.stderr)
            break

        if pending:
            time.sleep(POLL_INTERVAL_S)

    return results


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


def run_layer(
    layer: str,
    *,
    limit: int | None,
    end_date: str | None,
    submit_concurrency: int = 4,
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

    geojson_path = PROCESSED_DIR / f"{layer}.geojson"
    gdf = gpd.read_file(geojson_path)
    names = gdf["name"].tolist()
    if limit:
        names = names[:limit]

    run_date = end_date or time.strftime("%Y-%m-%d")
    raw_dir = RAW_OUT_DIR / layer / run_date
    extracted_dir = EXTRACTED_OUT_DIR / layer / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: submit every polygon (async), a handful at a time.
    print(f"Submitting {len(names)} report(s) for {layer} ({submit_concurrency} at a time)...", file=sys.stderr)
    jobs: dict[str, dict] = {}
    name_by_slug: dict[str, str] = {}

    def _submit_one(name: str):
        slug = slugify(name)
        job = submit_report(
            asset_id=asset_id,
            site_name=name,
            filter_value=name,
            filter_by="name",
            api_key=api_key,
            user_email=user_email,
            end_date=end_date,
        )
        return slug, name, job

    with ThreadPoolExecutor(max_workers=submit_concurrency) as pool:
        futures = [pool.submit(_submit_one, name) for name in names]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                slug, name, job = fut.result()
            except requests.HTTPError as e:
                print(f"  [{i}/{len(names)}] SUBMIT ERROR: {e} -- {e.response.text[:300]}", file=sys.stderr)
                continue
            name_by_slug[slug] = name
            jobs[slug] = job
            print(f"  [{i}/{len(names)}] submitted {name!r} -> {slug}", file=sys.stderr)

    # Phase 2: poll until each job finishes (or times out).
    print(f"Polling {len(jobs)} job(s) for completion...", file=sys.stderr)
    final = poll_all(jobs)

    # Phase 3: download + extract whatever succeeded.
    for slug, status in final.items():
        (raw_dir / f"{slug}.json").write_text(json.dumps(status, indent=2))
        if status.get("status") != "success":
            print(f"  WARNING: {name_by_slug.get(slug, slug)!r} ended with status {status.get('status')!r}: "
                  f"{status.get('message')}", file=sys.stderr)
            continue
        zip_url = status.get("report_link") or jobs[slug].get("report_link")
        if not zip_url:
            print(f"  WARNING: no report_link for {slug!r}; inspect {raw_dir / f'{slug}.json'}", file=sys.stderr)
            continue
        download_and_extract(zip_url, extracted_dir / slug)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True, choices=list(LAYERS))
    parser.add_argument("--limit", type=int, default=None, help="only process the first N features (smoke test)")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD; defaults to today (snaps to nearest available pentad)")
    parser.add_argument("--submit-concurrency", type=int, default=4, help="parallel submit requests")
    args = parser.parse_args()
    run_layer(args.layer, limit=args.limit, end_date=args.end_date, submit_concurrency=args.submit_concurrency)


if __name__ == "__main__":
    main()
