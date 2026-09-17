"""
Bokeh figure builders for the interactive charts on each report page (per
user direction: rebuild Climate Engine's static chart graphics as our own
interactive ones, using Bokeh for all of them). Figures are embedded via
bokeh.embed.components() in build_site.py -- one shared BokehJS <script>
per page (from CDN), one components() call per page covering all of that
page's figures.

Styling is intentionally a plain light card (explicit white-ish
background) regardless of the page's light/dark mode, matching how the
Climate Engine map PNGs already read as light cards against a dark page --
full dark-mode-aware Bokeh theming would mean re-rendering per theme,
which isn't done here.
"""

from __future__ import annotations

from bokeh.embed import components
from bokeh.models import ColumnDataSource, HoverTool, Span
from bokeh.plotting import figure
from bokeh.resources import CDN

from climate_charts import WATER_YEAR_CALENDAR

FIG_WIDTH = 640
FIG_HEIGHT = 300
BG = "#fcfcfb"
GRID = "#e1e0d9"
INK = "#0b0b0b"
MUTED = "#898781"
ACCENT = "#2a78d6"
ACCENT_BAND = "#2a78d6"
CURRENT_COLOR = "#e34948"


def _month_ticks() -> dict[int, str]:
    """water-day position -> 'Oct' etc. for the 1st of each month, in
    water-year order (Oct 1 = day 1)."""
    ticks = {}
    for i, (m, d) in enumerate(WATER_YEAR_CALENDAR, start=1):
        if d == 1:
            ticks[i] = {10: "Oct", 11: "Nov", 12: "Dec", 1: "Jan", 2: "Feb", 3: "Mar",
                        4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep"}[m]
    return ticks


def _base_figure(title: str, y_label: str, **kwargs) -> figure:
    fig = figure(
        title=title, height=FIG_HEIGHT, width=FIG_WIDTH,
        sizing_mode="stretch_width",  # fixed width overflowed its grid cell
        # (2-column layout, ~430px cells) instead of fitting it -- found via
        # screenshot QA, see DECISIONS.md.
        background_fill_color=BG, border_fill_color=BG,
        tools="pan,box_zoom,wheel_zoom,reset,save", toolbar_location="above",
        **kwargs,
    )
    fig.grid.grid_line_color = GRID
    fig.outline_line_color = "#c3c2b7"
    fig.yaxis.axis_label = y_label
    fig.yaxis.axis_label_text_color = MUTED
    fig.axis.major_label_text_color = MUTED
    fig.axis.axis_line_color = "#c3c2b7"
    fig.title.text_color = INK
    fig.title.text_font_size = "13px"
    return fig


def normal_band_figure(band: dict, *, title: str, y_label: str) -> figure:
    """Historical P5-P95 / P25-P75 band + mean, with the current water
    year's trace on top -- the pattern Climate Engine's gm_eto_rate /
    gm_precip_cum / gm_tmean_rate charts use, rebuilt here as an
    interactive Bokeh figure with a real hover tooltip."""
    fig = _base_figure(title, y_label)
    ticks = _month_ticks()
    fig.xaxis.ticker = list(ticks.keys())
    fig.xaxis.major_label_overrides = {k: v for k, v in ticks.items()}
    fig.x_range.start = 1
    fig.x_range.end = len(WATER_YEAR_CALENDAR)

    hist_src = ColumnDataSource(dict(
        wd=band["wd"], mean=band["mean"], p5=band["p5"], p25=band["p25"],
        p75=band["p75"], p95=band["p95"],
    ))
    fig.varea(x="wd", y1="p5", y2="p95", source=hist_src, fill_color=ACCENT_BAND, fill_alpha=0.12)
    fig.varea(x="wd", y1="p25", y2="p75", source=hist_src, fill_color=ACCENT_BAND, fill_alpha=0.22)
    fig.line(x="wd", y="mean", source=hist_src, line_color=ACCENT, line_width=1.5,
              line_dash="dashed", legend_label="Historical mean")

    cur_src = ColumnDataSource(dict(wd=band["current_wd"], value=band["current_value"]))
    line = fig.line(x="wd", y="value", source=cur_src, line_color=CURRENT_COLOR, line_width=2,
                     legend_label=f"{band['current_water_year']} (this water year)")
    fig.scatter(x="wd", y="value", source=cur_src, size=5, color=CURRENT_COLOR, alpha=0)  # hover targets

    fig.add_tools(HoverTool(renderers=[line], tooltips=[("Value", "@value{0.00}")], mode="vline"))
    fig.legend.location = "top_left"
    fig.legend.background_fill_alpha = 0.7
    fig.legend.label_text_font_size = "10px"
    fig.legend.border_line_color = None
    return fig


def water_year_trend_figure(wy_df) -> figure:
    """Annual Precip & ETo totals since the data begins, each with a
    linear trend line -- rebuild of Climate Engine's
    gm_wy_precip_eto_trends chart."""
    from climate_charts import mann_kendall_trend

    fig = _base_figure("Water-Year Precipitation & ETo Trends", "Total (in)")
    years = wy_df.index.to_numpy()
    fig.x_range.start = int(years.min()) - 1
    fig.x_range.end = int(years.max()) + 1

    specs = [("Precip", "#2a78d6", "Precipitation"), ("ETo", "#e34948", "Evaporative demand")]
    for col, color, label in specs:
        vals = wy_df[col].to_numpy()
        src = ColumnDataSource(dict(year=years, value=vals))
        line = fig.line(x="year", y="value", source=src, line_color=color, line_width=2, legend_label=label)
        fig.scatter(x="year", y="value", source=src, size=6, color=color)
        fig.add_tools(HoverTool(renderers=[line], tooltips=[(label, "@value{0.00} in"), ("Water year", "@year")]))

        trend = mann_kendall_trend(years, vals)
        slope_per_year = trend["slope_per_decade"] / 10
        trend_y = trend["mean"] + slope_per_year * (years - years.mean())
        fig.line(years, trend_y, line_color=color, line_width=1, line_dash="dotted", alpha=0.7)

    fig.legend.location = "center_left"
    fig.legend.background_fill_alpha = 0.7
    fig.legend.label_text_font_size = "10px"
    fig.legend.border_line_color = None
    return fig


def long_term_index_figure(series: list[tuple[int, float]]) -> figure:
    """1986-present long-term drought blend index, one point per water
    year -- Bokeh rebuild of the hand-drawn SVG version (and of Climate
    Engine's own ltb_eoy_timeseries chart)."""
    if not series:
        return None
    years = [y for y, _ in series]
    values = [v for _, v in series]

    fig = _base_figure("Long-Term Drought Blend Index (1986–Present)", "Index value")
    fig.x_range.start = min(years) - 1
    fig.x_range.end = max(years) + 1

    zero = Span(location=0, dimension="width", line_color=MUTED, line_width=1)
    fig.add_layout(zero)

    for lo, hi, color, alpha in [(-3, -1.5, "#de2d26", 0.15), (-1.5, -0.5, "#fc9272", 0.15),
                                   (-0.5, 0.5, "#cdccc4", 0.15), (0.5, 1.5, "#6da7ec", 0.15),
                                   (1.5, 3, "#256abf", 0.15)]:
        fig.quad(left=min(years) - 1, right=max(years) + 1, bottom=lo, top=hi, fill_color=color,
                  fill_alpha=alpha, line_width=0)

    src = ColumnDataSource(dict(year=years, value=values))
    line = fig.line(x="year", y="value", source=src, line_color=ACCENT, line_width=2)
    fig.scatter(x="year", y="value", source=src, size=6, color=ACCENT)
    fig.add_tools(HoverTool(renderers=[line], tooltips=[("Water year", "@year"), ("Index", "@value{+0.00}")]))
    fig.y_range.start, fig.y_range.end = -3, 3
    return fig


def embed_figures(figs: dict[str, figure]) -> tuple[str, dict[str, str]]:
    """Wraps bokeh.embed.components: one <script> covering every figure on
    a page, plus a {key: div_html} to place each figure where it belongs."""
    figs = {k: v for k, v in figs.items() if v is not None}
    if not figs:
        return "", {}
    script, divs = components(figs)
    return script, divs


BOKEH_CDN_TAGS = "\n".join(CDN.render_js().splitlines() + CDN.render_css().splitlines())
