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
from datetime import date
from pathlib import Path

from fetch_reports import run_layer, run_geometry_fallback, get_latest_gridmet_drought_date, LAYERS
from build_site import build

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "reports" / "state.json"


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
    print(f"gridMET Drought data available through {run_date}; running the pipeline for that date.")

    for layer in LAYERS:
        run_layer(layer, limit=args.limit, end_date=run_date)
        # One automatic retry pass: transient failures (concurrency-limit
        # errors, network blips) are expected at some rate every run -- see
        # DECISIONS.md. This mops most of them up without manual intervention.
        run_layer(layer, limit=args.limit, end_date=run_date, retry_failed=True)
        # Anything still failing after the retry pass with one of the two
        # confirmed-fixable error messages (a Climate Engine server-side bug
        # on complex geometries, or gridMET's 4km grid missing tiny
        # polygons) gets resubmitted via the coordinates endpoint instead --
        # see DECISIONS.md and the fetch_reports.py module docstring.
        run_geometry_fallback(layer, end_date=run_date)

    build(run_date=run_date)
    save_state(last_data_date=latest_available, checked_on=today)


if __name__ == "__main__":
    main()
