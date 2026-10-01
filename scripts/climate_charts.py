"""
Data prep for the interactive Bokeh charts in bokeh_charts.py: turns
gm_timeseries.csv / gm_wy_timeseries.csv / ltb_eoy_timeseries.csv into the
shapes those chart functions need (historical normal bands by day-of-year,
water-year totals, linear trends). Kept separate from bokeh_charts.py so
the statistics can be tested/reasoned about without touching plotting code.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def class_evolution_df(csv_path: Path, class_keys: list[str]) -> pd.DataFrame:
    """Wide DataFrame (index=date, one column per class key, values =
    percent of that row's area) from a stb_/ltb_/dm_timeseries.csv --
    the full time-evolving series those CSVs contain, which Climate
    Engine's own report only ever shows 3 snapshots of (now/3mo/1yr)."""
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["Date"])
    totals = df[class_keys].sum(axis=1)
    for k in class_keys:
        df[k] = np.where(totals > 0, df[k] / totals * 100, 0.0)
    return df.set_index("date")[class_keys].sort_index()


def _water_year(date: pd.Timestamp) -> int:
    # USGS convention: water year N runs Oct 1 (N-1) -> Sep 30 (N), so an
    # Oct-Dec date belongs to the FOLLOWING calendar year's water year, not
    # the current one. Confirmed against gm_wy_timeseries.csv (whose last
    # complete row is WaterYear=2025, i.e. Oct 2024-Sep 2025) and Climate
    # Engine's own pentad charts, which label the in-progress Oct
    # 2025-Sep 2026 trace "2026".
    return date.year + 1 if date.month >= 10 else date.year


def load_gm_daily(csv_path: Path) -> pd.DataFrame:
    """gm_timeseries.csv (Variable, Value, Year, Date[YYYYMMDD], DOY), long
    format across Tmin/Tmax/Precip/ETo -- adds date/water_year/month_day."""
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    df["water_year"] = df["date"].apply(_water_year)
    df["month_day"] = list(zip(df["date"].dt.month, df["date"].dt.day))
    return df


# Calendar (month, day) tuples in water-year order (Oct 1 -> Sep 30),
# used only to place approximate month-boundary tick labels on the
# pentad-rank x-axis (see bokeh_charts._month_ticks) -- NOT used to
# align data across years any more (see normal_band_data's docstring
# for why calendar-date alignment doesn't work for this dataset).
def _water_year_calendar() -> list[tuple[int, int]]:
    months_days = []
    for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        days_in_month = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[m]
        for d in range(1, days_in_month + 1):
            months_days.append((m, d))
    return months_days


WATER_YEAR_CALENDAR = _water_year_calendar()


def _pentad_rank(sub: pd.DataFrame) -> pd.Series:
    """1-based sequential index of each row within its own water year,
    in chronological order ('wd' downstream, though it's no longer a
    literal day-of-water-year -- see normal_band_data)."""
    return sub.sort_values("date").groupby("water_year").cumcount() + 1


def _complete_water_years(sub: pd.DataFrame) -> set[int]:
    """Water years with a full ~73/74-pentad record, excluding any
    partial year -- confirmed against the real data that gm_timeseries.csv's
    first on-record water year (1980) only starts Jan 1, 1980, so it has
    just 55 pentad rows instead of 73/74. A rank-based partial year
    desyncs from every other year for its entire length (by the time a
    complete year reaches rank 54 in late June, 1980's rank 54 is
    already late September, 55 rows into its own short record) and
    would otherwise quietly contaminate the historical band at nearly
    every rank, not just the ones near its missing months. 70 is well
    below the legitimate minimum (73) and well above the two observed
    partial-year counts (55 for 1980, and whatever the in-progress
    current year has reached), so it cleanly separates the two cases
    without hardcoding a specific year.
    """
    counts = sub.groupby("water_year").size()
    return set(counts[counts >= 70].index)


def _max_common_rank(sub: pd.DataFrame, complete_years: set[int]) -> int:
    """The shortest complete water year's pentad count (73, in
    practice) -- about 1 in 4 complete years get a 74th pentad (see
    _water_year_calendar's leap-year comment), so without this cap the
    band's very last point would average only that smaller subset of
    years instead of all of them, reading as a one-step drop at the
    end of the chart purely from the sample changing, not from any
    actual seasonal dip. Confirmed against real data: every such drop
    found across 65 districts was exactly at the last step (rank 73 to
    74), nowhere else.
    """
    counts = sub[sub["water_year"].isin(complete_years)].groupby("water_year").size()
    return int(counts.min()) if len(counts) else 0


def normal_band_data(
    df: pd.DataFrame,
    variable: str,
    *,
    cumulative: bool,
    current_water_year: int,
) -> dict:
    """Historical (all years except current) percentile band by day-of-
    water-year, plus the current water year's own trace, for one gm_*
    variable ("ETo", "Precip", "Tmax", "Tmin", or "Tmean" computed by the
    caller). cumulative=True accumulates within each water year first
    (for precipitation-style running totals).

    Climate Engine's underlying gm_timeseries.csv is a 5-day pentad
    composite, not truly daily, and its pentad schedule is anchored to
    absolute day-of-year (DOY % 5 == 1) -- a standard day-of-year count,
    which is well known to shift every calendar date from March onward
    by one day in a leap year versus a non-leap year (confirmed against
    the real data: leap years report Mar 1/6/11/.., non-leap years
    report Mar 2/7/12/..). Bucketing by literal calendar (month, day) --
    the previous approach -- mixes these two offset patterns together
    at nearly every post-February slot, so the historical mean/percentile
    band is really averaging two different sets of actual calendar
    windows depending on each year's leap status, which shows up as a
    persistent sawtooth from March through September (user-reported).
    Bucketing instead by each row's sequential pentad rank within its
    own water year (1st reading, 2nd reading, ...) compares the same
    relative position in the season's reporting sequence across years
    regardless of leap status, which is immune to this drift.
    """
    sub = df[df["Variable"] == variable].sort_values("date").copy()
    sub["wd"] = _pentad_rank(sub)

    if cumulative:
        sub["plot_value"] = sub.groupby("water_year")["Value"].cumsum()
    else:
        sub["plot_value"] = sub["Value"]

    complete_years = _complete_water_years(sub)
    hist = sub[(sub["water_year"] != current_water_year) & (sub["water_year"].isin(complete_years))]
    hist = hist[hist["wd"] <= _max_common_rank(sub, complete_years)]
    band = (
        hist.groupby("wd")["plot_value"]
        .agg(mean="mean", p5=lambda s: s.quantile(0.05), p25=lambda s: s.quantile(0.25),
             p75=lambda s: s.quantile(0.75), p95=lambda s: s.quantile(0.95))
        .dropna()
        .sort_index()
    )

    current = sub[sub["water_year"] == current_water_year].sort_values("wd")

    return {
        "wd": band.index.to_numpy(),
        "mean": band["mean"].to_numpy(),
        "p5": band["p5"].to_numpy(),
        "p25": band["p25"].to_numpy(),
        "p75": band["p75"].to_numpy(),
        "p95": band["p95"].to_numpy(),
        "current_wd": current["wd"].to_numpy(),
        "current_value": current["plot_value"].to_numpy(),
        "current_water_year": current_water_year,
    }


def water_year_mean_series(df: pd.DataFrame, variable: str, *, exclude_water_year: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-water-year MEAN of a daily gm_timeseries.csv variable (e.g.
    Tmean, which -- unlike Precip/ETo -- isn't in Climate Engine's own
    gm_wy_timeseries.csv, since it's a value we synthesize via add_tmean,
    not one they publish at the water-year level). Excludes the current,
    still-incomplete water year, matching how gm_wy_timeseries.csv only
    ever contains complete water years (see _water_year's docstring)."""
    sub = df[(df["Variable"] == variable) & (df["water_year"] != exclude_water_year)]
    grouped = sub.groupby("water_year")["Value"].mean().sort_index()
    return grouped.index.to_numpy(), grouped.to_numpy()


def water_year_pivot(csv_path: Path) -> pd.DataFrame:
    """gm_wy_timeseries.csv (Variable, Value, WaterYear) -> wide DataFrame
    indexed by WaterYear with one column per variable."""
    df = pd.read_csv(csv_path)
    return df.pivot(index="WaterYear", columns="Variable", values="Value").sort_index()


def add_tmean(df: pd.DataFrame) -> pd.DataFrame:
    """Appends a synthetic 'Tmean' variable ((Tmax+Tmin)/2 per date) so it
    can be treated like any other gm_timeseries.csv variable."""
    pivot = df.pivot_table(index=["date", "water_year", "month_day"], columns="Variable", values="Value")
    tmean = ((pivot["Tmax"] + pivot["Tmin"]) / 2).reset_index()
    tmean["Variable"] = "Tmean"
    tmean = tmean.rename(columns={0: "Value"})
    tmean["Value"] = ((pivot["Tmax"] + pivot["Tmin"]) / 2).to_numpy()
    return pd.concat([df, tmean[["Variable", "Value", "date", "water_year", "month_day"]]], ignore_index=True)


def current_vs_average(current_value: float, historical_values: np.ndarray) -> dict:
    """Matches Climate Engine's own gm_wb_summary/gm_temp_summary table
    methodology: current (possibly partial) water year's value against the
    mean of complete prior water years, with a percentile rank."""
    historical_values = np.asarray(historical_values, dtype=float)
    historical_values = historical_values[~np.isnan(historical_values)]
    avg = float(np.mean(historical_values)) if len(historical_values) else float("nan")
    pct_rank = float(stats.percentileofscore(historical_values, current_value)) if len(historical_values) else float("nan")
    return {
        "current": current_value,
        "average": avg,
        "diff": current_value - avg,
        "pct_of_avg": (current_value / avg * 100) if avg else float("nan"),
        "percentile": pct_rank,
    }


def year_to_date_summary(df: pd.DataFrame, variable: str, current_water_year: int, *, cumulative: bool) -> dict | None:
    """current_vs_average, but the historical comparison is truncated to
    the same point in the season's pentad sequence the current
    (possibly partial) water year has reached -- comparing a partial
    year's total/mean against complete prior FULL years would be
    biased. Truncates by pentad rank, not calendar date, for the same
    leap-year reason explained in normal_band_data's docstring. Close
    to, but not exactly, Climate Engine's own gm_wb_summary/
    gm_temp_summary numbers (their precise methodology isn't
    published); percentile rank matched CE exactly in spot-checks even
    where the mean differed slightly -- see DECISIONS.md."""
    sub = df[df["Variable"] == variable].copy()
    sub["wd"] = _pentad_rank(sub)

    current = sub[sub["water_year"] == current_water_year].sort_values("wd")
    if current.empty:
        return None
    complete_years = _complete_water_years(sub)
    last_wd = min(current["wd"].max(), _max_common_rank(sub, complete_years) or current["wd"].max())
    hist = sub[(sub["water_year"] != current_water_year) & (sub["water_year"].isin(complete_years)) & (sub["wd"] <= last_wd)]

    if cumulative:
        current_value = float(current["Value"].sum())
        historical = hist.groupby("water_year")["Value"].sum().to_numpy()
    else:
        current_value = float(current["Value"].mean())
        historical = hist.groupby("water_year")["Value"].mean().to_numpy()

    return current_vs_average(current_value, historical)


def mann_kendall_trend(years: np.ndarray, values: np.ndarray) -> dict:
    """Mann-Kendall trend test + Sen's slope estimator: the standard
    nonparametric trend test in hydrology/climate science (robust to
    non-normal, outlier-heavy annual series, unlike OLS regression).
    Matched Climate Engine's own gm_long_term_trends numbers far more
    closely than plain linear regression did in spot-checks (same
    conclusion, closer but not identical p-values/slopes -- their exact
    tie-handling isn't published) -- see DECISIONS.md."""
    mask = ~np.isnan(values)
    x, y = years[mask].astype(float), values[mask].astype(float)
    n = len(y)

    diffs = y[:, None] - y[None, :]
    idx = np.triu_indices(n, k=1)
    signs = np.sign(diffs[idx])
    s = signs.sum()

    _, counts = np.unique(y, return_counts=True)
    tie_term = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    pvalue = 2 * (1 - stats.norm.cdf(abs(z)))

    year_diffs = x[:, None] - x[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes = diffs[idx] / year_diffs[idx]
    slopes = slopes[np.isfinite(slopes)]
    sen_slope = float(np.median(slopes)) if len(slopes) else float("nan")

    return {
        "slope_per_decade": sen_slope * 10,
        "pvalue": float(pvalue),
        "mean": float(np.mean(y)),
    }
