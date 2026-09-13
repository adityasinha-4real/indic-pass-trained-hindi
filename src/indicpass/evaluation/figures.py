"""SVG figures for the evaluation report, from the standard library alone.

Same rationale as :mod:`indicpass.figures`: no plotting library is a runtime
dependency of this project, and eight more figures is not a reason to start.
:func:`indicpass.figures.grouped_bars` and :func:`indicpass.figures.intervals`
already cover "one bar per category" and "a forest plot of intervals", and are
reused here unchanged for the baseline/category comparisons and the bootstrap
confidence-interval figures. What this module adds is what a ROC curve, a PR
curve, a reliability diagram, a guess-number histogram and a confusion matrix
need that those two do not: a generic multi-series line chart and a small
labelled grid.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from indicpass.figures import PALETTE

__all__ = ["LineSeries", "confusion_grid", "histogram", "line_chart"]

_FONT = 'font-family="Segoe UI, Helvetica, Arial, sans-serif"'


def _escape(text: str) -> str:
    return html.escape(str(text), quote=True)


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Same rounding rule as :func:`indicpass.figures._ticks`, kept local so
    this module has no private cross-module dependency."""
    if high <= low:
        return [low, high if high > low else low + 1.0]
    raw = (high - low) / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= step * magnitude:
            chosen = step * magnitude
            break
    else:  # pragma: no cover
        chosen = 10 * magnitude
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


@dataclass(frozen=True)
class LineSeries:
    label: str
    colour: str
    points: Sequence[tuple[float, float]]
    dashed: bool = False


def line_chart(
    *,
    title: str,
    series: Sequence[LineSeries],
    subtitle: str = "",
    x_label: str = "",
    y_label: str = "",
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    diagonal: bool = False,
    width: int = 640,
    height: int = 460,
) -> str:
    """A multi-series line/scatter chart with axes, ticks and a legend.

    *diagonal* draws the ``y = x`` reference line across the plotted range --
    chance-level ROC, or perfect calibration -- in a dashed neutral grey, so a
    reader never has to eyeball where it would fall.
    """
    if not series:
        raise ValueError("A line chart needs at least one series.")
    all_x = [x for entry in series for x, _ in entry.points]
    all_y = [y for entry in series for _, y in entry.points]
    if not all_x:
        raise ValueError("Every series is empty.")

    x_low, x_high = x_range or (min(0.0, min(all_x)), max(1.0, max(all_x)))
    y_low, y_high = y_range or (min(0.0, min(all_y)), max(1.0, max(all_y)))
    x_ticks = _ticks(x_low, x_high)
    y_ticks = _ticks(y_low, y_high)
    x_low, x_high = x_ticks[0], x_ticks[-1]
    y_low, y_high = y_ticks[0], y_ticks[-1]
    x_span = x_high - x_low or 1.0
    y_span = y_high - y_low or 1.0

    plot_left, plot_right = 56, width - 20
    top = 62 if subtitle else 46
    bottom = height - 56
    plot_width = plot_right - plot_left
    plot_height = bottom - top

    def x_of(value: float) -> float:
        return plot_left + (value - x_low) / x_span * plot_width

    def y_of(value: float) -> float:
        return bottom - (value - y_low) / y_span * plot_height

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

    for tick in x_ticks:
        x = x_of(tick)
        out.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" '
            f'stroke="#eeeeee" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{bottom + 16}" {_FONT} font-size="10" fill="#666666" '
            f'text-anchor="middle">{_fmt(tick)}</text>'
        )
    for tick in y_ticks:
        y = y_of(tick)
        out.append(
            f'<line x1="{plot_left}" y1="{y:.1f}" x2="{plot_right}" y2="{y:.1f}" '
            f'stroke="#eeeeee" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{plot_left - 8}" y="{y + 3:.1f}" {_FONT} font-size="10" '
            f'fill="#666666" text-anchor="end">{_fmt(tick)}</text>'
        )
    out.append(
        f'<rect x="{plot_left}" y="{top}" width="{plot_width}" height="{plot_height}" '
        f'fill="none" stroke="#999999" stroke-width="1"/>'
    )

    if diagonal:
        out.append(
            f'<line x1="{x_of(max(x_low, y_low)):.1f}" y1="{y_of(max(x_low, y_low)):.1f}" '
            f'x2="{x_of(min(x_high, y_high)):.1f}" y2="{y_of(min(x_high, y_high)):.1f}" '
            f'stroke="#999999" stroke-width="1.2" stroke-dasharray="4 3"/>'
        )

    for entry in series:
        if not entry.points:
            continue
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{x_of(x):.1f},{y_of(y):.1f}"
            for i, (x, y) in enumerate(entry.points)
        )
        dash = ' stroke-dasharray="5 3"' if entry.dashed else ""
        out.append(
            f'<path d="{path}" fill="none" stroke="{entry.colour}" stroke-width="2"{dash}/>'
        )

    if x_label:
        out.append(
            f'<text x="{(plot_left + plot_right) / 2:.1f}" y="{height - 8}" {_FONT} '
            f'font-size="10.5" fill="#666666" text-anchor="middle">{_escape(x_label)}</text>'
        )
    if y_label:
        out.append(
            f'<text x="14" y="{(top + bottom) / 2:.1f}" {_FONT} font-size="10.5" '
            f'fill="#666666" text-anchor="middle" '
            f'transform="rotate(-90 14 {(top + bottom) / 2:.1f})">{_escape(y_label)}</text>'
        )

    legend_y = top - 8
    legend_x = plot_left
    for entry in series:
        out.append(
            f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 16}" y2="{legend_y}" '
            f'stroke="{entry.colour}" stroke-width="2"/>'
        )
        out.append(
            f'<text x="{legend_x + 20}" y="{legend_y + 3}" {_FONT} font-size="10" '
            f'fill="#333333">{_escape(entry.label)}</text>'
        )
        legend_x += 26 + len(entry.label) * 6.2
    out.append("</svg>")
    return "\n".join(out) + "\n"


def histogram(
    *,
    title: str,
    series: Sequence[tuple[str, str, Sequence[float]]],
    bins: int = 20,
    subtitle: str = "",
    x_label: str = "",
    width: int = 760,
    height: int = 360,
) -> str:
    """Overlaid histograms, one translucent colour per ``(label, colour, values)``.

    Bin edges are shared across every series -- spanning the union of all
    values -- so the bars are comparable rather than each series choosing its
    own scale.
    """
    all_values = [v for _, _, values in series for v in values if math.isfinite(v)]
    if not all_values:
        raise ValueError("Every series is empty or non-finite.")
    low, high = min(all_values), max(all_values)
    if high == low:
        high = low + 1.0

    counts: list[tuple[str, str, list[int]]] = []
    max_count = 1
    for label, colour, values in series:
        bucket = [0] * bins
        for v in values:
            if not math.isfinite(v):
                continue
            index = min(bins - 1, max(0, int((v - low) / (high - low) * bins)))
            bucket[index] += 1
        counts.append((label, colour, bucket))
        max_count = max(max_count, max(bucket, default=0))

    plot_left, plot_right = 56, width - 20
    top = 62 if subtitle else 46
    bottom = height - 50
    plot_width = plot_right - plot_left
    plot_height = bottom - top
    bin_width = plot_width / bins

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
    out.append(
        f'<rect x="{plot_left}" y="{top}" width="{plot_width}" height="{plot_height}" '
        f'fill="none" stroke="#999999" stroke-width="1"/>'
    )
    for tick in _ticks(low, high, count=6):
        if not (low <= tick <= high):
            continue
        x = plot_left + (tick - low) / (high - low) * plot_width
        out.append(
            f'<text x="{x:.1f}" y="{bottom + 16}" {_FONT} font-size="9.5" fill="#666666" '
            f'text-anchor="middle">{_fmt(tick)}</text>'
        )

    for _, colour, bucket in counts:
        for index, count in enumerate(bucket):
            if count == 0:
                continue
            bar_height = count / max_count * plot_height
            x = plot_left + index * bin_width
            y = bottom - bar_height
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(1.0, bin_width - 1):.1f}" '
                f'height="{bar_height:.1f}" fill="{colour}" fill-opacity="0.55"/>'
            )

    legend_x = plot_left
    legend_y = top - 8
    for label, colour, _ in counts:
        out.append(
            f'<rect x="{legend_x}" y="{legend_y - 8}" width="10" height="10" '
            f'fill="{colour}" fill-opacity="0.7"/>'
        )
        out.append(
            f'<text x="{legend_x + 14}" y="{legend_y + 1}" {_FONT} font-size="10" '
            f'fill="#333333">{_escape(label)}</text>'
        )
        legend_x += 20 + len(label) * 6.2
    if x_label:
        out.append(
            f'<text x="{(plot_left + plot_right) / 2:.1f}" y="{height - 8}" {_FONT} '
            f'font-size="10.5" fill="#666666" text-anchor="middle">{_escape(x_label)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def confusion_grid(
    *,
    title: str,
    confusion: Mapping[str, int],
    subtitle: str = "",
    positive_label: str = "crackable",
    negative_label: str = "not crackable",
    width: int = 420,
    height: int = 300,
) -> str:
    """A 2x2 confusion matrix, cell shade proportional to its share of the total.

    *confusion* takes ``tp``/``fp``/``tn``/``fn`` keys, matching
    :meth:`indicpass.evaluation.metrics.BinaryConfusion.to_dict`.
    """
    tp, fp, tn, fn = confusion["tp"], confusion["fp"], confusion["tn"], confusion["fn"]
    total = max(1, tp + fp + tn + fn)
    top = 62 if subtitle else 46
    grid_left, grid_top = 130, top + 20
    cell_w, cell_h = 130, 90

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
    out.append(
        f'<text x="{grid_left + cell_w}" y="{grid_top - 6}" {_FONT} font-size="10.5" '
        f'fill="#555555" text-anchor="middle">actual {positive_label}</text>'
    )
    out.append(
        f'<text x="{grid_left + 2 * cell_w}" y="{grid_top - 6}" {_FONT} font-size="10.5" '
        f'fill="#555555" text-anchor="middle">actual {negative_label}</text>'
    )
    labels = [
        ("predicted", "positive"),
        ("predicted", "negative"),
    ]
    for row, (prefix, word) in enumerate(labels):
        out.append(
            f'<text x="{grid_left - 8}" y="{grid_top + row * cell_h + cell_h / 2 + 4:.1f}" '
            f'{_FONT} font-size="10.5" fill="#555555" text-anchor="end">{prefix} {word}</text>'
        )

    positions = [
        (0, 0, tp, PALETTE["attack"]),
        (0, 1, fn, "#c0392b"),
        (1, 0, fp, "#c0392b"),
        (1, 1, tn, PALETTE["attack"]),
    ]
    for row, col, count, colour in positions:
        opacity = 0.15 + 0.65 * (count / total)
        x = grid_left + col * cell_w
        y = grid_top + row * cell_h
        out.append(
            f'<rect x="{x}" y="{y}" width="{cell_w - 4}" height="{cell_h - 4}" '
            f'fill="{colour}" fill-opacity="{opacity:.3f}" stroke="#999999"/>'
        )
        out.append(
            f'<text x="{x + (cell_w - 4) / 2:.1f}" y="{y + (cell_h - 4) / 2 + 6:.1f}" '
            f'{_FONT} font-size="17" font-weight="600" fill="#111111" '
            f'text-anchor="middle">{count:,}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"
