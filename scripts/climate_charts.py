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
# skipping Feb 29 for x-axis positioning (leap-year pentads just have one
# fewer historical sample at whichever bucket they land closest to; not
# worth a special axis case for one extra day every 4 years).
def _water_year_calendar() -> list[tuple[int, int]]:
    months_days = []
    for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        days_in_month = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[m]
        for d in range(1, days_in_month + 1):
            months_days.append((m, d))
    return months_days


WATER_YEAR_CALENDAR = _water_year_calendar()
_WD_INDEX = {md: i + 1 for i, md in enumerate(WATER_YEAR_CALENDAR)}


def water_day(month: int, day: int) -> int | None:
    """1-based day-of-water-year for a (month, day); Feb 29 maps to Feb 28's slot."""
    return _WD_INDEX.get((month, day), _WD_INDEX.get((2, 28)) if (month, day) == (2, 29) else None)


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
    (for precipitation-style running totals)."""
    sub = df[df["Variable"] == variable].sort_values("date").copy()
    if cumulative:
        sub["plot_value"] = sub.groupby("water_year")["Value"].cumsum()
    else:
        sub["plot_value"] = sub["Value"]
    sub["wd"] = sub["month_day"].map(lambda md: water_day(*md))
    sub = sub.dropna(subset=["wd"])

    hist = sub[sub["water_year"] != current_water_year]
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
    the same day-of-water-year the current (possibly partial) water year
    has reached -- comparing a partial year's total/mean against complete
    prior FULL years would be biased. Close to, but not exactly, Climate
    Engine's own gm_wb_summary/gm_temp_summary numbers (their precise
    methodology isn't published); percentile rank matched CE exactly in
    spot-checks even where the mean differed slightly -- see DECISIONS.md."""
    sub = df[df["Variable"] == variable].copy()
    sub["wd"] = sub["month_day"].map(lambda md: water_day(*md))
    sub = sub.dropna(subset=["wd"])

    current = sub[sub["water_year"] == current_water_year].sort_values("wd")
    if current.empty:
        return None
    last_wd = current["wd"].max()
    hist = sub[(sub["water_year"] != current_water_year) & (sub["wd"] <= last_wd)]

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
