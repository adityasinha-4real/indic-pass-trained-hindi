"""Charts as plain SVG, from the standard library alone.

The final report needs figures. It does not need a plotting library: nothing
else in ``requirements/base.txt`` draws anything, and adding matplotlib to a
project whose runtime dependency list is six packages -- each of which the
README justifies one by one -- would be the largest dependency in the tree,
pulled in to draw eight bar charts.

So the charts are emitted as SVG text. That is a better artefact than a PNG
anyway: vector, diffable, inspectable in a text editor, and it embeds in
Markdown, HTML and LaTeX without a raster step.

Two chart types cover everything the report shows:

:func:`grouped_bars`
    Horizontal bars, one row per category, one bar per series. Horizontal
    because the category labels are things like ``oov_spelling_variant`` and a
    vertical chart would either clip them or rotate them.

:func:`intervals`
    A forest plot: a point estimate and its confidence interval per row, with a
    reference line at zero. This is the shape the milestone's central result
    has, and a bar chart of it would hide the interval, which is the part that
    matters.

Colours are a fixed four-entry palette chosen to stay distinguishable in
greyscale -- a printed dissertation is the likeliest destination -- and to keep
the same estimator the same colour in every figure. No theme switching: these
are documents, not web pages.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = ["PALETTE", "Series", "grouped_bars", "intervals"]

#: One colour per estimator, fixed across every figure so a reader can carry
#: the association between them. Ordered light-to-dark so the series stay
#: separable when the page is printed in greyscale.
PALETTE: Mapping[str, str] = {
    "indicpass": "#1f4e79",  # M2  -- dark blue
    "pcfg": "#c55a11",  # M3  -- orange
    "baseline": "#7f7f7f",  # zxcvbn -- grey
    "attack": "#2e7d32",  # observed quantities -- green
    "m4": "#8e6c8a",  # milestone 4
    "m5": "#1f4e79",  # milestone 5
}

_FONT = "font-family=\"Segoe UI, Helvetica, Arial, sans-serif\""


@dataclass(frozen=True)
class Series:
    """One bar per category, and what to call it in the legend."""

    label: str
    colour: str
    values: Sequence[float | None]


def _escape(text: str) -> str:
    return html.escape(str(text), quote=True)


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round tick positions spanning ``[low, high]``.

    Chosen from the 1/2/2.5/5 series so the axis reads in numbers a person
    would have picked, rather than in whatever the data's range divides into.
    """
    if high <= low:
        return [low, high if high > low else low + 1.0]
    raw = (high - low) / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= step * magnitude:
            chosen = step * magnitude
            break
    else:  # pragma: no cover - the 10.0 branch always matches
        chosen = 10 * magnitude
    # The axis must CONTAIN the data, not merely come close to it: the caller
    # rescales to [ticks[0], ticks[-1]], so a top tick below the maximum would
    # place the largest bar past the right edge of the canvas. Hence the loop
    # runs until it has passed `high` and then emits one more, rather than
    # stopping at whatever the last whole step happened to reach.
    value = math.floor(low / chosen) * chosen
    out: list[float] = []
    while value < high - 1e-9:
        out.append(round(value, 10))
        value += chosen
    out.append(round(value, 10))
    return out


def _fmt(value: float) -> str:
    if value == int(value) and abs(value) < 1000:
        return str(int(value))
    return f"{value:g}"


def grouped_bars(
    *,
    title: str,
    categories: Sequence[str],
    series: Sequence[Series],
    subtitle: str = "",
    value_format: str = "{:.3f}",
    axis_label: str = "",
    width: int = 900,
    row_height: int = 22,
    label_width: int = 230,
    zero_based: bool = True,
) -> str:
    """A horizontal grouped bar chart.

    A ``None`` value is drawn as an explicit "n/a" rather than as a zero-length
    bar: an undefined statistic and a statistic that happens to be zero are
    different findings, and a chart that renders them alike would be the first
    place that distinction was lost.
    """
    if not categories:
        raise ValueError("A chart needs at least one category.")
    for entry in series:
        if len(entry.values) != len(categories):
            raise ValueError(
                f"Series {entry.label!r} has {len(entry.values)} values for "
                f"{len(categories)} categories."
            )

    present = [
        value for entry in series for value in entry.values if value is not None
    ]
    high = max([*present, 0.0])
    low = min([*present, 0.0]) if not zero_based else min(0.0, min([*present, 0.0]))
    ticks = _ticks(low, high)
    low, high = ticks[0], ticks[-1]
    span = high - low or 1.0

    group_height = row_height * len(series) + 10
    plot_left = label_width
    # The value is written to the right of its bar, so the right margin has to
    # fit the widest one. Deriving it from the formatted text rather than
    # guessing a constant is what keeps a long label from running off the canvas
    # when the numbers change -- which a fixed margin did, silently, until the
    # bounds check caught it.
    widest = max((len(value_format.format(value)) for value in present), default=5)
    plot_width = width - plot_left - (24 + widest * 7)
    top = 62 if subtitle else 46
    height = top + group_height * len(categories) + 46

    def x_of(value: float) -> float:
        return plot_left + (value - low) / span * plot_width

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape(title)}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="16" y="26" {_FONT} font-size="15" font-weight="600" '
        f'fill="#111111">{_escape(title)}</text>',
    ]
    if subtitle:
        out.append(
            f'<text x="16" y="45" {_FONT} font-size="11.5" fill="#555555">'
            f"{_escape(subtitle)}</text>"
        )

    bottom = top + group_height * len(categories)
    for tick in ticks:
        x = x_of(tick)
        out.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" '
            f'stroke="{"#999999" if tick == 0 else "#e6e6e6"}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{bottom + 16}" {_FONT} '
            f'font-size="10.5" fill="#666666" text-anchor="middle">{_fmt(tick)}</text>'
        )

    for row, category in enumerate(categories):
        base = top + row * group_height
        out.append(
            f'<text x="{plot_left - 10}" y="{base + group_height / 2 + 4:.1f}" {_FONT} '
            f'font-size="11.5" fill="#222222" text-anchor="end">{_escape(category)}</text>'
        )
        for index, entry in enumerate(series):
            value = entry.values[row]
            y = base + 5 + index * row_height
            if value is None:
                out.append(
                    f'<text x="{x_of(low) + 4:.1f}" y="{y + row_height - 7:.1f}" {_FONT} '
                    f'font-size="10.5" fill="#999999" font-style="italic">n/a</text>'
                )
                continue
            start, end = sorted((x_of(0.0) if low <= 0 <= high else x_of(low), x_of(value)))
            out.append(
                f'<rect x="{start:.1f}" y="{y:.1f}" width="{max(1.0, end - start):.1f}" '
                f'height="{row_height - 6}" fill="{entry.colour}" rx="1.5"/>'
            )
            out.append(
                f'<text x="{end + 5:.1f}" y="{y + row_height - 8:.1f}" {_FONT} '
                f'font-size="10.5" fill="#333333">{value_format.format(value)}</text>'
            )

    legend_y = height - 12
    x = plot_left
    for entry in series:
        out.append(
            f'<rect x="{x}" y="{legend_y - 9}" width="11" height="11" '
            f'fill="{entry.colour}" rx="1.5"/>'
        )
        out.append(
            f'<text x="{x + 16}" y="{legend_y}" {_FONT} font-size="11" fill="#333333">'
            f"{_escape(entry.label)}</text>"
        )
        x += 22 + len(entry.label) * 6.6
    if axis_label:
        out.append(
            f'<text x="{width - 12}" y="{legend_y}" {_FONT} font-size="10.5" '
            f'fill="#666666" text-anchor="end">{_escape(axis_label)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def intervals(
    *,
    title: str,
    rows: Sequence[tuple[str, float | None, float | None, float | None]],
    subtitle: str = "",
    axis_label: str = "",
    colour: str = PALETTE["pcfg"],
    reference: float = 0.0,
    width: int = 900,
    row_height: int = 30,
    label_width: int = 250,
) -> str:
    """A forest plot: ``(label, point, low, high)`` per row, with a zero line.

    Rows whose interval straddles the reference line are drawn in grey, so the
    figure says which differences exclude zero without the reader measuring.
    That is a presentational aid and not a significance test; the report's text
    says so wherever this figure appears.
    """
    if not rows:
        raise ValueError("A forest plot needs at least one row.")
    present = [
        value
        for _, point, low, high in rows
        for value in (point, low, high)
        if value is not None
    ]
    ticks = _ticks(min([*present, reference]), max([*present, reference]))
    axis_low, axis_high = ticks[0], ticks[-1]
    span = axis_high - axis_low or 1.0

    plot_left = label_width
    plot_width = width - plot_left - 110
    top = 62 if subtitle else 46
    height = top + row_height * len(rows) + 44

    def x_of(value: float) -> float:
        return plot_left + (value - axis_low) / span * plot_width

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_escape(title)}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="16" y="26" {_FONT} font-size="15" font-weight="600" '
        f'fill="#111111">{_escape(title)}</text>',
    ]
    if subtitle:
        out.append(
            f'<text x="16" y="45" {_FONT} font-size="11.5" fill="#555555">'
            f"{_escape(subtitle)}</text>"
        )

    for tick in ticks:
        x = x_of(tick)
        out.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + row_height * len(rows)}" '
            f'stroke="#ededed" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{top + row_height * len(rows) + 16}" {_FONT} '
            f'font-size="10.5" fill="#666666" text-anchor="middle">{_fmt(tick)}</text>'
        )
    zero = x_of(reference)
    out.append(
        f'<line x1="{zero:.1f}" y1="{top}" x2="{zero:.1f}" '
        f'y2="{top + row_height * len(rows)}" stroke="#333333" stroke-width="1.2" '
        f'stroke-dasharray="4 3"/>'
    )

    for index, (label, point, low, high) in enumerate(rows):
        y = top + index * row_height + row_height / 2
        out.append(
            f'<text x="{plot_left - 10}" y="{y + 4:.1f}" {_FONT} font-size="11.5" '
            f'fill="#222222" text-anchor="end">{_escape(label)}</text>'
        )
        if point is None:
            out.append(
                f'<text x="{plot_left + 6}" y="{y + 4:.1f}" {_FONT} font-size="10.5" '
                f'fill="#999999" font-style="italic">not estimated</text>'
            )
            continue
        excludes = low is not None and high is not None and (low > reference or high < reference)
        shade = colour if excludes else "#9e9e9e"
        if low is not None and high is not None:
            out.append(
                f'<line x1="{x_of(low):.1f}" y1="{y:.1f}" x2="{x_of(high):.1f}" '
                f'y2="{y:.1f}" stroke="{shade}" stroke-width="2"/>'
            )
            for edge in (low, high):
                out.append(
                    f'<line x1="{x_of(edge):.1f}" y1="{y - 5:.1f}" x2="{x_of(edge):.1f}" '
                    f'y2="{y + 5:.1f}" stroke="{shade}" stroke-width="2"/>'
                )
        out.append(f'<circle cx="{x_of(point):.1f}" cy="{y:.1f}" r="4" fill="{shade}"/>')
        text = f"{point:+.3f}" + (
            f" [{low:+.3f}, {high:+.3f}]" if low is not None and high is not None else ""
        )
        out.append(
            f'<text x="{width - 12}" y="{y + 4:.1f}" {_FONT} font-size="10" '
            f'fill="#444444" text-anchor="end">{_escape(text)}</text>'
        )

    out.append(
        f'<text x="{plot_left}" y="{height - 10}" {_FONT} font-size="10.5" fill="#666666">'
        f"{_escape(axis_label)}</text>"
    )
    out.append(
        f'<text x="{width - 12}" y="{height - 10}" {_FONT} font-size="10" fill="#888888" '
        f'text-anchor="end">coloured = interval excludes {_fmt(reference)}</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"
