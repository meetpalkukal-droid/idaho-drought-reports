"""
Entry point for the scheduled GitHub Actions job. Runs only when Climate
Engine's gridMET Drought dataset has actually published a new pentad since
our last successful run -- checked directly against Climate Engine's own
/metadata/dataset_dates endpoint (dataset=GRIDMET_DROUGHT), not guessed
from a fixed day count. See DECISIONS.md "Data-driven cadence gate" for
why: a blind "5 days since last run" counter can't tell a delayed
publication from an on-time one, and can't self-correct if gridMET's
actual cadence ever shifts.

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

from fetch_reports import run_layer, run_geometry_fallback, get_latest_gridmet_drought_date, list_failed_sites, LAYERS
from build_site import build

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "reports" / "state.json"
FAILURES_PATH = ROOT / "data" / "reports" / "last_run_failures.json"
RETRY_BACKOFF_S = 45


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
    # value for the whole ~20-30 min async run. See DECISIONS.md "end_date
    # truncation bug". run_date (the true pentad date) is still used for
    # local folder naming and the site's displayed report period.
    api_end_date = (latest_available + timedelta(days=3)).isoformat()
    print(f"gridMET Drought data available through {run_date}; running the pipeline for that date "
          f"(requesting end_date={api_end_date} to avoid Climate Engine's truncation quirk).")

    all_failures: dict[str, list[str]] = {}
    for layer in LAYERS:
        run_layer(layer, limit=args.limit, end_date=run_date, api_end_date=api_end_date)
        # Two automatic retry passes, with a short backoff between them:
        # transient failures (concurrency-limit errors, network blips) are
        # expected at some rate every run -- see DECISIONS.md "Second
        # retry pass". A single immediate retry wasn't enough in practice
        # (confirmed: a site that failed twice in one run succeeded on a
        # plain manual retry minutes later), so this backs off briefly to
        # give whatever caused the transient failure room to clear before
        # trying again.
        time.sleep(RETRY_BACKOFF_S)
        run_layer(layer, limit=args.limit, end_date=run_date, api_end_date=api_end_date, retry_failed=True)
        # Anything still failing with one of the two confirmed-fixable
        # error messages (a Climate Engine server-side bug on complex
        # geometries, or gridMET's 4km grid missing tiny polygons) gets
        # resubmitted via the coordinates endpoint instead -- see
        # DECISIONS.md and the fetch_reports.py module docstring.
        run_geometry_fallback(layer, end_date=run_date, api_end_date=api_end_date)
        # A last retry pass catches anything the fallback didn't touch
        # (a different, unrecognized error) that might still just be
        # transient.
        time.sleep(RETRY_BACKOFF_S)
        run_layer(layer, limit=args.limit, end_date=run_date, api_end_date=api_end_date, retry_failed=True)

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
