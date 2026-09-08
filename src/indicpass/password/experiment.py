"""Running the comparison, and the statistics it is allowed to report.

Everything here operates on ``log10(guesses)``, never on guesses. Guess counts
span thirty orders of magnitude; a mean over them is dominated entirely by the
largest sample and says nothing about the others. A mean over their logarithms
is a geometric mean of the counts, which is the only average that means
anything on this scale -- and medians are reported next to it because even that
is skewed.

What the numbers do and do not license
--------------------------------------
The headline quantity is the per-category difference

    mean log10(IndicPass guesses) - mean log10(baseline guesses)

Negative means IndicPass estimates *fewer* guesses: it found weakness the
baseline missed. That is the effect the experiment is looking for, on the Indic
categories specifically.

It is not, on its own, evidence that IndicPass is more accurate. Lower is only
better if the password really is easier to guess, and establishing that needs a
reference attack -- an actual cracking run against an actual leak -- which this
project does not have. So :func:`compare` reports the direction and the
magnitude and stops there. A lower estimate on the *random* controls, where
there is no lexical structure to find, is evidence of the opposite: a
difference in brute-force assumptions rather than in lexical knowledge, which
is why the controls are in the corpus at all.
"""

from __future__ import annotations

import random
import statistics
import string
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from indicpass.password.benchmark import CATEGORIES, BenchmarkSample
from indicpass.password.meter import IndicPassMeter

__all__ = [
    "ESTIMATORS",
    "CategoryComparison",
    "CategoryStats",
    "EstimatorComparison",
    "SampleResult",
    "aggregate",
    "compare",
    "compare_estimators",
    "compare_estimators_all",
    "false_match_probe",
    "pcfg_structure_census",
    "score_corpus",
    "shadow_rows",
]

#: Every estimator a row can carry a column for. ``indicpass`` is the Milestone
#: 2 meter, ``pcfg`` the Milestone 3 grammar, ``baseline`` zxcvbn. Named here so
#: a comparison cannot be requested against a column that does not exist.
ESTIMATORS: tuple[str, ...] = ("indicpass", "pcfg", "baseline")


@dataclass(frozen=True)
class SampleResult:
    """One password scored by one meter, and by the baseline if one was attached.

    Holds the sample's *identity*, never its text. This is the row that reaches
    a report, so the type itself is where the no-plaintext rule is enforced.
    """

    sample_id: str
    category: str
    length: int
    construction: str
    log10_guesses: float
    score: int
    #: Dictionary hits in the winning segmentation.
    indic_matches: int
    #: Hits priced by a measured rank rather than a provenance tier.
    ranked_matches: int
    baseline_log10_guesses: float | None = None
    baseline_score: int | None = None

    # -- the PCFG columns, present only when a grammar was attached ---------
    #: The reported PCFG estimate: ``min(grammar, brute force)``.
    pcfg_log10_guesses: float | None = None
    pcfg_score: int | None = None
    #: What the grammar said before the brute-force floor. Kept separately so a
    #: report can show how often the floor, rather than the model, produced the
    #: number -- which on random controls is the whole question.
    pcfg_grammar_log10_guesses: float | None = None
    pcfg_floor_applied: bool | None = None
    #: False when no derivation covers the password at all.
    pcfg_supported: bool | None = None
    #: The winning derivation's category sequence, e.g. ``"word+year"``. Shape
    #: only -- the same class of information as ``construction`` -- so it is
    #: safe to publish and is what makes a per-category mean interpretable.
    pcfg_structure: str = ""
    #: Dictionary segments in the winning derivation. On the random controls
    #: this is the count of hallucinated lexical structure.
    pcfg_word_segments: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sample_id": self.sample_id,
            "category": self.category,
            "length": self.length,
            "construction": self.construction,
            "log10_guesses": round(self.log10_guesses, 4),
            "score": self.score,
            "indic_matches": self.indic_matches,
            "ranked_matches": self.ranked_matches,
        }
        if self.baseline_log10_guesses is not None:
            payload["baseline_log10_guesses"] = round(self.baseline_log10_guesses, 4)
            payload["baseline_score"] = self.baseline_score
        if self.pcfg_log10_guesses is not None:
            payload["pcfg_log10_guesses"] = round(self.pcfg_log10_guesses, 4)
            payload["pcfg_score"] = self.pcfg_score
            payload["pcfg_grammar_log10_guesses"] = round(
                self.pcfg_grammar_log10_guesses or 0.0, 4
            )
            payload["pcfg_floor_applied"] = self.pcfg_floor_applied
            payload["pcfg_supported"] = self.pcfg_supported
            payload["pcfg_structure"] = self.pcfg_structure
            payload["pcfg_word_segments"] = self.pcfg_word_segments
        return payload

    def column(self, estimator: str) -> float | None:
        """This row's ``log10`` estimate for *estimator*, or ``None``."""
        if estimator == "indicpass":
            return self.log10_guesses
        if estimator == "pcfg":
            return self.pcfg_log10_guesses
        if estimator == "baseline":
            return self.baseline_log10_guesses
        raise ValueError(f"Unknown estimator {estimator!r}. Known: {list(ESTIMATORS)}.")

    def score_column(self, estimator: str) -> int | None:
        if estimator == "indicpass":
            return self.score
        if estimator == "pcfg":
            return self.pcfg_score
        if estimator == "baseline":
            return self.baseline_score
        raise ValueError(f"Unknown estimator {estimator!r}. Known: {list(ESTIMATORS)}.")


def score_corpus(
    meter: IndicPassMeter, samples: Sequence[BenchmarkSample]
) -> list[SampleResult]:
    """Score every sample, keeping only what may be published.

    The password goes in and does not come out: what is retained is the
    sample's id, its shape, and the two estimates.
    """
    results: list[SampleResult] = []
    for sample in samples:
        result = meter.score(sample.password)
        matches = [m for m in result.matched_patterns if m.pattern == "indic_word"]
        pcfg = result.pcfg
        results.append(
            SampleResult(
                sample_id=sample.sample_id,
                category=sample.category,
                length=len(sample.password),
                construction=sample.construction,
                log10_guesses=result.log10_guesses,
                score=result.strength_score,
                indic_matches=len(matches),
                ranked_matches=sum(
                    1 for m in matches if m.detail.get("rank_policy") == "observed_rank"
                ),
                baseline_log10_guesses=result.baseline_log10_guesses,
                baseline_score=result.baseline_score,
                pcfg_log10_guesses=pcfg.log10_guesses if pcfg else None,
                pcfg_score=pcfg.score if pcfg else None,
                pcfg_grammar_log10_guesses=pcfg.grammar_log10_guesses if pcfg else None,
                pcfg_floor_applied=pcfg.floor_applied if pcfg else None,
                pcfg_supported=pcfg.supported if pcfg else None,
                pcfg_structure="+".join(pcfg.structure) if pcfg else "",
                pcfg_word_segments=(
                    sum(1 for name in pcfg.structure if name == "word") if pcfg else 0
                ),
            )
        )
    return results


def _mean(values: Sequence[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def _median(values: Sequence[float]) -> float:
    return round(statistics.median(values), 4) if values else 0.0


@dataclass(frozen=True)
class CategoryStats:
    """One estimator's behaviour on one category."""

    category: str
    samples: int
    mean_log10_guesses: float
    median_log10_guesses: float
    mean_score: float
    median_score: float
    #: Share of samples where the dictionary contributed at all.
    match_rate: float
    #: Share of samples where at least one hit was priced by measured rank.
    ranked_match_rate: float
    score_distribution: dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "samples": self.samples,
            "mean_log10_guesses": self.mean_log10_guesses,
            "median_log10_guesses": self.median_log10_guesses,
            "mean_score": self.mean_score,
            "median_score": self.median_score,
            "match_rate": self.match_rate,
            "ranked_match_rate": self.ranked_match_rate,
            "score_distribution": {str(k): v for k, v in sorted(self.score_distribution.items())},
        }


def aggregate(results: Sequence[SampleResult], category: str) -> CategoryStats:
    rows = [row for row in results if row.category == category]
    if not rows:
        return CategoryStats(category, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    logs = [row.log10_guesses for row in rows]
    scores = [float(row.score) for row in rows]
    distribution: dict[int, int] = {}
    for row in rows:
        distribution[row.score] = distribution.get(row.score, 0) + 1

    return CategoryStats(
        category=category,
        samples=len(rows),
        mean_log10_guesses=_mean(logs),
        median_log10_guesses=_median(logs),
        mean_score=_mean(scores),
        median_score=_median(scores),
        match_rate=round(sum(1 for row in rows if row.indic_matches) / len(rows), 4),
        ranked_match_rate=round(sum(1 for row in rows if row.ranked_matches) / len(rows), 4),
        score_distribution=distribution,
    )


@dataclass(frozen=True)
class CategoryComparison:
    """IndicPass against the baseline, on one category, same passwords.

    ``lower`` counts the samples where IndicPass estimated FEWER guesses than
    the baseline -- it found the password easier to reach. On an Indic category
    that is the hypothesis; on the random controls it is a warning sign.
    """

    category: str
    samples: int
    indicpass: CategoryStats
    baseline: CategoryStats
    lower: int
    higher: int
    equal: int
    mean_difference: float
    median_difference: float
    #: Samples where the two 0-4 scores disagree, and by how much on average.
    score_disagreements: int
    mean_score_difference: float
    #: min(IndicPass, baseline) per sample -- see :func:`compare`.
    combined_mean_log10_guesses: float = 0.0
    combined_median_log10_guesses: float = 0.0
    #: Mean of combined minus baseline. Never positive; how much the Indic
    #: lexicon lowers the estimate *beyond* what the baseline already found.
    mean_information_added: float = 0.0
    median_information_added: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "samples": self.samples,
            "indicpass": self.indicpass.to_dict(),
            "baseline": self.baseline.to_dict(),
            "indicpass_lower": self.lower,
            "indicpass_higher": self.higher,
            "equal": self.equal,
            "mean_log10_difference": self.mean_difference,
            "median_log10_difference": self.median_difference,
            "score_disagreements": self.score_disagreements,
            "mean_score_difference": self.mean_score_difference,
            "combined_mean_log10_guesses": self.combined_mean_log10_guesses,
            "combined_median_log10_guesses": self.combined_median_log10_guesses,
            "mean_information_added": self.mean_information_added,
            "median_information_added": self.median_information_added,
            "direction_note": (
                "Negative means IndicPass estimates FEWER guesses than the baseline. "
                "Lower is not automatically more accurate: that requires a reference "
                "attack model, which this project does not have."
            ),
            "combined_note": (
                "combined = min(IndicPass, baseline) per password. Guessing cost is a "
                "minimum over the attacker's options, so an attacker holding both "
                "wordlists pays the smaller. mean_information_added is combined minus "
                "baseline: what the Indic lexicon finds that the baseline did not."
            ),
        }


#: Two estimates within this many orders of magnitude count as agreeing. Below
#: it the difference is smaller than the modelling error in either estimator,
#: so calling one of them the winner would be noise.
AGREEMENT_TOLERANCE = 0.05


def compare(results: Sequence[SampleResult], category: str) -> CategoryComparison:
    """IndicPass against its baseline on one category.

    Raises rather than silently comparing against nothing: a comparison table
    with a missing baseline column is worse than no table.
    """
    rows = [row for row in results if row.category == category]
    missing = [row.sample_id for row in rows if row.baseline_log10_guesses is None]
    if missing:
        raise ValueError(
            f"{len(missing)} samples in {category!r} have no baseline estimate "
            f"(first: {missing[0]}). Score the corpus with a baseline attached."
        )

    baseline_rows = [
        SampleResult(
            sample_id=row.sample_id,
            category=row.category,
            length=row.length,
            construction=row.construction,
            log10_guesses=row.baseline_log10_guesses,  # type: ignore[arg-type]
            score=row.baseline_score,  # type: ignore[arg-type]
            indic_matches=0,
            ranked_matches=0,
        )
        for row in rows
    ]

    differences = [
        row.log10_guesses - row.baseline_log10_guesses  # type: ignore[operator]
        for row in rows
    ]
    score_differences = [
        float(row.score - row.baseline_score)  # type: ignore[operator]
        for row in rows
    ]

    # An attacker holding both wordlists pays the smaller of the two costs --
    # guessing is a minimum over the options available, which is the same rule
    # the segmentation search already applies within one estimator. So the
    # question "does the Indic lexicon carry information the baseline lacks?"
    # is answered by how far below the baseline this minimum sits, and NOT by
    # whether IndicPass alone beats the baseline. IndicPass has no
    # common-password list; it was never going to win outright, and being
    # beaten on English passwords is not evidence against the hypothesis.
    combined = [
        min(row.log10_guesses, row.baseline_log10_guesses)  # type: ignore[type-var]
        for row in rows
    ]
    information = [
        value - row.baseline_log10_guesses  # type: ignore[operator]
        for value, row in zip(combined, rows, strict=True)
    ]

    return CategoryComparison(
        category=category,
        samples=len(rows),
        indicpass=aggregate(rows, category),
        baseline=aggregate(baseline_rows, category),
        lower=sum(1 for d in differences if d < -AGREEMENT_TOLERANCE),
        higher=sum(1 for d in differences if d > AGREEMENT_TOLERANCE),
        equal=sum(1 for d in differences if abs(d) <= AGREEMENT_TOLERANCE),
        mean_difference=_mean(differences),
        median_difference=_median(differences),
        score_disagreements=sum(1 for d in score_differences if d != 0),
        mean_score_difference=_mean(score_differences),
        combined_mean_log10_guesses=_mean(combined),
        combined_median_log10_guesses=_median(combined),
        mean_information_added=_mean(information),
        median_information_added=_median(information),
    )


def compare_all(results: Sequence[SampleResult]) -> list[CategoryComparison]:
    """Every populated category, in the canonical order."""
    present = {row.category for row in results}
    return [compare(results, name) for name in CATEGORIES if name in present]


def aggregate_all(results: Sequence[SampleResult]) -> list[CategoryStats]:
    present = {row.category for row in results}
    return [aggregate(results, name) for name in CATEGORIES if name in present]


# -- comparing any two estimators -----------------------------------------


def shadow_rows(rows: Sequence[SampleResult], estimator: str) -> list[SampleResult]:
    """*rows* rewritten so *estimator*'s column is the primary one.

    Lets :func:`aggregate` -- and every statistic already defined on it -- be
    reused for the PCFG without a second implementation that could drift from
    the first.
    """
    shadowed: list[SampleResult] = []
    for row in rows:
        value = row.column(estimator)
        if value is None:
            raise ValueError(
                f"Sample {row.sample_id} has no {estimator!r} estimate. "
                "Score the corpus with that estimator attached."
            )
        shadowed.append(
            SampleResult(
                sample_id=row.sample_id,
                category=row.category,
                length=row.length,
                construction=row.construction,
                log10_guesses=value,
                score=row.score_column(estimator) or 0,
                # Match counts belong to the Milestone 2 matcher and mean
                # nothing for another estimator, so they are zeroed rather than
                # carried across and quietly misread.
                indic_matches=row.indic_matches if estimator == "indicpass" else 0,
                ranked_matches=row.ranked_matches if estimator == "indicpass" else 0,
            )
        )
    return shadowed


@dataclass(frozen=True)
class EstimatorComparison:
    """Any two estimators, on one category, over the same passwords.

    Deliberately separate from :class:`CategoryComparison`, which is the
    Milestone 2 report's schema and is left byte-identical so that the two
    milestones' numbers stay comparable.

    ``improved`` counts samples where *left* estimated fewer guesses than
    *right*. On an Indic category that is the hypothesis; on the random controls
    it is a warning sign, and the same number must be read both ways.
    """

    category: str
    samples: int
    left: str
    right: str
    left_stats: CategoryStats
    right_stats: CategoryStats
    mean_difference: float
    median_difference: float
    improved: int
    worsened: int
    equal: int
    combined_mean_log10_guesses: float
    combined_median_log10_guesses: float
    mean_information_added: float
    median_information_added: float
    score_disagreements: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "samples": self.samples,
            "left": self.left,
            "right": self.right,
            f"{self.left}_stats": self.left_stats.to_dict(),
            f"{self.right}_stats": self.right_stats.to_dict(),
            "mean_log10_difference": self.mean_difference,
            "median_log10_difference": self.median_difference,
            "left_lower": self.improved,
            "left_higher": self.worsened,
            "equal": self.equal,
            "combined_mean_log10_guesses": self.combined_mean_log10_guesses,
            "combined_median_log10_guesses": self.combined_median_log10_guesses,
            "mean_information_added": self.mean_information_added,
            "median_information_added": self.median_information_added,
            "score_disagreements": self.score_disagreements,
            "direction_note": (
                f"Negative means {self.left} estimates FEWER guesses than {self.right}. "
                "Lower is not automatically more accurate: that requires a reference "
                "attack model, which this project does not have."
            ),
        }


def compare_estimators(
    results: Sequence[SampleResult],
    category: str,
    *,
    left: str = "pcfg",
    right: str = "baseline",
) -> EstimatorComparison:
    """Compare two of :data:`ESTIMATORS` on one category."""
    for name in (left, right):
        if name not in ESTIMATORS:
            raise ValueError(f"Unknown estimator {name!r}. Known: {list(ESTIMATORS)}.")

    rows = [row for row in results if row.category == category]
    left_rows = shadow_rows(rows, left)
    right_rows = shadow_rows(rows, right)

    differences = [
        a.log10_guesses - b.log10_guesses
        for a, b in zip(left_rows, right_rows, strict=True)
    ]
    combined = [
        min(a.log10_guesses, b.log10_guesses)
        for a, b in zip(left_rows, right_rows, strict=True)
    ]
    information = [
        value - b.log10_guesses for value, b in zip(combined, right_rows, strict=True)
    ]

    return EstimatorComparison(
        category=category,
        samples=len(rows),
        left=left,
        right=right,
        left_stats=aggregate(left_rows, category),
        right_stats=aggregate(right_rows, category),
        mean_difference=_mean(differences),
        median_difference=_median(differences),
        improved=sum(1 for d in differences if d < -AGREEMENT_TOLERANCE),
        worsened=sum(1 for d in differences if d > AGREEMENT_TOLERANCE),
        equal=sum(1 for d in differences if abs(d) <= AGREEMENT_TOLERANCE),
        combined_mean_log10_guesses=_mean(combined),
        combined_median_log10_guesses=_median(combined),
        mean_information_added=_mean(information),
        median_information_added=_median(information),
        score_disagreements=sum(
            1
            for a, b in zip(left_rows, right_rows, strict=True)
            if a.score != b.score
        ),
    )


def compare_estimators_all(
    results: Sequence[SampleResult], *, left: str = "pcfg", right: str = "baseline"
) -> list[EstimatorComparison]:
    present = {row.category for row in results}
    return [
        compare_estimators(results, name, left=left, right=right)
        for name in CATEGORIES
        if name in present
    ]


def pcfg_structure_census(
    results: Sequence[SampleResult], category: str, *, limit: int = 6
) -> dict[str, Any]:
    """Which derivations the grammar actually chose, and how often.

    A per-category mean cannot tell a reader whether ``indic_year`` parsed as
    ``word+year`` or as four unknown runs. This can, and it publishes only the
    category sequence -- the shape, never the content.
    """
    rows = [row for row in results if row.category == category]
    if not rows:
        return {"category": category, "samples": 0, "structures": []}

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.pcfg_structure] = counts.get(row.pcfg_structure, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    return {
        "category": category,
        "samples": len(rows),
        "distinct_structures": len(counts),
        "structures": [
            {"structure": name or "(unsupported)", "samples": count,
             "share": round(count / len(rows), 4)}
            for name, count in ranked[:limit]
        ],
        "word_segment_rate": round(
            sum(1 for row in rows if row.pcfg_word_segments) / len(rows), 4
        ),
        "floor_rate": round(
            sum(1 for row in rows if row.pcfg_floor_applied) / len(rows), 4
        ),
        "unsupported_rate": round(
            sum(1 for row in rows if row.pcfg_supported is False) / len(rows), 4
        ),
    }


#: Lengths and alphabets the false-match probe sweeps. Chosen to bracket real
#: password lengths, and to separate "the dictionary is large" from "the
#: password happens to be lower-case letters", which is the only charset a
#: Romanized-Indic wordlist could ever match inside.
FALSE_MATCH_LENGTHS: tuple[int, ...] = (6, 8, 10, 12, 14)
FALSE_MATCH_ALPHABETS: dict[str, str] = {
    "lower": string.ascii_lowercase,
    "alnum": string.ascii_letters + string.digits,
    "full": string.ascii_letters + string.digits + "@!#$*&_.-+",
}


def false_match_probe(
    meter: IndicPassMeter,
    *,
    seed: int,
    samples: int = 500,
    lengths: Sequence[int] = FALSE_MATCH_LENGTHS,
    alphabets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """How often a large wordlist "recognises" a string with nothing in it.

    A dictionary of 298k entries contains a great many short strings, and a
    matcher will find some of them inside almost any text. Two numbers separate
    a real problem from a harmless one:

    *offered* -- the matcher found at least one dictionary span. This is
    expected to be high and is not by itself a defect; the matcher's job is to
    offer candidates.

    *accepted* -- a dictionary span survived into the **winning segmentation**,
    i.e. the guess estimate actually rests on it. This is the number that
    matters, because only an accepted match changes the answer.

    The gap between the two is the segmentation search doing its job: an
    expensive fragment is offered and then rejected in favour of calling the
    span unexplained.

    Deterministic in *seed*, so the figure in a report can be reproduced.
    """
    table = dict(alphabets or FALSE_MATCH_ALPHABETS)
    rows: list[dict[str, Any]] = []

    for name, alphabet in table.items():
        for length in lengths:
            # Seeded per cell from a string, so adding a length or an alphabet
            # leaves every other cell's strings untouched. A string seed is
            # hashed by ``Random`` itself; a tuple's ``hash()`` is salted per
            # process and would not reproduce across runs.
            rng = random.Random(f"false-match:{seed}:{name}:{length}")
            offered_counts: list[int] = []
            accepted_counts: list[int] = []

            for _ in range(samples):
                password = "".join(rng.choice(alphabet) for _ in range(length))
                offered = sum(
                    1
                    for match in meter.matcher.matches(password)
                    if match.pattern == "indic_word"
                )
                result = meter.score(password)
                accepted = sum(
                    1 for m in result.matched_patterns if m.pattern == "indic_word"
                )
                offered_counts.append(offered)
                accepted_counts.append(accepted)

            rows.append(
                {
                    "alphabet": name,
                    "length": length,
                    "samples": samples,
                    "offered_rate": round(
                        sum(1 for c in offered_counts if c) / samples, 4
                    ),
                    "mean_offered": _mean([float(c) for c in offered_counts]),
                    "median_offered": _median([float(c) for c in offered_counts]),
                    "accepted_rate": round(
                        sum(1 for c in accepted_counts if c) / samples, 4
                    ),
                    "mean_accepted": _mean([float(c) for c in accepted_counts]),
                    "median_accepted": _median([float(c) for c in accepted_counts]),
                }
            )

    accepted_rates = [row["accepted_rate"] for row in rows]
    return {
        "seed": seed,
        "samples_per_cell": samples,
        "rows": rows,
        "worst_accepted_rate": max(accepted_rates) if accepted_rates else 0.0,
        "note": (
            "offered = the matcher found a dictionary span. accepted = one survived "
            "into the winning segmentation, so the guess estimate rests on it. Only "
            "the second changes an answer; the gap between them is the segmentation "
            "search rejecting fragments that are more expensive than calling the span "
            "unexplained."
        ),
    }


def overall(results: Iterable[SampleResult]) -> dict[str, Any]:
    """Corpus-wide figures, reported only alongside the per-category table.

    An overall average across categories is close to meaningless here -- it
    mixes seven deliberately different populations whose relative sizes were
    chosen by the generator, not by the world. It is carried because a reader
    will look for it, and labelled so nobody quotes it alone.
    """
    rows = list(results)
    logs = [row.log10_guesses for row in rows]
    return {
        "samples": len(rows),
        "mean_log10_guesses": _mean(logs),
        "median_log10_guesses": _median(logs),
        "note": (
            "Mixes seven populations whose proportions are an artefact of the "
            "generator. Read the per-category table instead."
        ),
    }
