"""Smoke tests for indicpass.evaluation.figures: valid, in-canvas SVG.

Mirrors tests/test_figures.py's geometry check -- an element drawn past the
declared canvas is a bug that a diff would not catch.
"""

from __future__ import annotations

import re

from indicpass.evaluation.figures import LineSeries, confusion_grid, histogram, line_chart


def _coordinates(svg: str) -> tuple[list[float], list[float], int, int]:
    width = int(re.search(r'width="(\d+)"', svg).group(1))
    height = int(re.search(r'height="(\d+)"', svg).group(1))
    xs = [float(v) for v in re.findall(r'[ "](?:x|x1|x2|cx)="(-?[\d.]+)"', svg)]
    ys = [float(v) for v in re.findall(r'[ "](?:y|y1|y2|cy)="(-?[\d.]+)"', svg)]
    return xs, ys, width, height


def _assert_inside_canvas(svg: str) -> None:
    xs, ys, width, height = _coordinates(svg)
    assert min(xs) >= -1
    assert max(xs) <= width + 1
    assert min(ys) >= -1
    assert max(ys) <= height + 1


def test_line_chart_is_valid_svg_inside_canvas():
    svg = line_chart(
        title="ROC curve",
        series=[
            LineSeries(
                label="IndicPass", colour="#1f4e79", points=[(0.0, 0.0), (0.2, 0.7), (1.0, 1.0)]
            ),
            LineSeries(
                label="zxcvbn", colour="#7f7f7f", points=[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
            ),
        ],
        x_range=(0.0, 1.0), y_range=(0.0, 1.0), diagonal=True,
    )
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    _assert_inside_canvas(svg)


def test_line_chart_requires_at_least_one_series():
    import pytest

    with pytest.raises(ValueError):
        line_chart(title="empty", series=[])


def test_histogram_is_valid_svg_inside_canvas():
    svg = histogram(
        title="Guess distribution",
        series=[
            ("IndicPass", "#1f4e79", [1.0, 2.0, 2.5, 3.0, 5.0]),
            ("zxcvbn", "#7f7f7f", [3.0, 4.0, 4.0, 6.0]),
        ],
    )
    _assert_inside_canvas(svg)


def test_confusion_grid_is_valid_svg_inside_canvas():
    svg = confusion_grid(
        title="Confusion matrix",
        confusion={"tp": 12, "fp": 3, "tn": 40, "fn": 5},
    )
    _assert_inside_canvas(svg)
    assert "12" in svg and "40" in svg
