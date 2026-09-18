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
# frame_height (the plotted-data rectangle only, excluding title/toolbar/
# axes/legend chrome) rather than a fixed total `height` -- this is what
# actually makes charts LOOK the same size, since a fixed total `height`
# stays equal even when one chart's legend eats into its plot area and
# another has no legend at all (found via user feedback + direct DOM
# measurement, see DECISIONS.md "Chart sizing").
FIG_FRAME_HEIGHT = 320
BG = "#fcfcfb"
GRID = "#e1e0d9"
INK = "#0b0b0b"
MUTED = "#898781"

# Bokeh renders client-side from literal color values -- it can't read
# CSS custom properties -- so the diverging drought-class ramp is
# duplicated here from site/assets/style.css's light-mode --dc-c0..c10
# values. Keep these in sync if that palette ever changes.
DROUGHT_HEX = {
    "c0": "#a50f15", "c1": "#de2d26", "c2": "#fb6a4a", "c3": "#fc9272", "c4": "#fcbba1",
    "c5": "#cdccc4",
    "c6": "#9ec5f4", "c7": "#6da7ec", "c8": "#3987e5", "c9": "#256abf", "c10": "#104281",
}
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
        title=title, frame_height=FIG_FRAME_HEIGHT, width=FIG_WIDTH,
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
    fig.varea(x="wd", y1="p5", y2="p95", source=hist_src, fill_color=ACCENT_BAND, fill_alpha=0.12,
              legend_label="Historical 5th–95th percentile")
    fig.varea(x="wd", y1="p25", y2="p75", source=hist_src, fill_color=ACCENT_BAND, fill_alpha=0.22,
              legend_label="Historical 25th–75th percentile")
    mean_line = fig.line(x="wd", y="mean", source=hist_src, line_color=ACCENT, line_width=1.5,
                          line_dash="dashed", legend_label="Historical mean")

    cur_src = ColumnDataSource(dict(wd=band["current_wd"], value=band["current_value"]))
    line = fig.line(x="wd", y="value", source=cur_src, line_color=CURRENT_COLOR, line_width=2,
                     legend_label=f"{band['current_water_year']} (this water year)")
    fig.scatter(x="wd", y="value", source=cur_src, size=5, color=CURRENT_COLOR, alpha=0)  # hover targets

    fig.add_tools(HoverTool(renderers=[mean_line], mode="vline", tooltips=[
        ("Historical mean", "@mean{0.00}"),
        ("25th–75th percentile", "@p25{0.00} – @p75{0.00}"),
        ("5th–95th percentile", "@p5{0.00} – @p95{0.00}"),
    ]))
    fig.add_tools(HoverTool(renderers=[line], tooltips=[("This water year", "@value{0.00}")], mode="vline"))
    _place_legend_below(fig)
    return fig


def _place_legend_below(fig: figure) -> None:
    """Moves the auto-built legend out of the plot frame into a compact
    horizontal strip underneath it, instead of overlapping the data --
    keeps the actual charted area the same visible size across every
    chart regardless of how many legend entries it has (see DECISIONS.md
    "Chart sizing")."""
    legend = fig.legend[0]
    legend.orientation = "horizontal"
    legend.location = "center"
    legend.background_fill_alpha = 0
    legend.border_line_color = None
    legend.label_text_font_size = "10px"
    legend.spacing = 14
    legend.margin = 4
    fig.add_layout(legend, "below")


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

    _place_legend_below(fig)
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


def class_evolution_figure(df, classes, title: str) -> figure:
    """Continuous drought-class-% stacked area over the full ~390-day
    window a stb_/ltb_/dm_timeseries.csv covers -- not a Climate Engine
    graphic at all (their own report only ever shows 3 snapshots of this
    same data, now/3mo/1yr, as a static table); this is the one thing
    genuinely new that the underlying data supports and Climate Engine
    doesn't show. Stack order runs driest (bottom) to wettest (top),
    matching the classes list order."""
    if df is None or df.empty:
        return None

    from bokeh.models import DatetimeTickFormatter

    keys = [c.key for c in classes]
    source = ColumnDataSource(df.reset_index())

    fig = figure(
        title=title, frame_height=FIG_FRAME_HEIGHT, width=FIG_WIDTH, sizing_mode="stretch_width",
        x_axis_type="datetime", background_fill_color=BG, border_fill_color=BG,
        tools="pan,box_zoom,wheel_zoom,reset,save", toolbar_location="above",
        y_range=(0, 100),
    )
    fig.grid.grid_line_color = GRID
    fig.outline_line_color = "#c3c2b7"
    fig.yaxis.axis_label = "% of area"
    fig.yaxis.axis_label_text_color = MUTED
    fig.axis.major_label_text_color = MUTED
    fig.axis.axis_line_color = "#c3c2b7"
    fig.title.text_color = INK
    fig.title.text_font_size = "13px"
    fig.xaxis.formatter = DatetimeTickFormatter(days="%b %d", months="%b %Y")

    colors = [DROUGHT_HEX[k] for k in keys]
    renderers = fig.varea_stack(stackers=keys, x="date", color=colors, source=source, legend_label=[c.label for c in classes])

    tooltips = [("Date", "@date{%F}")] + [(c.label, f"@{c.key}{{0.1f}}%") for c in classes]
    fig.add_tools(HoverTool(renderers=renderers, tooltips=tooltips, formatters={"@date": "datetime"}, mode="vline"))

    fig.legend.visible = False  # 11 classes as a legend box is noise here; the hover carries identity (see the shared legend under the summary bars above instead)
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
