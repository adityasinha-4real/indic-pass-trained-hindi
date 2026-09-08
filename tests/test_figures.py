"""The figures: is what the report draws inside the canvas and true to the data?

A chart in a research report is a claim, and it fails in ways prose does not. A
bar can run off the edge of the page and simply not be there; an undefined
statistic can be drawn as zero and read as a measurement; an axis can end below
the largest value and clip it. None of those raise, and none are visible in a
diff -- which is why they are tested here rather than eyeballed.

The geometry tests are the important ones. They render the SVG and check that
every coordinate lands inside the declared canvas, which is the property that
was actually violated: :func:`_ticks` used to stop at the last whole step below
the maximum, so the tallest bar was placed past the right edge.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from itertools import pairwise

import pytest

from indicpass.figures import PALETTE, Series, grouped_bars, intervals
from indicpass.figures import _ticks as ticks


def coordinates(svg: str) -> tuple[list[float], list[float], int, int]:
    width = int(re.search(r'width="(\d+)"', svg).group(1))
    height = int(re.search(r'height="(\d+)"', svg).group(1))
    xs = [float(v) for v in re.findall(r'[ "](?:x|x1|x2|cx)="(-?[\d.]+)"', svg)]
    ys = [float(v) for v in re.findall(r'[ "](?:y|y1|y2|cy)="(-?[\d.]+)"', svg)]
    return xs, ys, width, height


def assert_inside_canvas(svg: str) -> None:
    xs, ys, width, height = coordinates(svg)
    assert min(xs) >= -1, f"an element starts at x={min(xs)}, off the left edge"
    assert max(xs) <= width + 1, f"an element reaches x={max(xs)}, past the {width}px canvas"
    assert min(ys) >= -1, f"an element starts at y={min(ys)}, above the canvas"
    assert max(ys) <= height + 1, f"an element reaches y={max(ys)}, below the {height}px canvas"


# -- axis ticks -------------------------------------------------------------


def test_the_axis_contains_the_data():
    """The regression. The caller rescales to the tick range, so a top tick
    below the maximum silently pushes the largest bar off the canvas."""
    for low, high in ((0.0, 3.46), (0.0, 0.919), (0.0, 14.62), (-0.09, 0.18), (0.0, 1.0)):
        marks = ticks(low, high)
        assert marks[0] <= low, (low, high, marks)
        assert marks[-1] >= high, (low, high, marks)


def test_the_axis_is_evenly_spaced():
    marks = ticks(0.0, 3.46)
    steps = {round(b - a, 9) for a, b in pairwise(marks)}
    assert len(steps) == 1, marks


def test_a_degenerate_range_still_produces_an_axis():
    assert len(ticks(2.0, 2.0)) >= 2
    assert len(ticks(0.0, 0.0)) >= 2


# -- grouped bars -----------------------------------------------------------


def test_a_grouped_bar_chart_stays_inside_its_canvas():
    svg = grouped_bars(
        title="t",
        subtitle="s",
        categories=["a", "bbbbbbbbbbbbbbbbbbbb", "c"],
        series=[
            Series("first", PALETTE["indicpass"], [3.46, 0.001, 1.0]),
            Series("second", PALETTE["pcfg"], [0.5, 3.31, 2.0]),
        ],
        value_format="{:.2f}",
    )
    assert_inside_canvas(svg)


@pytest.mark.parametrize("value", [0.0, 1.0, 14.62, 1e6])
def test_a_single_bar_of_any_magnitude_stays_inside(value: float):
    svg = grouped_bars(
        title="t",
        categories=["only"],
        series=[Series("one", PALETTE["attack"], [value])],
        value_format="{:.2f}",
    )
    assert_inside_canvas(svg)


def test_an_undefined_value_is_drawn_as_such_and_not_as_zero():
    """A statistic that is undefined and one that is zero are different
    findings, and a chart is the first place that distinction gets lost."""
    svg = grouped_bars(
        title="t",
        categories=["defined", "undefined"],
        series=[Series("one", PALETTE["pcfg"], [0.0, None])],
    )
    assert "n/a" in svg
    assert_inside_canvas(svg)


def test_a_mismatched_series_is_refused():
    with pytest.raises(ValueError, match="values for"):
        grouped_bars(
            title="t",
            categories=["a", "b"],
            series=[Series("one", PALETTE["pcfg"], [1.0])],
        )


def test_a_chart_with_no_categories_is_refused():
    with pytest.raises(ValueError, match="at least one category"):
        grouped_bars(title="t", categories=[], series=[])


def test_the_bar_length_is_proportional_to_the_value():
    svg = grouped_bars(
        title="t",
        categories=["a", "b"],
        series=[Series("one", PALETTE["attack"], [1.0, 2.0])],
    )
    widths = [float(v) for v in re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)"', svg)]
    # The background rect carries no x/y so the regex skips it: these are the
    # two bars, then the legend swatch.
    assert widths[1] == pytest.approx(widths[0] * 2, rel=0.02)


# -- intervals --------------------------------------------------------------


def test_a_forest_plot_stays_inside_its_canvas():
    svg = intervals(
        title="t",
        subtitle="s",
        rows=[
            ("all", 0.087, 0.072, 0.103),
            ("oov_indic", -0.060, -0.078, -0.044),
            ("tiny", 0.0, None, None),
            ("absent", None, None, None),
        ],
    )
    assert_inside_canvas(svg)


def test_a_row_with_no_estimate_says_so():
    svg = intervals(title="t", rows=[("absent", None, None, None)])
    assert "not estimated" in svg


def test_an_interval_excluding_zero_is_drawn_differently_from_one_that_does_not():
    excludes = intervals(title="t", rows=[("a", -0.06, -0.078, -0.044)])
    includes = intervals(title="t", rows=[("a", -0.06, -0.20, 0.08)])
    assert PALETTE["pcfg"] in excludes
    assert PALETTE["pcfg"] not in includes


def test_a_forest_plot_with_no_rows_is_refused():
    with pytest.raises(ValueError, match="at least one row"):
        intervals(title="t", rows=[])


# -- output ------------------------------------------------------------------


def test_every_chart_is_well_formed_xml():
    charts = [
        grouped_bars(
            title="t & <angle>",
            categories=["a < b"],
            series=[Series("x & y", PALETTE["pcfg"], [1.0])],
        ),
        intervals(title="t & <angle>", rows=[("a < b", 0.1, 0.0, 0.2)]),
    ]
    for svg in charts:
        root = ElementTree.fromstring(svg)
        assert root.tag.endswith("svg")
        assert root.get("viewBox")


def test_labels_are_escaped_rather_than_injected():
    svg = grouped_bars(
        title="</svg><script>alert(1)</script>",
        categories=["x"],
        series=[Series("s", PALETTE["pcfg"], [1.0])],
    )
    assert "<script>" not in svg
    ElementTree.fromstring(svg)


def test_the_committed_figures_are_inside_their_canvases():
    """The figures the final report links to, as they are on disk."""
    from pathlib import Path

    directory = Path(__file__).resolve().parents[1] / "results" / "figures"
    figures = sorted(directory.glob("*.svg")) if directory.is_dir() else []
    if not figures:  # pragma: no cover - figures not generated in this checkout
        pytest.skip("Figures not generated; run scripts/final_report.py")
    for path in figures:
        svg = path.read_text(encoding="utf-8")
        ElementTree.fromstring(svg)
        try:
            assert_inside_canvas(svg)
        except AssertionError as error:  # pragma: no cover - only on a real failure
            raise AssertionError(f"{path.name}: {error}") from error
