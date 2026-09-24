"""
Entry point for the scheduled GitHub Actions job. Runs only when Climate
Engine's gridMET Drought dataset has actually published a new pentad since
our last successful run -- checked directly against Climate Engine's own
/metadata/dataset_dates endpoint (dataset=GRIDMET_DROUGHT), not guessed
from a fixed day count. See DECISIONS.md "Data-driven cadence gate" for
why: a blind "5 days since last run" counter can't tell a delayed
publication from an on-time one, and can't self-correct if gridMET's
actual cadence ever shifts.

With water districts added, the full run is ~121 polygons -- too many to
submit (plus retries) within a single rolling hour without risking
Climate Engine's 200 req/hour cap. So this splits the combined polygon
list into CHUNK_COUNT roughly-equal chunks and fully processes one chunk
(initial submit + both retry passes + geometry fallback) before moving to
the next, waiting CHUNK_INTERVAL_MINUTES between chunks -- see
DECISIONS.md "Add water districts, cut irrigation orgs to SWC-only" for
the quota math this is sized against.

    python scripts/run_pipeline.py          # runs only if a new pentad is available
    python scripts/run_pipeline.py --force  # runs regardless (for manual testing)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd

from fetch_reports import (
    run_layer,
    run_geometry_fallback,
    get_latest_gridmet_drought_date,
    list_failed_sites,
    LAYERS,
    PROCESSED_DIR,
    DEFAULT_MAX_IN_FLIGHT,
)
from build_site import build

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "reports" / "state.json"
FAILURES_PATH = ROOT / "data" / "reports" / "last_run_failures.json"
RETRY_BACKOFF_S = 45
CHUNK_COUNT = 3
CHUNK_INTERVAL_MINUTES = 60
# Water district polygons are dramatically larger than groundwater/
# irrigation ones -- a live run at the default concurrency (15) showed
# roughly half of them timing out (20 min each) under contention, even
# though an isolated single request finishes in ~2-6 min. Lower
# concurrency trades raw parallelism for reliability: fewer jobs compete
# for Earth Engine's compute capacity at once, so more finish within the
# timeout on their first attempt instead of needing a full, expensive
# resubmit. See DECISIONS.md "Water district timeouts under concurrent
# load".
LAYER_MAX_IN_FLIGHT = {
    "water_districts": 5,
}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text())


def save_state(*, last_data_date: date, checked_on: date) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "last_data_date": last_data_date.isoformat(),
        "last_checked": checked_on.isoformat(),
    }, indent=2))


def build_chunks(limit: int | None) -> list[dict[str, list[str]]]:
    """One flat (layer, name) list across every layer, in a fixed order,
    sliced into CHUNK_COUNT roughly-equal contiguous pieces. Returns a
    list of {layer: [names in this chunk]} dicts, one per chunk, so each
    chunk's per-layer calls only need to know their own names -- see
    fetch_reports.run_layer's names_override."""
    flat: list[tuple[str, str]] = []
    for layer in LAYERS:
        names = gpd.read_file(PROCESSED_DIR / f"{layer}.json")["name"].tolist()
        if limit:
            names = names[:limit]
        flat.extend((layer, n) for n in names)

    total = len(flat)
    chunk_size = -(-total // CHUNK_COUNT)  # ceil division
    chunks = []
    for i in range(0, total, chunk_size):
        piece = flat[i:i + chunk_size]
        by_layer: dict[str, list[str]] = {}
        for layer, name in piece:
            by_layer.setdefault(layer, []).append(name)
        chunks.append(by_layer)
    return chunks


def process_chunk(chunk: dict[str, list[str]], *, run_date: str, api_end_date: str, limit: int | None) -> None:
    for layer, names in chunk.items():
        max_in_flight = LAYER_MAX_IN_FLIGHT.get(layer, DEFAULT_MAX_IN_FLIGHT)
        run_layer(layer, limit=limit, end_date=run_date, api_end_date=api_end_date,
                  names_override=names, max_in_flight=max_in_flight)
        # Two automatic retry passes, with a short backoff between them:
        # transient failures (concurrency-limit errors, network blips) are
        # expected at some rate every run -- see DECISIONS.md "Second
        # retry pass". A single immediate retry wasn't enough in practice
        # (confirmed: a site that failed twice in one run succeeded on a
        # plain manual retry minutes later), so this backs off briefly to
        # give whatever caused the transient failure room to clear before
        # trying again.
        time.sleep(RETRY_BACKOFF_S)
        run_layer(layer, limit=limit, end_date=run_date, api_end_date=api_end_date,
                  retry_failed=True, names_override=names, max_in_flight=max_in_flight)
        # Anything still failing with one of the confirmed-fixable error
        # messages (a Climate Engine server-side bug on complex
        # geometries, gridMET's 4km grid missing tiny polygons, or the
        # comma-in-name sub_choices parsing bug) gets resubmitted via the
        # coordinates endpoint instead -- see DECISIONS.md and the
        # fetch_reports.py module docstring.
        run_geometry_fallback(layer, end_date=run_date, api_end_date=api_end_date, max_in_flight=max_in_flight)
        # A last retry pass catches anything the fallback didn't touch
        # (a different, unrecognized error) that might still just be
        # transient.
        time.sleep(RETRY_BACKOFF_S)
        run_layer(layer, limit=limit, end_date=run_date, api_end_date=api_end_date,
                  retry_failed=True, names_override=names, max_in_flight=max_in_flight)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="cap features per layer (smoke test)")
    args = parser.parse_args()

    api_key = os.environ.get("CE_API_KEY")
    if not api_key:
        raise SystemExit("missing required env var: CE_API_KEY")

    today = date.today()
    state = load_state()

    # This is the actual signal: the real max date gridMET Drought is
    # published through right now, queried live -- not a guess.
    latest_available = get_latest_gridmet_drought_date(api_key)

    if not args.force and state.get("last_data_date") == latest_available.isoformat():
        print(
            f"gridMET Drought still ends {latest_available.isoformat()} -- no new pentad since our "
            f"last successful run (checked {today.isoformat()}). Skipping."
        )
        return

    run_date = latest_available.isoformat()
    # The value actually sent to Climate Engine as end_date must NOT equal
    # latest_available exactly -- confirmed via a direct A/B test that an
    # exact-match end_date truncates the response back one full pentad
    # early (short/long-term blend timeseries end 5 days before what was
    # requested). Padding it past the target pentad's boundary (matching
    # what Climate Engine's own default end_date resolves to when none is
    # given at all) avoids this while still pinning one deterministic
    # value for the whole run. See DECISIONS.md "end_date truncation bug".
    # run_date (the true pentad date) is still used for local folder
    # naming and the site's displayed report period.
    api_end_date = (latest_available + timedelta(days=3)).isoformat()

    chunks = build_chunks(args.limit)
    print(f"gridMET Drought data available through {run_date}; running the pipeline for that date "
          f"(requesting end_date={api_end_date} to avoid Climate Engine's truncation quirk), "
          f"split into {len(chunks)} chunks of ~{sum(len(v) for v in chunks[0].values())} polygons each, "
          f"{CHUNK_INTERVAL_MINUTES} min apart to stay under Climate Engine's 200 req/hour cap.")

    for i, chunk in enumerate(chunks):
        chunk_total = sum(len(v) for v in chunk.values())
        print(f"--- Chunk {i + 1}/{len(chunks)}: {chunk_total} polygons ({', '.join(f'{l}={len(v)}' for l, v in chunk.items())}) ---")
        process_chunk(chunk, run_date=run_date, api_end_date=api_end_date, limit=args.limit)
        if i < len(chunks) - 1:
            print(f"Chunk {i + 1} done; waiting {CHUNK_INTERVAL_MINUTES} min before the next chunk...")
            time.sleep(CHUNK_INTERVAL_MINUTES * 60)

    all_failures: dict[str, list[str]] = {}
    for layer in LAYERS:
        failures = list_failed_sites(layer, run_date)
        if failures:
            print(f"WARNING: {len(failures)} {layer} report(s) still failed after all retry passes: {failures}")
        all_failures[layer] = failures

    build(run_date=run_date)
    save_state(last_data_date=latest_available, checked_on=today)
    FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAILURES_PATH.write_text(json.dumps(all_failures, indent=2))
    total_failed = sum(len(v) for v in all_failures.values())
    if total_failed:
        print(f"{total_failed} report(s) failed this cycle and are missing from the site -- see {FAILURES_PATH}.")
    else:
        print("All reports succeeded this cycle.")


if __name__ == "__main__":
    main()
