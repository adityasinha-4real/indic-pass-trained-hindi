"""The grammar: nonterminals, productions, and where every probability comes from.

A password is modelled as a sequence of *segments*, each drawn from one of five
categories, each expanding to a string:

```
S      ->  C_1 C_2 ... C_k                      P(k) · prod P(C_i)
C      ->  word | unknown | digits | year | symbols
word   ->  <an IndicDict entry>, cased          P(entry) · P(case | length)
unknown->  <any Roman spelling>, cased          P_ngram(spelling) · P(case | length)
digits ->  <n digits>                           P(n) · 10^-n
year   ->  <a year in the configured window>    1 / |window|
symbols->  <n symbols>                          P(n) · |S|^-n
```

The grammar is deliberately **ambiguous**: a dictionary word can also be derived
through `unknown`, and `2024` through both `digits` and `year`. The parser takes
the maximum-probability derivation, which is the derivation an attacker
enumerating in probability order actually reaches the password by.

Which parts are learned, and which are not
-----------------------------------------
This is the honest core of the milestone, and it does not split the way a
textbook PCFG does.

**Learned from data in this repository**

* `P(entry)` — the wordfreq join, normalised into a distribution over the
  dictionary. **[measured]** for the 13.8% of entries with an observed
  frequency.
* `P_ngram` — a character model trained on the dictionary's 297,747 Romanized
  spellings. **[measured]**, in the sense that every count comes from the data.
* The per-tier weight given to entries with *no* observed frequency: each tier's
  **measured** frequency coverage. A tier where 44% of entries were found in a
  general Hindi frequency table holds words; a tier where 1.8% were found holds
  mostly corpus artefacts, and the ratio says so.

**Not learned, because this repository holds no password corpus**

* `P(k)`, the number of segments.
* `P(C)`, which category a segment is.
* `P(n)` for digit and symbol run lengths.

Those are the Weir-style *structure* probabilities, and learning them requires
passwords. There are none here, and the synthetic benchmark corpus must not be
used: fitting the structure prior to the generator and then evaluating on the
generator's output would measure the generator. So they are explicit priors —
**maximum entropy subject to a stated constraint** — and the milestone reports
how much the conclusion moves when they change, rather than claiming they are
right. See ``docs/password_strength_design.md`` §14.4.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from math import comb
from typing import Any

from indicpass.password.dictionary import IndicDict, IndicDictEntry
from indicpass.password.mangling import case_variations
from indicpass.password.pcfg.ngram import CharacterNgram

__all__ = [
    "CATEGORY_DIGITS",
    "CATEGORY_SYMBOLS",
    "CATEGORY_UNKNOWN",
    "CATEGORY_WORD",
    "CATEGORY_YEAR",
    "PCFG_CATEGORIES",
    "CaseModel",
    "GrammarSettings",
    "PcfgGrammar",
    "WordDistribution",
]

CATEGORY_WORD = "word"
CATEGORY_UNKNOWN = "unknown"
CATEGORY_DIGITS = "digits"
CATEGORY_YEAR = "year"
CATEGORY_SYMBOLS = "symbols"

#: Fixed order. It fixes the category prior's ordering and the sampler's
#: draw, so adding a category at the end leaves existing artefacts readable.
PCFG_CATEGORIES: tuple[str, ...] = (
    CATEGORY_WORD,
    CATEGORY_UNKNOWN,
    CATEGORY_DIGITS,
    CATEGORY_YEAR,
    CATEGORY_SYMBOLS,
)

_NEGATIVE_INFINITY = -math.inf


@dataclass(frozen=True)
class GrammarSettings:
    """Every knob the grammar has, all of them from ``config/password.yaml``.

    Each field says below whether it is learned from data or asserted. Nothing
    in this module hardcodes a probability.
    """

    #: Character-model order. Swept; see the sensitivity report.
    ngram_order: int
    #: Restrict n-gram training to these provenance tiers. Empty means all.
    ngram_tiers: tuple[str, ...]

    #: **[assumption]** P(k segments) is geometric with this continuation
    #: probability, truncated at ``max_segments`` and renormalised. Geometric is
    #: the maximum-entropy distribution on the positive integers once a mean is
    #: fixed, which is the least that can be assumed while still assuming
    #: anything.
    segment_continuation: float
    max_segments: int

    #: **[assumption]** P(category). Empty means uniform -- maximum entropy,
    #: the only defensible default with no password corpus to fit.
    category_prior: Mapping[str, float]

    #: **[assumption]** Truncated-geometric length priors for digit and symbol
    #: runs, for the same reason as ``segment_continuation``.
    digit_length_decay: float
    symbol_length_decay: float
    max_run_length: int

    #: Terminal alphabets, shared with the Milestone 2 estimator so the two
    #: differ in their probability model and not in what a digit is.
    digits_per_position: int
    symbol_alphabet_size: int
    year_range: tuple[int, int]

    #: How entries with no observed frequency are priced. ``tier_coverage``
    #: weights each tier by its measured frequency coverage; ``uniform`` gives
    #: every tier the same weight; ``excluded`` drops them from the word
    #: category entirely, leaving the n-gram to explain them.
    unranked_policy: str

    @classmethod
    def from_config(
        cls, pcfg: Mapping[str, Any], scoring: Mapping[str, Any]
    ) -> GrammarSettings:
        grammar = dict(pcfg.get("grammar") or {})
        low, high = tuple(scoring.get("year_range", (1900, 2035)))
        return cls(
            ngram_order=int(grammar.get("ngram_order", 4)),
            ngram_tiers=tuple(str(name) for name in (grammar.get("ngram_tiers") or ())),
            segment_continuation=float(grammar.get("segment_continuation", 0.5)),
            max_segments=int(grammar.get("max_segments", 8)),
            category_prior={
                str(name): float(value)
                for name, value in (grammar.get("category_prior") or {}).items()
            },
            digit_length_decay=float(grammar.get("digit_length_decay", 0.5)),
            symbol_length_decay=float(grammar.get("symbol_length_decay", 0.35)),
            max_run_length=int(grammar.get("max_run_length", 16)),
            digits_per_position=int(scoring.get("digits_per_position", 10)),
            symbol_alphabet_size=int(scoring.get("symbol_alphabet_size", 33)),
            year_range=(int(low), int(high)),
            unranked_policy=str(grammar.get("unranked_policy", "tier_coverage")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ngram_order": self.ngram_order,
            "ngram_tiers": list(self.ngram_tiers),
            "segment_continuation": self.segment_continuation,
            "max_segments": self.max_segments,
            "category_prior": dict(self.category_prior),
            "digit_length_decay": self.digit_length_decay,
            "symbol_length_decay": self.symbol_length_decay,
            "max_run_length": self.max_run_length,
            "digits_per_position": self.digits_per_position,
            "symbol_alphabet_size": self.symbol_alphabet_size,
            "year_range": list(self.year_range),
            "unranked_policy": self.unranked_policy,
        }


# -- case ------------------------------------------------------------------


@lru_cache(maxsize=64)
def _case_table(length: int) -> tuple[tuple[int, float], ...]:
    """``(surfaces, variations)`` buckets for a word with *length* cased letters.

    Enumerates the ``2**length`` case surfaces combinatorially rather than one
    by one, grouping them by the number of variations
    :func:`indicpass.password.mangling.case_variations` assigns. The groups are
    what makes the case model both normalisable and samplable.
    """
    if length <= 0:
        return ((1, 1.0),)
    if length == 1:
        # The single upper-case surface is "uppercase", not "capitalized".
        return ((1, 1.0), (1, 2.0))

    buckets: list[tuple[int, float]] = [
        (1, 1.0),  # all lower
        (1, 2.0),  # ALL UPPER
        (2, 2.0),  # Capitalized and finaL
    ]
    for uppers in range(1, length):
        surfaces = comb(length, uppers) - (2 if uppers == 1 else 0)
        if surfaces <= 0:
            continue
        variations = float(
            sum(comb(length, i) for i in range(1, min(uppers, length - uppers) + 1)) or 1
        )
        buckets.append((surfaces, variations))
    return tuple(buckets)


class CaseModel:
    """``P(surface | word)`` over every case pattern of a word.

    The *relative* weighting is zxcvbn's, and is inherited on purpose: Milestone
    2 held the case rule identical across the two estimators so that a
    difference between them would be attributable to the lexicon rather than to
    capital letters, and abandoning that here would break the comparison this
    milestone extends.

    What this module adds is the **normalisation**. Milestone 2 used the
    variation count as a cost multiplier, which is not a probability -- an
    all-lower-case word got a multiplier of 1, so the "distribution" summed to
    well over 1. Dividing by ``Z(L) = sum over all 2^L surfaces of 1/U`` turns
    the same weighting into a proper conditional distribution, which is exactly
    the step a PCFG requires and the previous estimator did not.

    **[heuristic]** The weighting itself. **[measured]** nothing here: no case
    statistics from real passwords exist in this repository.
    """

    @staticmethod
    @lru_cache(maxsize=64)
    def log10_normaliser(length: int) -> float:
        total = sum(surfaces / variations for surfaces, variations in _case_table(length))
        return math.log10(total) if total > 0 else 0.0

    @classmethod
    def log10_probability(cls, surface: str) -> float:
        """``log10 P(surface | the word it is a casing of)``."""
        cased = sum(1 for char in surface if char.isalpha())
        variations = _variations(surface)
        return -math.log10(variations) - cls.log10_normaliser(cased)

    @classmethod
    def sample_log10(cls, rng: random.Random, length: int) -> float:
        """Draw a case surface for a word of *length* letters; return its log-probability."""
        table = _case_table(length)
        normaliser = cls.log10_normaliser(length)
        weights = [surfaces / variations for surfaces, variations in table]
        total = sum(weights)
        roll = rng.random() * total
        cumulative = 0.0
        for (_, variations), weight in zip(table, weights, strict=True):
            cumulative += weight
            if roll < cumulative:
                return -math.log10(variations) - normaliser
        return -math.log10(table[-1][1]) - normaliser


def _variations(surface: str) -> float:
    """``case_variations`` for a surface, as a float, never below 1."""
    return float(max(case_variations(surface), 1))


# -- the word terminal -----------------------------------------------------


@dataclass(frozen=True)
class WordDistribution:
    """``P(entry)`` over an :class:`~indicpass.password.dictionary.IndicDict`.

    Two populations, kept apart exactly as Milestone 2 kept the two pricing
    policies apart:

    ``observed``
        The entry's native form was found in the frequency table. Its unnormalised
        weight is ``10 ** (zipf - 9)``, the provider's own definition of
        occurrences per token. **[measured]**

    ``unobserved``
        No frequency. Its weight is the **smallest observed weight** -- a word
        absent from a 26,653-word general frequency list is at most as common as
        the rarest word on it, which is a bound the data supports rather than a
        number invented for it -- scaled by the entry's tier weight.
        **[heuristic]**: the bound is derived, the tier scaling is a policy.

    The tier weight is the tier's add-one-smoothed frequency coverage,
    ``(ranked + 1) / (size + 1)``. That ratio is measured, and it says what the
    provenance tiers were always claiming: 44% of ``human_romanized`` entries
    turn up in a Hindi frequency table against 1.8% of ``mined`` ones.
    """

    log10_normaliser: float
    log10_min_observed: float
    tier_weights: Mapping[str, float]
    observed_entries: int
    unobserved_entries: int
    observed_mass: float
    unobserved_mass: float
    policy: str

    @classmethod
    def train(cls, dictionary: IndicDict, *, policy: str = "tier_coverage") -> WordDistribution:
        frequencies = [
            entry.frequency for entry in dictionary.entries.values() if entry.frequency is not None
        ]
        # A dictionary with no frequency at all still has to produce a
        # distribution -- the fixtures and the `no_frequency` ablation arm both
        # need one -- so fall back to a flat weight and say so in `policy`.
        if frequencies:
            weights = [10.0 ** (value - 9.0) for value in frequencies]
            minimum = min(weights)
        else:
            weights = []
            minimum = 1.0

        tier_weights = _tier_weights(dictionary, policy)

        observed_mass = math.fsum(weights)
        unobserved_mass = 0.0
        unobserved = 0
        for entry in dictionary.entries.values():
            if entry.frequency is not None:
                continue
            unobserved += 1
            unobserved_mass += minimum * tier_weights.get(entry.tier, 0.0)

        total = observed_mass + unobserved_mass
        return cls(
            log10_normaliser=math.log10(total) if total > 0 else 0.0,
            log10_min_observed=math.log10(minimum) if minimum > 0 else 0.0,
            tier_weights=tier_weights,
            observed_entries=len(weights),
            unobserved_entries=unobserved,
            observed_mass=observed_mass,
            unobserved_mass=unobserved_mass,
            policy=policy,
        )

    def log10_probability(self, entry: IndicDictEntry) -> float:
        """``log10 P(entry)``. ``-inf`` when the policy excludes it."""
        if entry.frequency is not None:
            return (entry.frequency - 9.0) - self.log10_normaliser
        weight = self.tier_weights.get(entry.tier, 0.0)
        if weight <= 0.0:
            return _NEGATIVE_INFINITY
        return self.log10_min_observed + math.log10(weight) - self.log10_normaliser

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "observed_entries": self.observed_entries,
            "unobserved_entries": self.unobserved_entries,
            "observed_mass": self.observed_mass,
            "unobserved_mass": self.unobserved_mass,
            "log10_normaliser": round(self.log10_normaliser, 6),
            "log10_min_observed": round(self.log10_min_observed, 6),
            "tier_weights": {name: round(value, 6) for name, value in self.tier_weights.items()},
            "note": (
                "Unobserved entries are bounded by the smallest OBSERVED probability and "
                "scaled by their tier's measured frequency coverage. No frequency is "
                "invented for them, and frequency stays null on the entry itself."
            ),
        }


def _tier_weights(dictionary: IndicDict, policy: str) -> dict[str, float]:
    if policy == "excluded":
        return dict.fromkeys(dictionary.tiers, 0.0)
    if policy == "uniform":
        return dict.fromkeys(dictionary.tiers, 1.0)
    if policy != "tier_coverage":
        raise ValueError(
            f"Unknown unranked_policy {policy!r}. "
            "Known: tier_coverage, uniform, excluded."
        )
    # Add-one smoothed so a tier that happens to have no ranked entry -- the
    # test fixtures, the no_frequency ablation -- gets a small weight rather
    # than vanishing from the grammar entirely.
    return {
        name: (tier.ranked_size + 1) / (tier.size + 1)
        for name, tier in dictionary.tiers.items()
    }


# -- the grammar -----------------------------------------------------------


class PcfgGrammar:
    """Structure prior plus terminal distributions, trained from one dictionary."""

    def __init__(
        self,
        *,
        dictionary: IndicDict,
        settings: GrammarSettings,
        words: WordDistribution,
        ngram: CharacterNgram,
    ) -> None:
        self.dictionary = dictionary
        self.settings = settings
        self.words = words
        self.ngram = ngram

        self._log10_segments = _geometric_log10(
            settings.segment_continuation, settings.max_segments
        )
        self._log10_category = _category_log10(settings.category_prior)
        self._log10_digit_length = _geometric_log10(
            settings.digit_length_decay, settings.max_run_length
        )
        self._log10_symbol_length = _geometric_log10(
            settings.symbol_length_decay, settings.max_run_length
        )
        low, high = settings.year_range
        self._log10_year = -math.log10(max(high - low + 1, 1))
        self._log10_digit = -math.log10(max(settings.digits_per_position, 1))
        self._log10_symbol = -math.log10(max(settings.symbol_alphabet_size, 1))

        self._sampler: _WordSampler | None = None

    # -- construction ------------------------------------------------------

    @classmethod
    def train(cls, dictionary: IndicDict, settings: GrammarSettings) -> PcfgGrammar:
        """Fit every learnable part of the grammar to *dictionary*.

        Deterministic: the counts depend on the set of entries, not on their
        order, so two runs over the same dictionary give identical probabilities.
        """
        wanted = set(settings.ngram_tiers)
        training = [
            key
            for key, entry in dictionary.entries.items()
            if not wanted or entry.tier in wanted
        ]
        training.sort()
        return cls(
            dictionary=dictionary,
            settings=settings,
            words=WordDistribution.train(dictionary, policy=settings.unranked_policy),
            ngram=CharacterNgram.train(training, order=settings.ngram_order),
        )

    # -- the structure prior ----------------------------------------------

    def log10_structure(self, segments: int) -> float:
        """``log10 P(k)``. ``-inf`` past ``max_segments``."""
        if 1 <= segments <= len(self._log10_segments):
            return self._log10_segments[segments - 1]
        return _NEGATIVE_INFINITY

    def log10_category(self, category: str) -> float:
        return self._log10_category.get(category, _NEGATIVE_INFINITY)

    # -- terminals ---------------------------------------------------------

    def log10_word(self, token: str) -> tuple[float, IndicDictEntry | None]:
        """``log10 P(token | word)``: the entry, then its casing."""
        entry = self.dictionary.get(token.lower())
        if entry is None:
            return _NEGATIVE_INFINITY, None
        base = self.words.log10_probability(entry)
        if base == _NEGATIVE_INFINITY:
            return _NEGATIVE_INFINITY, entry
        return base + CaseModel.log10_probability(token), entry

    def log10_unknown(self, token: str) -> float:
        """``log10 P(token | unknown)``: the character model, then its casing."""
        if len(token) > self.settings.max_run_length:
            return _NEGATIVE_INFINITY
        base = self.ngram.log10_probability(token.lower())
        if base == _NEGATIVE_INFINITY:
            return _NEGATIVE_INFINITY
        return base + CaseModel.log10_probability(token)

    def log10_digits(self, token: str) -> float:
        length = len(token)
        if not 1 <= length <= len(self._log10_digit_length):
            return _NEGATIVE_INFINITY
        return self._log10_digit_length[length - 1] + length * self._log10_digit

    def log10_year(self) -> float:
        return self._log10_year

    def log10_symbols(self, token: str) -> float:
        length = len(token)
        if not 1 <= length <= len(self._log10_symbol_length):
            return _NEGATIVE_INFINITY
        return self._log10_symbol_length[length - 1] + length * self._log10_symbol

    # -- sampling ----------------------------------------------------------

    def sample_log10_probability(self, rng: random.Random) -> tuple[float, int]:
        """Draw one derivation; return ``(log10 P, segment count)``.

        **The derived string is never assembled.** Only its probability is
        needed to build the guess curve, and a file of sampled passwords would
        be a cracking wordlist -- so the sampler returns numbers and the pieces
        it drew are discarded inside this function. That is a property of the
        design, not a policy applied afterwards.
        """
        segments = _draw(rng, self._log10_segments) + 1
        total = self._log10_segments[segments - 1]

        for _ in range(segments):
            category = PCFG_CATEGORIES[_draw_mapping(rng, self._log10_category)]
            total += self._log10_category[category]
            total += self._sample_terminal(rng, category)
        return total, segments

    def _sample_terminal(self, rng: random.Random, category: str) -> float:
        if category == CATEGORY_WORD:
            if self._sampler is None:
                self._sampler = _WordSampler(self.dictionary, self.words)
            log10_word, length = self._sampler.draw(rng)
            return log10_word + CaseModel.sample_log10(rng, length)
        if category == CATEGORY_UNKNOWN:
            spelling = self.ngram.sample(rng, max_length=self.settings.max_run_length)
            if not spelling:
                return _NEGATIVE_INFINITY
            return self.ngram.log10_probability(spelling) + CaseModel.sample_log10(
                rng, len(spelling)
            )
        if category == CATEGORY_DIGITS:
            length = _draw(rng, self._log10_digit_length) + 1
            return self._log10_digit_length[length - 1] + length * self._log10_digit
        if category == CATEGORY_YEAR:
            return self._log10_year
        length = _draw(rng, self._log10_symbol_length) + 1
        return self._log10_symbol_length[length - 1] + length * self._log10_symbol

    # -- provenance --------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "categories": list(PCFG_CATEGORIES),
            "settings": self.settings.to_dict(),
            "word_distribution": self.words.to_dict(),
            "ngram": self.ngram.describe(),
            "structure_prior": {
                "form": "truncated geometric over segment count, renormalised",
                "log10_probability": [round(v, 6) for v in self._log10_segments],
                "status": "assumption -- no password corpus exists in this repository",
            },
            "category_prior": {
                name: round(value, 6) for name, value in self._log10_category.items()
            },
        }

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<PcfgGrammar entries={len(self.dictionary):,} "
            f"order={self.settings.ngram_order} max_segments={self.settings.max_segments}>"
        )


class _WordSampler:
    """Cumulative weights over the dictionary, built once and only when sampling.

    Holds the spellings' *lengths*, never the spellings: the sampler needs a
    length to draw a case pattern and nothing else, so there is no point at
    which a drawn word exists as a string.
    """

    def __init__(self, dictionary: IndicDict, words: WordDistribution) -> None:
        self._log10: list[float] = []
        self._lengths: list[int] = []
        cumulative: list[float] = []
        running = 0.0
        for key in sorted(dictionary.entries):
            entry = dictionary.entries[key]
            log10 = words.log10_probability(entry)
            if log10 == _NEGATIVE_INFINITY:
                continue
            running += 10.0**log10
            self._log10.append(log10)
            self._lengths.append(len(key))
            cumulative.append(running)
        self._cumulative = cumulative
        self._total = running

    def draw(self, rng: random.Random) -> tuple[float, int]:
        if not self._cumulative:
            return _NEGATIVE_INFINITY, 0
        index = bisect_left(self._cumulative, rng.random() * self._total)
        index = min(index, len(self._cumulative) - 1)
        return self._log10[index], self._lengths[index]


# -- priors ----------------------------------------------------------------


def _geometric_log10(decay: float, limit: int) -> tuple[float, ...]:
    """A truncated, renormalised geometric distribution over ``1..limit``.

    Truncating and renormalising rather than letting the tail run keeps the
    prior a genuine distribution over the range the parser can actually reach,
    so probabilities coming out of the grammar sum to one over its own support.
    """
    if not 0.0 < decay < 1.0:
        raise ValueError(f"A geometric decay must be in (0, 1); got {decay}.")
    if limit < 1:
        raise ValueError(f"A geometric prior needs at least one outcome; got {limit}.")
    weights = [decay**index for index in range(limit)]
    total = math.fsum(weights)
    return tuple(math.log10(weight / total) for weight in weights)


def _category_log10(prior: Mapping[str, float]) -> dict[str, float]:
    """The category prior, defaulting to uniform.

    Uniform is not a placeholder: with no password corpus, maximum entropy over
    the categories is the only choice that does not assert something unmeasured.
    A configured prior is renormalised, so a partially specified one cannot
    silently sum to less than 1.
    """
    if not prior:
        return dict.fromkeys(PCFG_CATEGORIES, -math.log10(len(PCFG_CATEGORIES)))

    unknown = sorted(set(prior) - set(PCFG_CATEGORIES))
    if unknown:
        raise ValueError(
            f"category_prior names unknown categories {unknown}. "
            f"Known: {list(PCFG_CATEGORIES)}."
        )
    weights = {name: float(prior.get(name, 0.0)) for name in PCFG_CATEGORIES}
    total = math.fsum(weights.values())
    if total <= 0:
        raise ValueError("category_prior must give some category positive weight.")
    return {
        name: (math.log10(weight / total) if weight > 0 else _NEGATIVE_INFINITY)
        for name, weight in weights.items()
    }


def _draw(rng: random.Random, log10_probabilities: Sequence[float]) -> int:
    roll = rng.random()
    cumulative = 0.0
    for index, value in enumerate(log10_probabilities):
        cumulative += 10.0**value
        if roll < cumulative:
            return index
    return len(log10_probabilities) - 1


def _draw_mapping(rng: random.Random, log10_probabilities: Mapping[str, float]) -> int:
    return _draw(rng, [log10_probabilities[name] for name in PCFG_CATEGORIES])


def iter_categories() -> Iterator[str]:  # pragma: no cover - trivial
    yield from PCFG_CATEGORIES
