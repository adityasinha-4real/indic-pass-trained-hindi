"""Scoring the estimators against the reference attack's observed ranks.

Two quantities meet here and must never be confused, so they are named apart
everywhere in this module and in every report it produces:

``log10_reference_rank``
    Where :mod:`indicpass.password.reference_attack` actually emitted the
    password. An observation about one specific attacker. Exact.

``log10_guesses``
    What an estimator predicted. A model output.

The error is ``predicted - observed``. **Positive means the estimator called
the password stronger than the attack found it** -- the dangerous direction for
a meter, because it is the one that tells someone a crackable password is fine.
Negative means the estimator was pessimistic, which is the safe direction and
is still an error.

Why every metric, rather than one score
---------------------------------------
The metrics disagree with each other, and which one matters depends on what the
meter is for. A rank correlation says whether an estimator *orders* passwords
the way the attack does -- the property a strength meter needs, because its job
is to tell a weak password from a strong one. An absolute error says whether it
gets the *number* right -- the property a risk calculation needs. An estimator
can be excellent at one and useless at the other, and collapsing them into a
single figure of merit would hide exactly that. So all of them are reported,
per estimator and per category, and the report names the winner under each.

Everything is computed in ``log10`` space, for the reason
:mod:`indicpass.password.experiment` gives: a mean over guess counts spanning
sixteen orders of magnitude is the largest sample and nothing else.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ESTIMATOR_COLUMNS",
    "ESTIMATOR_LABELS",
    "METRIC_DIRECTION",
    "PRIMARY_ESTIMATORS",
    "Calibration",
    "CalibrationBin",
    "MetricSet",
    "ValidationRow",
    "best_by_metric",
    "calibration",
    "combined_predictions",
    "coverage_row",
    "metrics",
    "pearson",
    "spearman",
    "stratum_rows",
]

#: The three estimators, then the combinations. A combination is what an
#: attacker holding several models actually pays -- guessing cost is a minimum
#: over the options -- so it is a real candidate for "what should the meter
#: report", not a presentational convenience.
PRIMARY_ESTIMATORS: tuple[str, ...] = ("indicpass", "pcfg", "baseline")
ESTIMATOR_COLUMNS: tuple[str, ...] = (
    "indicpass",
    "pcfg",
    "baseline",
    "min_indicpass_baseline",
    "min_pcfg_baseline",
    "min_all",
)

#: Human-readable names for a report's column headers. Kept beside the columns
#: so a table cannot label ``min_all`` as something it is not.
ESTIMATOR_LABELS: Mapping[str, str] = {
    "indicpass": "IndicPass (M2)",
    "pcfg": "PCFG (M3)",
    "baseline": "zxcvbn 4.5.0",
    "min_indicpass_baseline": "min(M2, zxcvbn)",
    "min_pcfg_baseline": "min(PCFG, zxcvbn)",
    "min_all": "min(M2, PCFG, zxcvbn)",
}


@dataclass(frozen=True)
class ValidationRow:
    """One target: what the attack observed, and what each estimator predicted.

    Holds the sample's identity and shape, never its text -- the same rule
    :class:`indicpass.password.experiment.SampleResult` enforces, for the same
    reason. ``predictions`` carries raw floats; rounding happens once, at
    serialisation, so no statistic is ever computed on a display value.
    """

    sample_id: str
    category: str
    construction: str
    length: int
    covered: bool
    reference_rank: int | None
    log10_reference_rank: float | None
    #: Column name -> predicted ``log10`` guesses. Every entry in
    #: :data:`ESTIMATOR_COLUMNS` is present on a row built by
    #: :func:`build_rows`.
    predictions: Mapping[str, float] = field(default_factory=dict)
    #: The rule that emitted the password, e.g. ``word+year/capitalized``.
    rule: str | None = None
    #: True when the target's stem is absent from the attacker's lexicon. A
    #: derived stratum, reported separately: it is the "unseen spelling" family.
    unseen_stem: bool = False
    #: True when the sample was generated with a non-lowercase word. The "case
    #: variation" family, likewise a stratum rather than a category of its own.
    case_variant: bool = False

    def error(self, estimator: str) -> float | None:
        """``predicted - observed``, or ``None`` if this target is uncovered."""
        if not self.covered or self.log10_reference_rank is None:
            return None
        predicted = self.predictions.get(estimator)
        if predicted is None:
            return None
        return predicted - self.log10_reference_rank

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "category": self.category,
            "construction": self.construction,
            "length": self.length,
            "covered": self.covered,
            "reference_rank": self.reference_rank,
            "log10_reference_rank": (
                round(self.log10_reference_rank, 6)
                if self.log10_reference_rank is not None
                else None
            ),
            "rule": self.rule,
            "unseen_stem": self.unseen_stem,
            "case_variant": self.case_variant,
            "predictions": {
                name: round(value, 6) for name, value in sorted(self.predictions.items())
            },
        }


def combined_predictions(
    *, indicpass: float, pcfg: float | None, baseline: float | None
) -> dict[str, float]:
    """Every column of :data:`ESTIMATOR_COLUMNS` an available estimator supports.

    A missing estimator drops its columns rather than being substituted for:
    a ``min_pcfg_baseline`` computed without a PCFG would silently be zxcvbn,
    and a table saying otherwise would be wrong.
    """
    values: dict[str, float] = {"indicpass": indicpass}
    if pcfg is not None:
        values["pcfg"] = pcfg
    if baseline is not None:
        values["baseline"] = baseline
        values["min_indicpass_baseline"] = min(indicpass, baseline)
        if pcfg is not None:
            values["min_pcfg_baseline"] = min(pcfg, baseline)
            values["min_all"] = min(indicpass, pcfg, baseline)
    return values


# -- correlations -----------------------------------------------------------


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Product-moment correlation, or ``None`` when it is undefined.

    ``None`` rather than 0.0 for a constant series: a correlation of zero is a
    finding ("the estimator does not track the attack") and an undefined one is
    an absence of data. Reporting the second as the first would be a claim.
    """
    if len(xs) != len(ys):
        raise ValueError(f"Series differ in length: {len(xs)} and {len(ys)}.")
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    numerator = sum(a * b for a, b in zip(dx, dy, strict=True))
    denominator = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    if denominator == 0.0:
        return None
    return numerator / denominator


def _average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks with ties averaged.

    Ties are not an edge case here: the brute-force floor gives whole blocks of
    passwords the same estimate, and the attack gives none of them the same
    rank. Ranking those with ``sort`` order rather than an average would invent
    an ordering the estimator never expressed.
    """
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in order[position : end + 1]:
            ranks[index] = shared
        position = end + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation: Pearson on tie-averaged ranks."""
    if len(xs) != len(ys):
        raise ValueError(f"Series differ in length: {len(xs)} and {len(ys)}.")
    if len(xs) < 2:
        return None
    return pearson(_average_ranks(xs), _average_ranks(ys))


# -- metrics ----------------------------------------------------------------

#: Bands an estimate counts as "close" within. Half an order of magnitude is
#: about the width of one strength band boundary; a full order is the coarsest
#: agreement anyone would call agreement.
CLOSE_BANDS: tuple[float, ...] = (0.5, 1.0)


@dataclass(frozen=True)
class MetricSet:
    """One estimator's agreement with the reference attack, on one population.

    ``samples`` counts COVERED targets only. Uncovered ones carry no observed
    rank and so contribute to :func:`coverage_row` and to nothing else; the
    selection this creates is stated wherever a MetricSet is printed.
    """

    estimator: str
    category: str
    samples: int
    spearman: float | None
    pearson: float | None
    mean_signed_error: float
    median_signed_error: float
    mean_absolute_error: float
    median_absolute_error: float
    rmse: float
    within_half: float
    within_one: float
    #: Share of covered targets the estimator placed above / below the observed
    #: rank by more than :data:`AGREEMENT_BAND`.
    over_rate: float
    under_rate: float

    @property
    def direction(self) -> str:
        """Which way this estimator is systematically wrong, in one word."""
        if abs(self.mean_signed_error) <= AGREEMENT_BAND:
            return "calibrated"
        return "over-estimates" if self.mean_signed_error > 0 else "under-estimates"

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimator": self.estimator,
            "label": ESTIMATOR_LABELS.get(self.estimator, self.estimator),
            "category": self.category,
            "samples": self.samples,
            "spearman": self.spearman,
            "pearson": self.pearson,
            "mean_signed_error": self.mean_signed_error,
            "median_signed_error": self.median_signed_error,
            "mean_absolute_error": self.mean_absolute_error,
            "median_absolute_error": self.median_absolute_error,
            "rmse": self.rmse,
            "within_0.5_log10": self.within_half,
            "within_1.0_log10": self.within_one,
            "over_estimate_rate": self.over_rate,
            "under_estimate_rate": self.under_rate,
            "direction": self.direction,
            "error_note": (
                "error = predicted log10 guesses - observed log10 reference rank. "
                "Positive means the estimator called the password STRONGER than this "
                "attack found it."
            ),
        }


#: An error smaller than this is not a direction. Half an order of magnitude is
#: well inside the modelling error of every estimator here.
AGREEMENT_BAND = 0.5


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


def metrics(
    rows: Sequence[ValidationRow], estimator: str, *, category: str | None = None
) -> MetricSet:
    """Score *estimator* over the covered rows, optionally within one category."""
    selected = [
        row
        for row in rows
        if row.covered
        and (category is None or row.category == category)
        and estimator in row.predictions
        and row.log10_reference_rank is not None
    ]
    if not selected:
        return MetricSet(
            estimator=estimator,
            category=category or "all",
            samples=0,
            spearman=None,
            pearson=None,
            mean_signed_error=0.0,
            median_signed_error=0.0,
            mean_absolute_error=0.0,
            median_absolute_error=0.0,
            rmse=0.0,
            within_half=0.0,
            within_one=0.0,
            over_rate=0.0,
            under_rate=0.0,
        )

    observed = [row.log10_reference_rank for row in selected]
    predicted = [row.predictions[estimator] for row in selected]
    errors = [p - o for p, o in zip(predicted, observed, strict=True)]  # type: ignore[operator]
    absolute = [abs(value) for value in errors]
    count = len(errors)

    rho = spearman(predicted, observed)  # type: ignore[arg-type]
    r = pearson(predicted, observed)  # type: ignore[arg-type]

    return MetricSet(
        estimator=estimator,
        category=category or "all",
        samples=count,
        spearman=_round(rho) if rho is not None else None,
        pearson=_round(r) if r is not None else None,
        mean_signed_error=_round(statistics.fmean(errors)),
        median_signed_error=_round(statistics.median(errors)),
        mean_absolute_error=_round(statistics.fmean(absolute)),
        median_absolute_error=_round(statistics.median(absolute)),
        rmse=_round(math.sqrt(statistics.fmean([value * value for value in errors]))),
        within_half=_round(sum(1 for v in absolute if v <= CLOSE_BANDS[0]) / count),
        within_one=_round(sum(1 for v in absolute if v <= CLOSE_BANDS[1]) / count),
        over_rate=_round(sum(1 for v in errors if v > AGREEMENT_BAND) / count),
        under_rate=_round(sum(1 for v in errors if v < -AGREEMENT_BAND) / count),
    )


#: For each metric, whether the better estimator is the one with the larger
#: value. Written down rather than inferred, so a report cannot announce a
#: winner by maximising an error.
METRIC_DIRECTION: Mapping[str, bool] = {
    "spearman": True,
    "pearson": True,
    "mean_absolute_error": False,
    "median_absolute_error": False,
    "rmse": False,
    "within_0.5_log10": True,
    "within_1.0_log10": True,
    "abs_mean_signed_error": False,
}


def best_by_metric(sets: Sequence[MetricSet]) -> dict[str, Any]:
    """Which estimator wins under each metric, with the value it won on.

    Deliberately produces a table rather than a ranking: the estimators do not
    agree about who is best, and the disagreement is a result. ``None`` where
    no estimator has a defined value for that metric.
    """
    winners: dict[str, Any] = {}
    for metric, higher_is_better in METRIC_DIRECTION.items():
        scored: list[tuple[str, float]] = []
        for entry in sets:
            if entry.samples == 0:
                continue
            if metric == "abs_mean_signed_error":
                scored.append((entry.estimator, abs(entry.mean_signed_error)))
                continue
            value = entry.to_dict().get(metric)
            if value is None:
                continue
            scored.append((entry.estimator, float(value)))
        if not scored:
            winners[metric] = None
            continue
        winner = (max if higher_is_better else min)(scored, key=lambda item: item[1])
        winners[metric] = {
            "estimator": winner[0],
            "label": ESTIMATOR_LABELS.get(winner[0], winner[0]),
            "value": _round(winner[1]),
            "higher_is_better": higher_is_better,
        }
    return winners


# -- calibration ------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationBin:
    """One band of predictions, and how far off the attack said they were."""

    index: int
    samples: int
    predicted_low: float
    predicted_high: float
    mean_predicted: float
    mean_observed: float
    mean_bias: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "bin": self.index,
            "samples": self.samples,
            "predicted_low": self.predicted_low,
            "predicted_high": self.predicted_high,
            "mean_predicted": self.mean_predicted,
            "mean_observed": self.mean_observed,
            "mean_bias": self.mean_bias,
        }


@dataclass(frozen=True)
class Calibration:
    """Ordinary least squares of observed rank on predicted guesses.

    A perfectly calibrated estimator has slope 1 and intercept 0. Slope below
    one means the estimator's scale is *compressed* -- it spreads passwords
    over fewer orders of magnitude than the attack does -- and slope above one
    that it exaggerates. The intercept is a constant offset, which for a
    strength meter is much the less serious of the two: a meter whose ordering
    is right and whose zero is wrong can be re-based, one whose slope is wrong
    cannot.
    """

    estimator: str
    category: str
    samples: int
    slope: float | None
    intercept: float | None
    r_squared: float | None
    bins: tuple[CalibrationBin, ...] = ()
    #: ``(predicted, observed)`` pairs, thinned for plotting. Publishable: a
    #: pair of numbers says nothing about which password produced it.
    points: tuple[tuple[float, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimator": self.estimator,
            "label": ESTIMATOR_LABELS.get(self.estimator, self.estimator),
            "category": self.category,
            "samples": self.samples,
            "slope": self.slope,
            "intercept": self.intercept,
            "r_squared": self.r_squared,
            "bins": [entry.to_dict() for entry in self.bins],
            "points": [[a, b] for a, b in self.points],
            "note": (
                "Ordinary least squares of log10 observed reference rank on log10 "
                "predicted guesses. Slope 1 / intercept 0 is perfect calibration "
                "against THIS attack, not against real attackers."
            ),
        }


def calibration(
    rows: Sequence[ValidationRow],
    estimator: str,
    *,
    category: str | None = None,
    bins: int = 10,
    points: int = 400,
) -> Calibration:
    """Fit *estimator* against the observed ranks, and bin the residuals.

    Bins are equal-count (deciles by default) rather than equal-width: an
    equal-width bin over a range dominated by one cluster puts almost every
    sample in one bucket and reports nine empty ones.
    """
    selected = [
        row
        for row in rows
        if row.covered
        and (category is None or row.category == category)
        and estimator in row.predictions
        and row.log10_reference_rank is not None
    ]
    label = category or "all"
    if len(selected) < 2:
        return Calibration(estimator, label, len(selected), None, None, None)

    selected.sort(key=lambda row: row.predictions[estimator])
    predicted = [row.predictions[estimator] for row in selected]
    observed = [float(row.log10_reference_rank) for row in selected]  # type: ignore[arg-type]

    mean_x, mean_y = statistics.fmean(predicted), statistics.fmean(observed)
    variance = sum((x - mean_x) ** 2 for x in predicted)
    if variance == 0.0:
        # Every prediction identical: a slope is undefined, but the bias is
        # not, and the bins below still say what the estimator got wrong.
        slope = intercept = r_squared = None
    else:
        covariance = sum(
            (x - mean_x) * (y - mean_y) for x, y in zip(predicted, observed, strict=True)
        )
        slope = covariance / variance
        intercept = mean_y - slope * mean_x
        correlation = pearson(predicted, observed)
        r_squared = correlation**2 if correlation is not None else None

    count = len(selected)
    width = max(1, count // max(1, bins))
    binned: list[CalibrationBin] = []
    for index in range(0, count, width):
        chunk = slice(index, min(index + width, count))
        chunk_predicted = predicted[chunk]
        chunk_observed = observed[chunk]
        if not chunk_predicted:
            continue
        binned.append(
            CalibrationBin(
                index=len(binned) + 1,
                samples=len(chunk_predicted),
                predicted_low=_round(min(chunk_predicted)),
                predicted_high=_round(max(chunk_predicted)),
                mean_predicted=_round(statistics.fmean(chunk_predicted)),
                mean_observed=_round(statistics.fmean(chunk_observed)),
                mean_bias=_round(
                    statistics.fmean(chunk_predicted) - statistics.fmean(chunk_observed)
                ),
            )
        )

    # points=0 asks for the fit and the bins without the scatter -- what the
    # per-category tables want, where seven copies of a 400-point cloud would
    # be most of the report and none of the information.
    if points <= 0:
        thinned: tuple[tuple[float, float], ...] = ()
    else:
        step = max(1, count // points)
        thinned = tuple(
            (_round(predicted[index]), _round(observed[index]))
            for index in range(0, count, step)
        )

    return Calibration(
        estimator=estimator,
        category=label,
        samples=count,
        slope=_round(slope) if slope is not None else None,
        intercept=_round(intercept) if intercept is not None else None,
        r_squared=_round(r_squared) if r_squared is not None else None,
        bins=tuple(binned),
        points=thinned,
    )


# -- coverage ---------------------------------------------------------------


def coverage_row(rows: Sequence[ValidationRow], category: str | None = None) -> dict[str, Any]:
    """Coverage for one population, with the two derived strata broken out."""
    selected = [row for row in rows if category is None or row.category == category]
    if not selected:
        return {"category": category or "all", "targets": 0, "covered": 0, "coverage": 0.0}
    covered = [row for row in selected if row.covered]
    unseen = [row for row in selected if row.unseen_stem]
    case_variants = [row for row in selected if row.case_variant]
    return {
        "category": category or "all",
        "targets": len(selected),
        "covered": len(covered),
        "coverage": _round(len(covered) / len(selected)),
        "median_log10_rank": (
            _round(statistics.median([float(r.log10_reference_rank) for r in covered]))  # type: ignore[arg-type]
            if covered
            else None
        ),
        "mean_log10_rank": (
            _round(statistics.fmean([float(r.log10_reference_rank) for r in covered]))  # type: ignore[arg-type]
            if covered
            else None
        ),
        "unseen_stem": len(unseen),
        "unseen_stem_covered": sum(1 for row in unseen if row.covered),
        "case_variant": len(case_variants),
        "case_variant_covered": sum(1 for row in case_variants if row.covered),
    }


def stratum_rows(rows: Iterable[ValidationRow], stratum: str) -> list[ValidationRow]:
    """The derived families the benchmark categories cut across.

    ``case_variation`` and ``unseen_spelling`` are required families that are
    not benchmark categories: the generator sprinkles capitalisation through
    every Indic category, and whether a word is in the attacker's lexicon is a
    property of the lexicon, not of the generator. Both are therefore strata
    over the existing corpus rather than new samples -- which is also what
    keeps the 1,400-sample benchmark untouched.
    """
    rows = list(rows)
    if stratum == "case_variation":
        return [row for row in rows if row.case_variant]
    if stratum == "unseen_spelling":
        return [row for row in rows if row.unseen_stem]
    if stratum == "in_lexicon":
        return [row for row in rows if not row.unseen_stem]
    raise ValueError(
        f"Unknown stratum {stratum!r}. "
        "Known: case_variation, unseen_spelling, in_lexicon."
    )
