"""From a probability to a guess number, and from there to a strength score.

The step this module performs is the one that separates a probabilistic model
from a scoring heuristic, and it is worth being precise about.

A PCFG gives ``P(password)``. That is not a guess number. The guess number is

    G(x) = |{ y : P(y) >= P(x) }|

-- how many passwords an attacker enumerating in descending probability order
tries before reaching this one. The two are related but not interchangeable:
``1/P`` is a well-known *upper bound* on ``G`` and over-states it badly for
common passwords, because near the head of the distribution many passwords share
similar probabilities.

Computing ``G`` exactly means enumerating the grammar, which is the thing
guessing is expensive for. Instead this uses the Monte-Carlo strength estimator
of Dell'Amico & Filippone (CCS 2015): draw ``N`` derivations from the model and

    G_hat(x) = (1/N) * sum over { i : P(y_i) >= P(x) } of 1 / P(y_i)

which is **unbiased** -- the expectation of ``1{P(y) >= P(x)} / P(y)`` under
``y ~ P`` is exactly the count above. The estimator needs only the sampled
*probabilities*, so the sampler never assembles a password (see
:meth:`~indicpass.password.pcfg.grammar.PcfgGrammar.sample_log10_probability`),
and the artefact this produces is a monotone curve rather than a wordlist.

Two safeguards on the curve
---------------------------
``G(x) <= 1 / P(x)`` always: at most ``1/p`` passwords can have probability
``>= p``. That bound is applied unconditionally, which also makes the tail
extrapolation safe -- below the sampled range the curve is extrapolated
log-linearly and then clipped by the bound, so it can never claim more
certainty than the samples support.

The brute-force floor is not part of the grammar
------------------------------------------------
An attacker chooses the cheaper of "use the model" and "enumerate strings", so
the reported estimate is ``min(G_hat, C^len)``. That floor is the Milestone 2
brute-force assumption, retained deliberately and kept **outside** the
probability model: it is a statement about an alternative attack, not a
production of the grammar. Both numbers are reported separately
(``grammar_log10_guesses`` and ``bruteforce_log10_guesses``) so no reader has to
guess which one produced a result, and ``floor_applied`` says which won.

Without it the model would over-estimate random strings, which Milestone 2
established is the dangerous direction for a meter to err in and the failure
mode the random controls exist to catch.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from indicpass.password.patterns import bruteforce_log10_guesses, observed_cardinality
from indicpass.password.pcfg.grammar import PcfgGrammar
from indicpass.password.pcfg.parser import Derivation, best_derivation
from indicpass.password.result import guesses_from_log10, round_guesses
from indicpass.password.scoring import StrengthScale

__all__ = [
    "EstimatorSettings",
    "GuessCurve",
    "PcfgEstimate",
    "PcfgEstimator",
]

_NEGATIVE_INFINITY = -math.inf

#: Slope of the tail extrapolation is clamped to this range. The upper limit is
#: not arbitrary: ``G <= 1/p`` forces ``d log10 G / d(-log10 p) <= 1``
#: asymptotically, so a steeper fitted slope is sampling noise.
_TAIL_SLOPE_RANGE = (0.0, 1.0)


def log10_add(a: float, b: float) -> float:
    """``log10(10**a + 10**b)`` without forming either power."""
    if a == _NEGATIVE_INFINITY:
        return b
    if b == _NEGATIVE_INFINITY:
        return a
    if a == math.inf or b == math.inf:
        return math.inf
    high, low = (a, b) if a >= b else (b, a)
    return high + math.log10(1.0 + 10.0 ** (low - high))


@dataclass(frozen=True)
class EstimatorSettings:
    """How the guess curve is built and how the floor is applied."""

    #: Derivations drawn to build the curve. Higher is a better estimate of the
    #: head of the distribution and costs one-off training time only.
    samples: int
    #: Seed for the sampler. The curve is an artefact, so this is what makes it
    #: reproducible -- there is no other randomness in the pipeline.
    sample_seed: int
    #: Points kept in the stored curve. Sampled geometrically over the sorted
    #: draws so the head, where the resolution matters, stays dense.
    curve_points: int
    #: Apply ``min(grammar, brute force)``. Off, the grammar's own number is
    #: reported -- an ablation arm, not a deployable configuration.
    bruteforce_floor: bool
    bruteforce_cardinality: str | int
    character_class_sizes: Mapping[str, int]

    @classmethod
    def from_config(
        cls, pcfg: Mapping[str, Any], scoring: Mapping[str, Any]
    ) -> EstimatorSettings:
        estimator = dict(pcfg.get("estimator") or {})
        raw = scoring.get("bruteforce_cardinality", "observed")
        return cls(
            samples=int(estimator.get("samples", 200000)),
            sample_seed=int(estimator.get("sample_seed", 42)),
            curve_points=int(estimator.get("curve_points", 2000)),
            bruteforce_floor=bool(estimator.get("bruteforce_floor", True)),
            bruteforce_cardinality="observed" if raw == "observed" else int(raw),
            character_class_sizes=dict(scoring.get("character_class_sizes") or {}),
        )

    def cardinality_for(self, password: str) -> int:
        if self.bruteforce_cardinality == "observed":
            return observed_cardinality(password, self.character_class_sizes)
        return max(int(self.bruteforce_cardinality), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "sample_seed": self.sample_seed,
            "curve_points": self.curve_points,
            "bruteforce_floor": self.bruteforce_floor,
            "bruteforce_cardinality": self.bruteforce_cardinality,
        }


@dataclass(frozen=True)
class GuessCurve:
    """The monotone map from ``log10 P`` to ``log10 G``, built by Monte Carlo.

    Stored descending in probability and ascending in guesses. Holds no
    password: the sampler discarded every string it drew, so this is a few
    thousand pairs of floats and nothing else.
    """

    log10_probabilities: tuple[float, ...]
    log10_guesses: tuple[float, ...]
    samples: int
    seed: int
    tail_slope: float
    #: Segment counts drawn, as a histogram. A cheap check that the structure
    #: prior did what it was configured to do.
    segment_histogram: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ascending negatives, for bisect. Built once: the lookup runs per span
        # of every password scored, and rebuilding a 1,300-element list there
        # would cost more than the parse it belongs to.
        object.__setattr__(
            self, "_descending", [-value for value in self.log10_probabilities]
        )

    @classmethod
    def build(
        cls,
        grammar: PcfgGrammar,
        *,
        samples: int,
        seed: int,
        curve_points: int = 2000,
    ) -> GuessCurve:
        if samples < 2:
            raise ValueError(f"The guess curve needs at least 2 samples; got {samples}.")

        rng = random.Random(f"pcfg-guess-curve:{seed}")
        drawn: list[float] = []
        histogram: dict[int, int] = {}
        for _ in range(samples):
            log10_probability, segments = grammar.sample_log10_probability(rng)
            if log10_probability == _NEGATIVE_INFINITY:
                continue
            drawn.append(log10_probability)
            histogram[segments] = histogram.get(segments, 0) + 1

        if len(drawn) < 2:
            raise ValueError(
                "The grammar produced no samplable derivations. Check that the "
                "category prior gives some category positive weight."
            )

        drawn.sort(reverse=True)
        log10_n = math.log10(len(drawn))

        # cumulative[j] = log10 of sum over i <= j of 1 / (N * p_i). Accumulated
        # in log space because 1/p is astronomically large in the tail and would
        # overflow a float long before the curve ended.
        cumulative: list[float] = []
        running = _NEGATIVE_INFINITY
        for value in drawn:
            running = log10_add(running, -value - log10_n)
            cumulative.append(running)

        indices = _geometric_indices(len(drawn), curve_points)
        probabilities = tuple(drawn[i] for i in indices)
        guesses = tuple(max(cumulative[i], 0.0) for i in indices)

        return cls(
            log10_probabilities=probabilities,
            log10_guesses=guesses,
            samples=len(drawn),
            seed=seed,
            tail_slope=_tail_slope(probabilities, guesses),
            segment_histogram=dict(sorted(histogram.items())),
        )

    # -- lookup ------------------------------------------------------------

    def log10_guesses_for(self, log10_probability: float) -> float:
        """``log10 G`` for a password of this probability.

        The estimator is a sum over every sample at least as probable as the
        query, so the lookup must land on the **last** curve point whose
        probability still satisfies that -- not the first. The difference is
        invisible until probabilities tie, and then it is the whole answer: a
        grammar generating ten equiprobable passwords must say ten, and reading
        the first tied point would say one.

        Clipped by ``G <= 1/P`` in every branch: interpolation, extrapolation
        and both ends. That bound is exact, so applying it can only correct the
        estimate towards the truth, and it is what makes the tail extrapolation
        safe.
        """
        if log10_probability == _NEGATIVE_INFINITY:
            return math.inf
        bound = -log10_probability
        probabilities = self.log10_probabilities
        guesses = self.log10_guesses

        # bisect_right over the ascending negatives counts the points with
        # probability >= the query; one less is the last such index.
        index = bisect_right(self._descending, -log10_probability) - 1

        if index < 0:
            # More probable than anything sampled: nothing outranks it.
            return 0.0

        if index >= len(probabilities) - 1:
            if log10_probability >= probabilities[-1]:
                return max(0.0, min(guesses[-1], bound))
            overshoot = probabilities[-1] - log10_probability
            return max(0.0, min(guesses[-1] + self.tail_slope * overshoot, bound))

        high_p, low_p = probabilities[index], probabilities[index + 1]
        high_g, low_g = guesses[index], guesses[index + 1]
        span = high_p - low_p
        weight = 0.0 if span == 0 else (high_p - log10_probability) / span
        return max(0.0, min(high_g + weight * (low_g - high_g), bound))

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "seed": self.seed,
            "points": len(self.log10_probabilities),
            "tail_slope": round(self.tail_slope, 6),
            # Rounded UPWARD, not to nearest. A curve point often *is* the most
            # probable derivation of some real password -- the commonest word in
            # the dictionary, say -- and that password's query then ties the
            # point exactly. Rounding to nearest can push the stored point a
            # hair below the query, which drops it out of the lookup and
            # collapses the estimate to one guess. Rounding up keeps every tie
            # on the inside, at a cost of at most 1e-6 log10.
            "log10_probabilities": [_ceiling(v, 6) for v in self.log10_probabilities],
            "log10_guesses": [round(v, 6) for v in self.log10_guesses],
            "segment_histogram": {str(k): v for k, v in (self.segment_histogram or {}).items()},
            "method": (
                "Monte-Carlo strength estimation (Dell'Amico & Filippone, CCS 2015): "
                "G_hat(x) = (1/N) * sum of 1/P(y_i) over samples with P(y_i) >= P(x). "
                "Unbiased for the number of passwords the model ranks at or above x."
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GuessCurve:
        return cls(
            log10_probabilities=tuple(float(v) for v in data["log10_probabilities"]),
            log10_guesses=tuple(float(v) for v in data["log10_guesses"]),
            samples=int(data["samples"]),
            seed=int(data["seed"]),
            tail_slope=float(data["tail_slope"]),
            segment_histogram={
                int(k): int(v) for k, v in (data.get("segment_histogram") or {}).items()
            },
        )


def _ceiling(value: float, digits: int) -> float:
    """``value`` rounded up to *digits* decimal places."""
    scale = 10.0**digits
    return math.ceil(value * scale) / scale


def _geometric_indices(total: int, points: int) -> list[int]:
    """Indices into a sorted sample, dense at the head.

    The head is where a difference of one order of magnitude in probability is a
    difference of one order of magnitude in guesses, so a linear subsample would
    throw away exactly the resolution that matters and keep the tail, where the
    curve is nearly straight.
    """
    if points >= total:
        return list(range(total))
    chosen = {0, total - 1}
    for step in range(points):
        position = (total - 1) ** (step / max(points - 1, 1))
        chosen.add(int(position))
    return sorted(chosen)


def _tail_slope(
    probabilities: Sequence[float], guesses: Sequence[float]
) -> float:
    """``d log10 G / d(-log10 P)`` over the last decade of the curve."""
    if len(probabilities) < 2:
        return 1.0
    edge = probabilities[-1]
    start = 0
    for index, value in enumerate(probabilities):
        if value <= edge + 1.0:
            start = index
            break
    start = min(start, len(probabilities) - 2)
    run = probabilities[start] - probabilities[-1]
    if run <= 0:
        return 1.0
    rise = guesses[-1] - guesses[start]
    low, high = _TAIL_SLOPE_RANGE
    return min(max(rise / run, low), high)


# -- the estimate ----------------------------------------------------------


@dataclass(frozen=True)
class PcfgEstimate:
    """What the PCFG concluded about one password.

    Carries the derivation as well as the number. A guess estimate nobody can
    argue with is not a research result, so the parse, the per-segment
    probabilities, the structure prior's own contribution and which of the two
    attack models won are all on the record.
    """

    #: The reported estimate: ``min(grammar, brute force)`` when the floor is on.
    log10_guesses: float
    guesses: float
    score: int
    label: str

    #: ``log10 P(password)`` under the grammar.
    log10_probability: float
    #: What the grammar alone said, before the floor.
    grammar_log10_guesses: float
    #: What enumerating strings would cost. Not a production of the grammar.
    bruteforce_log10_guesses: float
    #: True when brute force was the cheaper of the two.
    floor_applied: bool
    #: False when no derivation covers the password.
    supported: bool

    structure: tuple[str, ...] = ()
    segments: tuple[dict[str, Any], ...] = ()
    log10_structure_prior: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "guesses": round_guesses(self.guesses),
            "log10_guesses": round(self.log10_guesses, 6),
            "score": self.score,
            "label": self.label,
            "log10_probability": round(self.log10_probability, 6),
            "grammar_log10_guesses": round(self.grammar_log10_guesses, 6),
            "bruteforce_log10_guesses": round(self.bruteforce_log10_guesses, 6),
            "floor_applied": self.floor_applied,
            "supported": self.supported,
            "structure": list(self.structure),
            "log10_structure_prior": round(self.log10_structure_prior, 6),
            "segments": list(self.segments),
        }


class PcfgEstimator:
    """Grammar + curve + scale: the object the meter and the reports talk to."""

    name = "pcfg"

    def __init__(
        self,
        grammar: PcfgGrammar,
        curve: GuessCurve,
        *,
        settings: EstimatorSettings,
        scale: StrengthScale,
        version: str = "1.0",
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        self.grammar = grammar
        self.curve = curve
        self.settings = settings
        self.scale = scale
        self.version = version
        self.provenance = dict(provenance or {})

    # -- construction ------------------------------------------------------

    @classmethod
    def train(
        cls,
        grammar: PcfgGrammar,
        *,
        settings: EstimatorSettings,
        scale: StrengthScale,
        version: str = "1.0",
        provenance: Mapping[str, Any] | None = None,
    ) -> PcfgEstimator:
        curve = GuessCurve.build(
            grammar,
            samples=settings.samples,
            seed=settings.sample_seed,
            curve_points=settings.curve_points,
        )
        return cls(
            grammar,
            curve,
            settings=settings,
            scale=scale,
            version=version,
            provenance=provenance,
        )

    # -- scoring -----------------------------------------------------------

    def derive(self, password: str) -> Derivation:
        return best_derivation(self.grammar, password)

    def estimate(self, password: str, *, include_tokens: bool = False) -> PcfgEstimate:
        """Score *password*. The string is read and discarded."""
        derivation = self.derive(password)
        bruteforce = bruteforce_log10_guesses(
            password, cardinality=self.settings.cardinality_for(password)
        )

        grammar_guesses = self.curve.log10_guesses_for(derivation.log10_probability)
        if self.settings.bruteforce_floor:
            reported = min(grammar_guesses, bruteforce)
        else:
            reported = grammar_guesses
        # An unsupported password has no estimate of its own; the floor is then
        # the only statement available, and reporting `inf` would read as
        # "unbreakable" when it means "unmodelled".
        if not derivation.supported and self.settings.bruteforce_floor:
            reported = bruteforce

        return PcfgEstimate(
            log10_guesses=reported,
            guesses=guesses_from_log10(reported),
            score=self.scale.score(reported),
            label=self.scale.label(self.scale.score(reported)),
            log10_probability=derivation.log10_probability,
            grammar_log10_guesses=grammar_guesses,
            bruteforce_log10_guesses=bruteforce,
            floor_applied=self.settings.bruteforce_floor
            and (bruteforce <= grammar_guesses or not derivation.supported),
            supported=derivation.supported,
            structure=derivation.structure,
            segments=tuple(
                segment.describe(include_token=include_tokens)
                for segment in derivation.segments
            ),
            log10_structure_prior=derivation.log10_structure,
        )

    # -- provenance --------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "grammar": self.grammar.describe(),
            "estimator": self.settings.to_dict(),
            "curve": {
                "samples": self.curve.samples,
                "seed": self.curve.seed,
                "points": len(self.curve.log10_probabilities),
                "tail_slope": round(self.curve.tail_slope, 6),
            },
            **self.provenance,
        }

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<PcfgEstimator v{self.version} entries={len(self.grammar.dictionary):,} "
            f"samples={self.curve.samples:,}>"
        )
