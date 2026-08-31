"""Evaluation metrics for transliteration.

Character Error Rate is the primary metric, and the choice is forced by the
data rather than by taste. 13.33% of Romanized spellings in the Hindi corpus
map to more than one attested Devanagari form (see docs/dataset_pipeline.md),
so a model can produce a perfectly good transliteration that is not the string
this particular record happens to hold. Exact match scores that as a total
failure; CER scores it as the one or two characters it actually differs by.

Exact match is still reported, because it is what a user of a transliteration
box experiences, and because a sudden divergence between the two numbers is
informative. It is simply not what the best checkpoint is selected on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "MetricResult",
    "character_error_rate",
    "corpus_cer",
    "edit_distance",
    "evaluate_predictions",
    "exact_match",
]


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings.

    Two rows rather than a full matrix: the strings here are single words, but
    this runs over every validation example every epoch.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Iterate over the shorter string in the inner dimension.
    if len(a) < len(b):
        a, b = b, a

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (char_a != char_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(prediction: str, target: str) -> float:
    """CER for one pair: ``edit_distance / len(target)``.

    Empty target is defined explicitly rather than left to divide by zero:

    * empty target, empty prediction -> ``0.0`` (nothing was asked, nothing
      was wrong)
    * empty target, non-empty prediction -> ``1.0``, not ``len(prediction)``.

    The second case is a clamp. The textbook formula returns unbounded error
    for a spurious prediction, and one such example can outweigh hundreds of
    good ones in a corpus average. Preprocessing already drops empty targets,
    so this only guards against a decoder emitting into a degenerate record.
    """
    if not target:
        return 0.0 if not prediction else 1.0
    return edit_distance(prediction, target) / len(target)


def exact_match(prediction: str, target: str) -> bool:
    """Strict string equality. Secondary: see this module's docstring."""
    return prediction == target


def corpus_cer(predictions: Sequence[str], targets: Sequence[str]) -> float:
    """Corpus CER: total edit distance over total target length.

    Aggregated over the corpus, not averaged over per-example rates. A
    three-character word getting one character wrong is a 33% per-example
    rate; averaging those lets short words dominate. Summing first weights
    every character equally, which is what "character error rate" means.
    """
    if len(predictions) != len(targets):
        raise ValueError(
            f"Got {len(predictions)} predictions for {len(targets)} targets."
        )
    if not targets:
        return 0.0

    total_distance = 0
    total_length = 0
    # strict=True is belt-and-braces: the length check above already rejects a
    # mismatch, but a silent truncation here would understate the error rate.
    for prediction, target in zip(predictions, targets, strict=True):
        if not target:
            total_distance += 1 if prediction else 0
            total_length += 1  # avoid a zero denominator; see character_error_rate
            continue
        total_distance += edit_distance(prediction, target)
        total_length += len(target)

    return total_distance / total_length if total_length else 0.0


@dataclass(frozen=True)
class MetricResult:
    """Metrics over one evaluation pass."""

    cer: float
    exact_match: float
    count: int

    def as_dict(self) -> dict[str, float | int]:
        return {"cer": self.cer, "exact_match": self.exact_match, "count": self.count}

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"CER {self.cer:.4f} | exact {self.exact_match:.4f} | n={self.count}"


def evaluate_predictions(
    predictions: Sequence[str], targets: Sequence[str]
) -> MetricResult:
    """Corpus CER and exact-match accuracy for a set of decoded predictions."""
    if len(predictions) != len(targets):
        raise ValueError(
            f"Got {len(predictions)} predictions for {len(targets)} targets."
        )
    if not targets:
        return MetricResult(cer=0.0, exact_match=0.0, count=0)

    matches = sum(
        exact_match(prediction, target)
        for prediction, target in zip(predictions, targets, strict=True)
    )
    return MetricResult(
        cer=corpus_cer(predictions, targets),
        exact_match=matches / len(targets),
        count=len(targets),
    )
