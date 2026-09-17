"""
Entry point for the scheduled GitHub Actions job. Runs at most once every
5 days (matching the gridMET Drought pentad cadence the underlying data is
published on) by tracking the last successful run date in
data/reports/state.json, which is committed back to the repo so the check
survives across separate Actions runs.

    python scripts/run_pipeline.py          # runs only if >= 5 days since last run
    python scripts/run_pipeline.py --force  # runs regardless (for manual testing)
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from fetch_reports import run_layer, run_geometry_fallback, LAYERS
from build_site import build

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "reports" / "state.json"
CADENCE_DAYS = 5


def load_last_run() -> date | None:
    if not STATE_PATH.exists():
        return None
    data = json.loads(STATE_PATH.read_text())
    return date.fromisoformat(data["last_run"])


def save_last_run(d: date) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"last_run": d.isoformat()}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="cap features per layer (smoke test)")
    args = parser.parse_args()

    today = date.today()
    last_run = load_last_run()

    if not args.force and last_run is not None and (today - last_run) < timedelta(days=CADENCE_DAYS):
        print(f"Last run was {last_run.isoformat()}; next run due {(last_run + timedelta(days=CADENCE_DAYS)).isoformat()}. Skipping.")
        return

    for layer in LAYERS:
        run_layer(layer, limit=args.limit, end_date=today.isoformat())
        # One automatic retry pass: transient failures (concurrency-limit
        # errors, network blips) are expected at some rate every run -- see
        # DECISIONS.md. This mops most of them up without manual intervention.
        run_layer(layer, limit=args.limit, end_date=today.isoformat(), retry_failed=True)
        # Anything still failing after the retry pass with one of the two
        # confirmed-fixable error messages (a Climate Engine server-side bug
        # on complex geometries, or gridMET's 4km grid missing tiny
        # polygons) gets resubmitted via the coordinates endpoint instead --
        # see DECISIONS.md and the fetch_reports.py module docstring.
        run_geometry_fallback(layer, end_date=today.isoformat())

    build(run_date=today.isoformat())
    save_last_run(today)


if __name__ == "__main__":
    main()
