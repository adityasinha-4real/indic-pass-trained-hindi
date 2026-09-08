"""Milestone 5: an attacker that can reach a spelling IndicDict has never seen.

Milestone 4 measured an observed rank for 528 of the 1,400 benchmark targets.
The other 872 were unreachable for one reason: that attack is a **wordlist**
crossed with suffix rules, and a password built from a spelling absent from the
wordlist is not in its universe at all. Milestone 3's central claim is about
exactly those 872 -- that a character model prices a Hindi-shaped spelling the
dictionary never saw below a random string of the same length -- and Milestone 4
had no way to test it, because it could not reach a single one of them.

This module is the attacker that can. It replaces the wordlist with a
**character model**, so *every* lower-case letter string within the bounds below
is in its universe, whether or not IndicDict contains it. The rank is still an
observation rather than an estimate: the enumeration is never run, the universe
is counted by dynamic programming, and a target's position is recovered by
inverting the ordering arithmetic.

The candidate universe
----------------------
A candidate is exactly::

    candidate = case(stem) + suffix

with three search dimensions, each finite and each bounded by a setting that is
written into every report:

``stem``
    Any string over the 26 ASCII lower-case letters with length in
    ``[min_stem_length, max_stem_length]``. The default upper bound of 16 is
    ``dictionary.max_token_length`` from ``config/password.yaml`` -- the same
    bound the dictionary build uses for what counts as password material -- and
    it covers 1,395 of the 1,400 benchmark targets' letter bodies. **This is the
    dimension that makes the attack OOV-capable**: the stem is generated, not
    looked up, so a spelling missing from IndicDict is reachable on exactly the
    same terms as one that is in it.

``case``
    ``lower`` | ``capitalized`` | ``upper``, applied to the whole stem. A
    password with a capital anywhere else -- ``meraNamaste`` -- is not in the
    universe and is reported unreachable rather than approximated.

``suffix``
    One of the families in :func:`build_families`: nothing, one to
    ``max_digits`` digits, a year in ``year_range``, one symbol from
    ``symbols``, or a symbol followed by up to ``max_symbol_digits`` digits.
    Each family is a set of strings of fixed width with a fixed enumeration
    order, so it has a size and an index and can be inverted with one test.

There is no combinator rule and none is needed: a two-word body such as
``merapyaar`` is just a nine-character stem, and the character model prices it.
That is the whole structural difference from Milestone 4.

The ordering
------------
Candidates are enumerated in ascending **level**, an integer quantised cost::

    level(candidate) = shape_level(case, family) + stem_level(stem)

    stem_level(s) = Σ_i q(-log10 P(s_i | context_i)) + q(-log10 P(END | context))
    shape_level   = q(log10 3) + q(log10 F) + q(log10 |family|)
    q(x)          = floor(x / precision + 0.5)

``P`` is the character model of :class:`CharacterModel`; ``F`` is the number of
suffix families. The shape term is the cost of choosing a case (uniform over
three), choosing a family (uniform over ``F``) and then choosing a member of it
(uniform within the family). Both uniforms are **assumptions**, stated here and
in the report: there is no password corpus in this project to learn a structure
prior from, so maximum entropy is the only choice that asserts nothing
unmeasured -- the same move, for the same reason, that the PCFG's structure
prior makes.

Quantisation is what makes the ordering countable. Levels are integers, so the
number of candidates at each level can be computed by a dynamic programme over
``(remaining length, context, remaining level)`` and the enumeration becomes a
sum over a few hundred integers instead of a walk over 10^16 strings. It is the
level-based scheme published cracking tools use for exactly this reason. Note
that a sum of quantised costs is not the quantised sum: the level *defines* this
attack's order, and it is not claimed to be a probability.

Ties are broken by a total order, so every candidate has one position:

1. ascending level;
2. within a level, by shape index -- shapes sorted by
   ``(shape_level, family index, case index)``, so the cheapest family runs
   first and ``lower`` runs before ``capitalized`` before ``upper``;
3. within a shape, by stem: **length ascending, then lexicographic** over
   ``a..z``;
4. within a stem, by the suffix's index in its family.

Bounds, and what "unreachable" means
------------------------------------
The budget is ``max_candidates``, and it is **inherited from Milestone 4**:
10^16 candidates, the same figure that attack was given. Levels are added
cheapest-first until the next one would break it, and the last affordable level
becomes ``max_level``. Spending the same as Milestone 4 is what makes the two
coverage figures comparable -- the difference between them is then a statement
about the candidate model, not about how long the attacker was allowed to run.

``level_ceiling`` is a structural bound rather than a policy one: it is the
height of the counting table, and the build asserts the budget binds below it,
so a universe is never silently limited by an implementation detail.

A candidate whose level exceeds ``max_level`` is outside the universe, and so is
a stem longer than ``max_stem_length`` or a password no ``(case, suffix)`` shape
can decompose. Every one of those is reported **unreachable with a named
reason** and given **no rank** -- never the universe size, never a censored
bound, never a substituted value. The universe size is a property of the attack;
it is never a target's rank.

Independence from the estimators
--------------------------------
This module imports **nothing but the standard library**. It does not import the
meter, the scoring model, the matcher, the baseline, the PCFG, or even the
dictionary: :func:`dictionary_stem_corpus` takes an ``IndicDict`` and reads one
attribute off its entries, so the type is a duck rather than a dependency.
Nothing here reads a guess number, and the ordering is a function of the
character model and the bounds alone. ``tests/test_character_attack.py``
enforces this the way Milestone 4's tests do: by parsing the import set, by
denylisting the estimator modules, and by ranking a corpus with all three
estimators replaced by objects that raise on contact.

That is independence in the mechanical sense. The evidential sense is weaker and
saying so is the point of the arms:

    **Under ``model="indicdict"`` the character model is trained on the same
    Romanized spellings the PCFG's own n-gram is trained on.** Different order,
    different smoothing, different implementation -- but the same evidence. A
    finding that the PCFG predicts this attack well under that arm is partly a
    statement about shared training data, not only about the estimator.

``model="uniform"`` removes the shared evidence completely: every character costs
the same, the ordering collapses to length-then-lexicographic, and no estimator
has any informational advantage. It is the null arm, and a conclusion that holds
under both is a conclusion about the estimators.

What this attack does not represent
-----------------------------------
One attacker, not the space of them. No leaked-password list, no leet
substitution, no keyboard walks, no targeted personal data, no digits or symbols
anywhere but the tail, and no capital anywhere but the first letter. Its reach
over Romanized Hindi comes from a character model trained on a transliteration
dictionary, which is a hypothesis about what such an attacker could build, not a
measurement of one that exists.
"""

from __future__ import annotations

import hashlib
import math
import random
import string
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ATTACK_SYMBOLS",
    "ATTACK_VERSION",
    "CASES",
    "END_OF_STEM",
    "MODEL_KINDS",
    "STEM_ALPHABET",
    "UNREACHABLE",
    "UNREACHABLE_REASONS",
    "CharacterAttack",
    "CharacterAttackRank",
    "CharacterAttackSettings",
    "CharacterModel",
    "Shape",
    "StemCounter",
    "SuffixFamily",
    "build_families",
    "build_shapes",
    "coverage",
    "dictionary_stem_corpus",
]

#: Bump when the universe definition, the ordering or the rank arithmetic
#: changes. Every report carries it, so a rank can never be silently compared
#: against one produced by a different attack.
ATTACK_VERSION = "1.0"

#: The stem alphabet. Twenty-six ASCII lower-case letters and nothing else:
#: IndicDict's keys are filtered to exactly this set at build time, so it is the
#: complete symbol set the character model can have learned.
STEM_ALPHABET = string.ascii_lowercase

#: Emitted after a stem's last character. Being part of the model's alphabet is
#: what makes it a distribution over *strings* -- the cost of stopping is
#: learned, so the attack needs no separate length prior.
END_OF_STEM = "\x00"

#: Left padding. Outside the alphabet, so it appears only in a context and can
#: never be emitted.
_PAD = "\x01"

#: The model's symbol set, in the order every level tuple is indexed by.
_SYMBOLS: tuple[str, ...] = (*STEM_ALPHABET, END_OF_STEM)
_SYMBOL_INDEX: Mapping[str, int] = {symbol: index for index, symbol in enumerate(_SYMBOLS)}
_END_INDEX = _SYMBOL_INDEX[END_OF_STEM]

#: Case transformations, in enumeration order. ``lower`` first for the same
#: reason Milestone 4 runs the straight wordlist first: a plain spelling must
#: never be more expensive than a decorated one.
CASES: tuple[str, ...] = ("lower", "capitalized", "upper")

#: Where the character model's statistics come from. ``indicdict`` shares its
#: training evidence with the PCFG's n-gram; ``uniform`` shares none and is the
#: null arm. See the module docstring.
MODEL_KINDS: tuple[str, ...] = ("indicdict", "uniform")

#: Symbols the attacker appends. A strict superset of the ten the benchmark
#: generator uses, which is the safe direction: a superset can only push a
#: target further down the enumeration, never closer, so coverage cannot be an
#: artefact of a matched symbol list.
ATTACK_SYMBOLS = "!@#$%^&*()-_.+"

#: Every reason a target can be outside the universe. Written down so a report
#: cannot invent one, and so that "unreachable" is always a named fact rather
#: than an absence.
UNREACHABLE_REASONS: tuple[str, ...] = (
    "empty",
    "no_shape",  # no (case, suffix) pair decomposes it into a lower-case stem
    "stem_too_short",
    "stem_too_long",
    "level_above_budget",
)

#: Suffix families in their fixed index order. Used to break ties between shapes
#: of equal level, and to keep the enumeration stable when a bound changes.
_FAMILY_ORDER: tuple[str, ...] = (
    "",
    "digits1",
    "digits2",
    "digits3",
    "digits4",
    "digits5",
    "year",
    "symbol",
    "symbol+digits1",
    "symbol+digits2",
    "symbol+digits3",
)


def quantise(value: float, precision: float) -> int:
    """``value / precision``, rounded half-up to an integer.

    Half-up rather than :func:`round`, which is half-to-even: a cost that lands
    exactly on a half-quantum is rare but it must land the same way on every
    machine, and the banker's rule is the one people are surprised by.
    """
    return math.floor(value / precision + 0.5)


# -- the training corpus ----------------------------------------------------


def dictionary_stem_corpus(dictionary: Any) -> list[str]:
    """The lower-case Romanized spellings an ``IndicDict`` holds.

    Separated from :meth:`CharacterModel.train` so that everything below this
    line operates on plain strings and the attack itself depends on nothing but
    the standard library. Only the spellings are read: no frequency, no rank, no
    tier, and nothing an estimator prices a word with.
    """
    return [
        entry.romanized_form
        for entry in dictionary.entries.values()
        if entry.romanized_form == entry.romanized_form.lower()
    ]


# -- the character model ----------------------------------------------------


@dataclass(frozen=True)
class CharacterModel:
    """Integer per-character costs, and where they came from.

    The model is stored as its **levels**, not its probabilities: the attack is
    defined by the integers, and keeping the floats around would invite a later
    change to re-derive them differently and silently move every rank.

    ``levels`` maps a context of exactly ``order - 1`` symbols to a 27-tuple of
    levels indexed by :data:`_SYMBOL_INDEX`. Every context reachable in a padded
    stem is present, so a lookup never has to decide what to do about a missing
    one.
    """

    order: int
    smoothing: float
    precision: float
    kind: str
    levels: Mapping[str, tuple[int, ...]]
    training_words: int
    training_characters: int
    training_share: float
    training_seed: int
    source: str

    @classmethod
    def train(
        cls,
        words: Iterable[str],
        *,
        order: int = 3,
        smoothing: float = 1.0,
        precision: float = 0.25,
        kind: str = "indicdict",
        share: float = 1.0,
        seed: int = 42,
        source: str = "IndicDict romanized keys",
    ) -> CharacterModel:
        """Fit the model, then freeze it into integer levels.

        ``P(c | h) = (N(h,c) + alpha) / (N(h) + alpha * 27)`` evaluated at the
        **longest suffix of h that was observed at all**, backing off one
        character at a time and falling to uniform if even the unigram is empty.

        Additive smoothing with ``alpha = 1`` rather than the PCFG's Witten-Bell
        interpolation, and it is a deliberate difference rather than an
        oversight. Two reasons. It is a different estimator fitted to the same
        counts, so the attack is not a re-implementation of the thing it is
        scoring -- and Laplace is the conventional parameter-free choice, so
        ``alpha`` is a stated constant rather than a tuned one. The report
        carries a sensitivity arm over ``alpha`` and over ``order`` anyway,
        because both are assumptions and neither is allowed to be load-bearing
        without a measurement.

        ``share < 1`` trains on a seeded subsample. That is the hold-out arm:
        it answers whether the attack's reach depends on the *particular*
        spellings IndicDict happens to contain or on the shape of the language.
        """
        if order < 1:
            raise ValueError(f"A character model needs order >= 1, got {order}.")
        if smoothing <= 0.0:
            raise ValueError(f"Additive smoothing must be positive, got {smoothing}.")
        if precision <= 0.0:
            raise ValueError(f"The level quantum must be positive, got {precision}.")
        if kind not in MODEL_KINDS:
            raise ValueError(f"Unknown model kind {kind!r}. Known: {list(MODEL_KINDS)}.")
        if not 0.0 < share <= 1.0:
            raise ValueError(f"training_share must be in (0, 1], got {share}.")

        contexts = _reachable_contexts(order)

        if kind == "uniform":
            # No character statistics at all: every symbol costs the same, so
            # the ordering collapses to length-then-lexicographic. The null arm.
            flat = quantise(math.log10(len(_SYMBOLS)), precision)
            uniform = tuple([flat] * len(_SYMBOLS))
            return cls(
                order=order,
                smoothing=smoothing,
                precision=precision,
                kind=kind,
                levels={context: uniform for context in contexts},
                training_words=0,
                training_characters=0,
                training_share=share,
                training_seed=seed,
                source="uniform (no training data)",
            )

        selected = sorted({word for word in words if word})
        if share < 1.0:
            keep = max(1, int(len(selected) * share))
            selected = sorted(random.Random(f"charmodel:{seed}:{share}").sample(selected, keep))

        counts: dict[str, list[int]] = {}
        seen_characters = 0
        pad = _PAD * (order - 1)
        for word in selected:
            if any(character not in _SYMBOL_INDEX for character in word):
                continue
            seen_characters += len(word) + 1
            padded = pad + word + END_OF_STEM
            for position in range(order - 1, len(padded)):
                emitted = _SYMBOL_INDEX[padded[position]]
                for back in range(order):
                    context = padded[position - back : position]
                    row = counts.get(context)
                    if row is None:
                        row = counts[context] = [0] * len(_SYMBOLS)
                    row[emitted] += 1

        totals = {context: sum(row) for context, row in counts.items()}
        levels = {
            context: _context_levels(context, counts, totals, smoothing, precision)
            for context in contexts
        }
        return cls(
            order=order,
            smoothing=smoothing,
            precision=precision,
            kind=kind,
            levels=levels,
            training_words=len(selected),
            training_characters=seen_characters,
            training_share=share,
            training_seed=seed,
            source=source,
        )

    def fingerprint(self) -> str:
        """SHA-256 over every level. Two runs must agree on this or on nothing."""
        digest = hashlib.sha256()
        digest.update(
            f"{ATTACK_VERSION}\n{self.kind}\n{self.order}\n"
            f"{self.smoothing!r}\n{self.precision!r}\n".encode()
        )
        for context in sorted(self.levels):
            digest.update(context.encode("utf-8"))
            digest.update(b"\t")
            digest.update(",".join(str(value) for value in self.levels[context]).encode())
            digest.update(b"\n")
        return f"sha256:{digest.hexdigest()}"

    def describe(self) -> dict[str, Any]:
        """Publishable provenance. Holds no spelling from the training set."""
        return {
            "kind": self.kind,
            "order": self.order,
            "smoothing": self.smoothing,
            "precision": self.precision,
            "contexts": len(self.levels),
            "alphabet": len(_SYMBOLS),
            "training_words": self.training_words,
            "training_characters": self.training_characters,
            "training_share": self.training_share,
            "training_seed": self.training_seed,
            "source": self.source,
            "estimator": "additive (Laplace) smoothing, backoff to the longest seen context",
            "fingerprint": self.fingerprint(),
            "shares_evidence_with_pcfg_ngram": self.kind == "indicdict",
        }


def _reachable_contexts(order: int) -> list[str]:
    """Every context of length ``order - 1`` a padded stem can produce.

    Enumerated rather than collected from the training data: the dynamic
    programme walks contexts the corpus may never have shown, and a missing
    entry there would be a silent zero instead of a smoothed cost.
    """
    width = order - 1
    contexts = [""]
    for _ in range(width):
        contexts = [context + character for context in contexts for character in STEM_ALPHABET]
    # ... plus the padded prefixes seen at the left edge of a stem.
    for pad_width in range(1, width + 1):
        head = _PAD * pad_width
        tails = [""]
        for _ in range(width - pad_width):
            tails = [tail + character for tail in tails for character in STEM_ALPHABET]
        contexts.extend(head + tail for tail in tails)
    return sorted(set(contexts))


def _context_levels(
    context: str,
    counts: Mapping[str, Sequence[int]],
    totals: Mapping[str, int],
    smoothing: float,
    precision: float,
) -> tuple[int, ...]:
    """Levels for every symbol after *context*, backing off until something was seen."""
    history = context
    while history and history not in counts:
        history = history[1:]
    row = counts.get(history)
    if row is None:
        flat = quantise(math.log10(len(_SYMBOLS)), precision)
        return tuple([flat] * len(_SYMBOLS))
    denominator = totals[history] + smoothing * len(_SYMBOLS)
    return tuple(
        quantise(-math.log10((row[index] + smoothing) / denominator), precision)
        for index in range(len(_SYMBOLS))
    )


# -- suffix families --------------------------------------------------------


@dataclass(frozen=True)
class SuffixFamily:
    """What a shape appends to a cased stem, as a bounded indexable set.

    A family is a set of strings of one fixed width with a fixed enumeration
    order. The width is what makes the inverse a single test rather than a
    search: at most one split of a target is possible, so :meth:`split` either
    finds it or the family cannot have produced the target.
    """

    name: str
    #: ``none`` | ``digits`` | ``year`` | ``symbol`` | ``symbol_digits``
    kind: str
    digits: int = 0
    year_range: tuple[int, int] = (0, 0)
    symbols: str = ""

    @property
    def size(self) -> int:
        if self.kind == "none":
            return 1
        if self.kind == "digits":
            return 10**self.digits
        if self.kind == "year":
            return self.year_range[1] - self.year_range[0] + 1
        if self.kind == "symbol":
            return len(self.symbols)
        if self.kind == "symbol_digits":
            return len(self.symbols) * 10**self.digits
        raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    @property
    def width(self) -> int:
        """Characters this family occupies, so a stem can be cut off exactly."""
        if self.kind == "none":
            return 0
        if self.kind == "digits":
            return self.digits
        if self.kind == "year":
            return 4
        if self.kind == "symbol":
            return 1
        if self.kind == "symbol_digits":
            return 1 + self.digits
        raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    def split(self, target: str) -> tuple[str, int] | None:
        """``(stem surface, suffix index)`` if *target* ends with a member.

        Digit runs keep their leading zeros: ``007`` is the seventh member of
        the three-digit family, not the seventh of the one-digit family,
        because an attacker enumerating ``000..999`` really does emit it there.
        """
        width = self.width
        if width == 0:
            return (target, 0)
        if len(target) <= width:
            return None
        stem, tail = target[:-width], target[-width:]

        if self.kind == "digits":
            return (stem, int(tail)) if tail.isdigit() and tail.isascii() else None
        if self.kind == "year":
            if not (tail.isdigit() and tail.isascii()):
                return None
            value = int(tail)
            low, high = self.year_range
            return (stem, value - low) if low <= value <= high else None
        if self.kind == "symbol":
            position = self.symbols.find(tail)
            return (stem, position) if position >= 0 else None
        if self.kind == "symbol_digits":
            symbol, rest = tail[0], tail[1:]
            position = self.symbols.find(symbol)
            if position < 0 or not (rest.isdigit() and rest.isascii()):
                return None
            return (stem, position * 10**self.digits + int(rest))
        raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    def members(self) -> Iterator[str]:
        """Every member, in enumeration order.

        Used by the toy exhaustive test and by nothing on the ranking path. The
        production arithmetic needs :attr:`size` and :meth:`split` only, which is
        what lets the universe be counted without being built.
        """
        if self.kind == "none":
            yield ""
        elif self.kind == "digits":
            for value in range(10**self.digits):
                yield str(value).zfill(self.digits)
        elif self.kind == "year":
            low, high = self.year_range
            for value in range(low, high + 1):
                yield str(value)
        elif self.kind == "symbol":
            yield from self.symbols
        elif self.kind == "symbol_digits":
            for symbol in self.symbols:
                for value in range(10**self.digits):
                    yield symbol + str(value).zfill(self.digits)
        else:
            raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name or "(none)",
            "kind": self.kind,
            "size": self.size,
            "width": self.width,
        }


def build_families(settings: CharacterAttackSettings) -> list[SuffixFamily]:
    """Every suffix family, in :data:`_FAMILY_ORDER`."""
    families = [SuffixFamily("", "none")]
    families += [
        SuffixFamily(f"digits{n}", "digits", digits=n) for n in range(1, settings.max_digits + 1)
    ]
    families.append(SuffixFamily("year", "year", year_range=settings.year_range))
    families.append(SuffixFamily("symbol", "symbol", symbols=settings.symbols))
    families += [
        SuffixFamily(f"symbol+digits{n}", "symbol_digits", digits=n, symbols=settings.symbols)
        for n in range(1, settings.max_symbol_digits + 1)
    ]
    return families


# -- shapes -----------------------------------------------------------------


def _apply_case(stem: str, case: str) -> str:
    if case == "lower":
        return stem
    if case == "capitalized":
        return stem.capitalize()
    if case == "upper":
        return stem.upper()
    raise ValueError(f"Unknown case {case!r}. Known: {list(CASES)}.")


def _stem_of(surface: str, case: str) -> str | None:
    """The lower-case stem a cased *surface* came from, or ``None``.

    ``capitalized`` and ``upper`` coincide for a one-letter stem, so ``A`` is
    emitted by two shapes. :meth:`CharacterAttack.rank` takes the minimum, which
    is the position the enumeration actually reaches it at. The shape *sizes*
    still count both, over-counting the universe by 26 candidates per family --
    the conservative direction, since it can only push later candidates further
    out.
    """
    if not surface or not surface.isascii() or not surface.isalpha():
        return None
    lowered = surface.lower()
    return lowered if surface == _apply_case(lowered, case) else None


@dataclass(frozen=True)
class Shape:
    """One ``(case, suffix family)`` pair, placed in the enumeration.

    ``level`` is the constant every candidate of this shape pays before its stem
    is priced; ``index`` is its position in the tie-break order. Both are fixed
    at build time, so a rank is arithmetic over a table of a few dozen rows.
    """

    case: str
    family: SuffixFamily
    level: int
    index: int

    @property
    def name(self) -> str:
        """Shape only -- publishable, and what a report's rows are keyed on."""
        tail = f"+{self.family.name}" if self.family.name else ""
        return f"stem{tail}/{self.case}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "case": self.case,
            "suffix": self.family.name or "(none)",
            "suffix_size": self.family.size,
            "level": self.level,
            "index": self.index,
        }


def build_shapes(settings: CharacterAttackSettings) -> list[Shape]:
    """Every shape, in the order ties within a level are broken by.

    ``shape_level`` is the quantised cost of choosing a case (uniform over
    three), a family (uniform over however many there are) and a member within
    it (uniform). Sorted by that level first, so the cheapest decoration runs
    earliest; then by the fixed family order, then by the fixed case order, so
    two shapes of equal cost are still totally ordered.
    """
    families = build_families(settings)
    precision = settings.precision
    case_cost = quantise(math.log10(len(CASES)), precision)
    family_cost = quantise(math.log10(len(families)), precision)

    unordered: list[tuple[int, int, int, str, SuffixFamily]] = []
    for family in families:
        level = case_cost + family_cost + quantise(math.log10(family.size), precision)
        for case in CASES:
            unordered.append(
                (level, _FAMILY_ORDER.index(family.name), CASES.index(case), case, family)
            )
    unordered.sort(key=lambda item: item[:3])
    return [
        Shape(case=case, family=family, level=level, index=index)
        for index, (level, _, _, case, family) in enumerate(unordered)
    ]


# -- counting the stems -----------------------------------------------------


class StemCounter:
    """How many stems sit at each ``(length, level)``, and how many precede one.

    This is the piece that lets the universe be **counted without being
    materialised**. ``_table[k][context]`` holds, for every level ``m``, the
    number of ways to emit exactly ``k`` more characters from ``context`` and
    then stop, at a total cost of ``m``. The recurrence is one line::

        W[0][h][m] = 1 if m == level(h, END) else 0
        W[k][h][m] = Σ_c W[k-1][h·c][m - level(h, c)]

    Each row is stored as ``(lowest level, counts)`` because the reachable band
    is narrow for short stems, and skipping the zeros outside it is the
    difference between a build that takes seconds and one that takes minutes.
    """

    def __init__(
        self,
        model: CharacterModel,
        *,
        min_length: int,
        max_length: int,
        max_level: int,
    ) -> None:
        if min_length < 1:
            raise ValueError(f"A stem needs at least one character, got {min_length}.")
        if max_length < min_length:
            raise ValueError(f"max_stem_length {max_length} is below min {min_length}.")
        if max_level < 1:
            raise ValueError(f"max_level must be positive, got {max_level}.")

        self.model = model
        self.min_length = min_length
        self.max_length = max_length
        self.max_level = max_level

        contexts = sorted(model.levels)
        self._contexts = contexts
        index_of = {context: index for index, context in enumerate(contexts)}
        self._index_of = index_of
        self._levels = [model.levels[context] for context in contexts]
        width = model.order - 1
        self._next = [
            [
                index_of[(context + character)[-width:] if width else ""]
                for character in STEM_ALPHABET
            ]
            for context in contexts
        ]
        self._start = index_of[_PAD * width]
        self._preceding_cache: dict[str, int] = {}
        self._table = self._build_table()
        self._totals = self._build_totals()

    # -- the dynamic programme -------------------------------------------

    def _build_table(self) -> list[list[tuple[int, list[int]] | None]]:
        cap = self.max_level
        contexts = len(self._contexts)
        base: list[tuple[int, list[int]] | None] = []
        for index in range(contexts):
            end = self._levels[index][_END_INDEX]
            base.append((end, [1]) if end <= cap else None)
        table: list[list[tuple[int, list[int]] | None]] = [base]

        for _ in range(self.max_length):
            previous = table[-1]
            layer: list[tuple[int, list[int]] | None] = []
            for index in range(contexts):
                levels = self._levels[index]
                successors = self._next[index]
                low = cap + 1
                high = -1
                accumulator = [0] * (cap + 1)
                for symbol in range(len(STEM_ALPHABET)):
                    entry = previous[successors[symbol]]
                    if entry is None:
                        continue
                    start = entry[0] + levels[symbol]
                    if start > cap:
                        continue
                    counts = entry[1]
                    span = min(len(counts), cap + 1 - start)
                    stop = start + span
                    accumulator[start:stop] = [
                        a + b
                        for a, b in zip(accumulator[start:stop], counts[:span], strict=True)
                    ]
                    low = min(low, start)
                    high = max(high, stop - 1)
                layer.append((low, accumulator[low : high + 1]) if high >= low else None)
            table.append(layer)
        return table

    def _build_totals(self) -> list[int]:
        """``S(m)``: stems of any allowed length whose level is exactly ``m``."""
        totals = [0] * (self.max_level + 1)
        for length in range(self.min_length, self.max_length + 1):
            entry = self._table[length][self._start]
            if entry is None:
                continue
            low, counts = entry
            for offset, value in enumerate(counts):
                totals[low + offset] += value
        return totals

    # -- queries -----------------------------------------------------------

    @staticmethod
    def _at(entry: tuple[int, list[int]] | None, level: int) -> int:
        if entry is None:
            return 0
        low, counts = entry
        position = level - low
        return counts[position] if 0 <= position < len(counts) else 0

    def count(self, length: int, level: int) -> int:
        """Stems of exactly *length* at exactly *level*."""
        if not self.min_length <= length <= self.max_length:
            return 0
        if not 0 <= level <= self.max_level:
            return 0
        return self._at(self._table[length][self._start], level)

    def total_at_level(self, level: int) -> int:
        """``S(level)``, summed over every allowed length."""
        if not 0 <= level <= self.max_level:
            return 0
        return self._totals[level]

    @property
    def universe(self) -> int:
        """Every stem the bounds allow. Counted, never enumerated."""
        return sum(self._totals)

    def level_of(self, stem: str) -> int | None:
        """The stem's level, or ``None`` if it is outside the universe.

        ``None`` covers three different facts and the caller distinguishes them
        by asking again: outside the alphabet, outside the length band, or
        priced above the budget.
        """
        if not self.min_length <= len(stem) <= self.max_length:
            return None
        context = self._start
        total = 0
        for character in stem:
            symbol = _SYMBOL_INDEX.get(character)
            if symbol is None or symbol == _END_INDEX:
                return None
            total += self._levels[context][symbol]
            context = self._next[context][symbol]
            if total > self.max_level:
                return None
        total += self._levels[context][_END_INDEX]
        return total if total <= self.max_level else None

    def preceding(self, stem: str) -> int:
        """Stems at *stem*'s own level that the enumeration reaches first.

        Length ascending, then lexicographic. Counted by walking the stem once:
        at each position, every smaller letter opens a set of completions whose
        size the table already holds. That is the inversion the milestone asks
        for -- a rank recovered without enumerating anything that precedes it.
        """
        cached = self._preceding_cache.get(stem)
        if cached is not None:
            return cached

        level = self.level_of(stem)
        if level is None:
            raise ValueError("The stem is outside the universe; it has no position.")

        total = 0
        for length in range(self.min_length, len(stem)):
            total += self._at(self._table[length][self._start], level)

        context = self._start
        used = 0
        for position, character in enumerate(stem):
            remaining = len(stem) - position - 1
            levels = self._levels[context]
            successors = self._next[context]
            limit = _SYMBOL_INDEX[character]
            layer = self._table[remaining]
            for symbol in range(limit):
                budget = level - used - levels[symbol]
                if budget < 0:
                    continue
                total += self._at(layer[successors[symbol]], budget)
            used += levels[limit]
            context = successors[limit]

        self._preceding_cache[stem] = total
        return total

    def describe(self) -> dict[str, Any]:
        return {
            "min_stem_length": self.min_length,
            "max_stem_length": self.max_length,
            "level_ceiling": self.max_level,
            "contexts": len(self._contexts),
            "stems_counted": self.universe,
            "log10_stems_counted": (
                round(math.log10(self.universe), 4) if self.universe else None
            ),
            "note": (
                "Stems are counted by dynamic programme over (remaining length, "
                "context, remaining level). No candidate list is ever built. This is "
                "every stem below the counting ceiling; the attack's own universe is "
                "the prefix of it the budget affords."
            ),
        }


# -- settings ---------------------------------------------------------------


@dataclass(frozen=True)
class CharacterAttackSettings:
    """Every bound that defines the attack. Serialised into every report."""

    order: int = 3
    smoothing: float = 1.0
    precision: float = 0.25
    #: The attacker's budget in candidates. Inherited from Milestone 4 so the
    #: two attacks cost the same and their coverage is comparable.
    max_candidates: float = 1e16
    #: Height of the counting table. A structural bound, not a policy: the build
    #: refuses to let it, rather than the budget, decide the universe.
    level_ceiling: int = 128
    min_stem_length: int = 1
    max_stem_length: int = 16
    year_range: tuple[int, int] = (1940, 2029)
    symbols: str = ATTACK_SYMBOLS
    max_digits: int = 5
    max_symbol_digits: int = 3
    model: str = "indicdict"
    training_share: float = 1.0
    training_seed: int = 42

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> CharacterAttackSettings:
        years = section.get("year_range") or [1940, 2029]
        return cls(
            order=int(section.get("order", 3)),
            smoothing=float(section.get("smoothing", 1.0)),
            precision=float(section.get("precision", 0.25)),
            max_candidates=float(section.get("max_candidates", 1e16)),
            level_ceiling=int(section.get("level_ceiling", 128)),
            min_stem_length=int(section.get("min_stem_length", 1)),
            max_stem_length=int(section.get("max_stem_length", 16)),
            year_range=(int(years[0]), int(years[1])),
            symbols=str(section.get("symbols", ATTACK_SYMBOLS)),
            max_digits=int(section.get("max_digits", 5)),
            max_symbol_digits=int(section.get("max_symbol_digits", 3)),
            model=str(section.get("model", "indicdict")),
            training_share=float(section.get("training_share", 1.0)),
            training_seed=int(section.get("training_seed", 42)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "smoothing": self.smoothing,
            "precision": self.precision,
            "max_candidates": self.max_candidates,
            "log10_max_candidates": round(math.log10(self.max_candidates), 4),
            "level_ceiling": self.level_ceiling,
            "min_stem_length": self.min_stem_length,
            "max_stem_length": self.max_stem_length,
            "year_range": list(self.year_range),
            "symbols": self.symbols,
            "symbol_count": len(self.symbols),
            "max_digits": self.max_digits,
            "max_symbol_digits": self.max_symbol_digits,
            "model": self.model,
            "training_share": self.training_share,
            "training_seed": self.training_seed,
        }


# -- the attack -------------------------------------------------------------


@dataclass(frozen=True)
class CharacterAttackRank:
    """Where the attack reached a password, or why it never does.

    Holds no password: ``shape`` is a form like ``stem+year/capitalized``, the
    same class of information as the benchmark's ``construction``.

    ``rank`` is ``None`` whenever ``reachable`` is false, and it is never a
    substituted value, a censored bound or the universe size. ``reason`` names
    which bound put the target outside, so an unreachable row is a fact rather
    than a gap.
    """

    reachable: bool
    rank: int | None = None
    log10_rank: float | None = None
    shape: str | None = None
    level: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "rank": self.rank,
            "log10_rank": round(self.log10_rank, 6) if self.log10_rank is not None else None,
            "shape": self.shape,
            "level": self.level,
            "reason": self.reason,
        }


#: Returned for an empty password, rather than a fresh object each time.
UNREACHABLE = CharacterAttackRank(reachable=False, reason="empty")

#: Which reason wins when several shapes fail differently. Most specific first:
#: "the budget stopped it" says more than "no shape fits", so it is preferred.
_REASON_PRECEDENCE: tuple[str, ...] = (
    "level_above_budget",
    "stem_too_long",
    "stem_too_short",
    "no_shape",
)


@dataclass(frozen=True)
class CharacterAttack:
    """A fully specified OOV-capable attacker, and the ranks it produces.

    Build with :meth:`build`, then call :meth:`rank`. Immutable, and the only
    state it keeps is a memo of stem positions, so ranking a corpus twice in one
    process gives the same answer as ranking it in two.
    """

    settings: CharacterAttackSettings
    model: CharacterModel
    counter: StemCounter
    shapes: tuple[Shape, ...]
    #: The deepest level the budget affords. Derived, not configured.
    max_level: int
    #: ``N(level)``: candidates at each level, and the running total before it.
    level_counts: tuple[int, ...]
    level_offsets: tuple[int, ...]
    universe_size: int
    #: False when the counting table's height, not the budget, ended the
    #: enumeration -- in which case the universe is an implementation artefact
    #: and the report has to say so.
    budget_binding: bool

    @classmethod
    def build(cls, model: CharacterModel, settings: CharacterAttackSettings) -> CharacterAttack:
        """Count the universe level by level, and place every shape.

        Levels are bought cheapest-first until the next one would break the
        budget, exactly as Milestone 4 buys rule blocks. The last affordable
        level is ``max_level``; everything above it is outside the universe.
        """
        if model.order != settings.order or model.precision != settings.precision:
            raise ValueError(
                "The character model was fitted with different settings than the attack "
                f"asks for (order {model.order} vs {settings.order}, precision "
                f"{model.precision} vs {settings.precision})."
            )
        counter = StemCounter(
            model,
            min_length=settings.min_stem_length,
            max_length=settings.max_stem_length,
            max_level=settings.level_ceiling,
        )
        shapes = tuple(build_shapes(settings))

        counts: list[int] = []
        offsets: list[int] = []
        running = 0
        max_level = -1
        for level in range(settings.level_ceiling + 1):
            total = 0
            for shape in shapes:
                remainder = level - shape.level
                if remainder < 0:
                    continue
                stems = counter.total_at_level(remainder)
                if stems:
                    total += stems * shape.family.size
            if running + total > settings.max_candidates:
                break
            counts.append(total)
            offsets.append(running)
            running += total
            max_level = level

        if running == 0:
            raise ValueError(
                f"No candidate fits a budget of {settings.max_candidates:.3g} candidates. "
                "The universe is empty; raise max_candidates."
            )

        return cls(
            settings=settings,
            model=model,
            counter=counter,
            shapes=shapes,
            max_level=max_level,
            level_counts=tuple(counts),
            level_offsets=tuple(offsets),
            universe_size=running,
            budget_binding=max_level < settings.level_ceiling,
        )

    # -- ranking -----------------------------------------------------------

    def rank(self, password: str) -> CharacterAttackRank:
        """The 1-based position at which this attack emits *password*.

        Every shape that can decompose the password is priced and the **minimum**
        is returned: a candidate two shapes can produce is reached at the earlier
        of them, not at both. When no shape reaches it the result names the bound
        that stopped it and carries no rank.
        """
        if not password:
            return UNREACHABLE

        best: CharacterAttackRank | None = None
        failures: set[str] = set()

        for shape in self.shapes:
            split = shape.family.split(password)
            if split is None:
                continue
            surface, suffix_index = split
            stem = _stem_of(surface, shape.case)
            if stem is None:
                continue
            if len(stem) < self.settings.min_stem_length:
                failures.add("stem_too_short")
                continue
            if len(stem) > self.settings.max_stem_length:
                failures.add("stem_too_long")
                continue
            stem_level = self.counter.level_of(stem)
            if stem_level is None:
                failures.add("level_above_budget")
                continue
            level = shape.level + stem_level
            if level > self.max_level:
                failures.add("level_above_budget")
                continue

            rank = self._position(shape, stem, stem_level, suffix_index, level)
            if best is None or rank < best.rank:  # type: ignore[operator]
                best = CharacterAttackRank(
                    reachable=True,
                    rank=rank,
                    log10_rank=math.log10(rank),
                    shape=shape.name,
                    level=level,
                )

        if best is not None:
            return best
        for reason in _REASON_PRECEDENCE:
            if reason in failures:
                return CharacterAttackRank(reachable=False, reason=reason)
        return CharacterAttackRank(reachable=False, reason="no_shape")

    def _position(
        self, shape: Shape, stem: str, stem_level: int, suffix_index: int, level: int
    ) -> int:
        """Closed-form position of one candidate. Nothing before it is listed.

        Three terms, in the order the enumeration visits them: every candidate at
        a cheaper level, every candidate at this level belonging to an earlier
        shape, and every candidate of this shape whose stem comes first.
        """
        position = self.level_offsets[level]
        for other in self.shapes:
            if other.index >= shape.index:
                break
            remainder = level - other.level
            if remainder < 0:
                continue
            stems = self.counter.total_at_level(remainder)
            if stems:
                position += stems * other.family.size
        position += self.counter.preceding(stem) * shape.family.size
        return position + suffix_index + 1

    def rank_all(self, passwords: Sequence[str]) -> list[CharacterAttackRank]:
        return [self.rank(password) for password in passwords]

    def candidates_at_level(self, level: int) -> int:
        """``N(level)``. Zero outside the budget, never an error."""
        if not 0 <= level <= self.max_level:
            return 0
        return self.level_counts[level]

    # -- provenance --------------------------------------------------------

    def fingerprint(self) -> str:
        """SHA-256 over the model, the bounds and the placed shape programme."""
        digest = hashlib.sha256()
        digest.update(f"{ATTACK_VERSION}\n{self.model.fingerprint()}\n".encode())
        for key, value in sorted(self.settings.to_dict().items()):
            digest.update(f"{key}={value!r}\n".encode())
        for shape in self.shapes:
            digest.update(f"{shape.name}\t{shape.level}\t{shape.family.size}\n".encode())
        digest.update(f"max_level={self.max_level}\nuniverse={self.universe_size}\n".encode())
        return f"sha256:{digest.hexdigest()}"

    def describe(self) -> dict[str, Any]:
        """Everything a reader needs to reproduce or dispute the attack."""
        occupied = [level for level, count in enumerate(self.level_counts) if count]
        return {
            "attack_version": ATTACK_VERSION,
            "settings": self.settings.to_dict(),
            "model": self.model.describe(),
            "stems": self.counter.describe(),
            "universe_size": self.universe_size,
            "log10_universe_size": round(math.log10(self.universe_size), 4),
            "max_level": self.max_level,
            "budget_binding": self.budget_binding,
            "shapes": [shape.to_dict() for shape in self.shapes],
            "first_occupied_level": occupied[0] if occupied else None,
            "last_occupied_level": occupied[-1] if occupied else None,
            "fingerprint": self.fingerprint(),
            "search_dimensions": {
                "stem": (
                    f"every string over {len(STEM_ALPHABET)} lower-case ASCII letters of "
                    f"length {self.settings.min_stem_length}-{self.settings.max_stem_length}, "
                    "generated by the character model rather than looked up -- this is what "
                    "makes an out-of-lexicon spelling reachable"
                ),
                "case": f"{len(CASES)} whole-stem case forms: {', '.join(CASES)}",
                "suffix": (
                    f"{len(build_families(self.settings))} families: nothing, 1-"
                    f"{self.settings.max_digits} digits, a year in "
                    f"{self.settings.year_range[0]}-{self.settings.year_range[1]}, one of "
                    f"{len(self.settings.symbols)} symbols, or a symbol plus 1-"
                    f"{self.settings.max_symbol_digits} digits"
                ),
                "budget": (
                    f"{self.settings.max_candidates:.3g} candidates, which buys every "
                    f"candidate at total level <= {self.max_level}, where one level is "
                    f"{self.settings.precision} of a log10 unit of cost"
                ),
            },
            "ordering": [
                "ascending level (quantised -log10 cost)",
                "then by shape index: shapes sorted by (shape level, family order, case order)",
                "then by stem: length ascending, then lexicographic over a-z",
                "then by the suffix's index within its family",
            ],
            "assumptions": [
                "P(case) uniform over three forms. No password corpus exists here to "
                "learn a case prior from; maximum entropy asserts nothing unmeasured.",
                "P(suffix family) uniform, and uniform within a family. Same reasoning.",
                "Costs are quantised to integer levels and summed. A sum of quantised "
                "costs is not the quantised sum: the level DEFINES this attack's order "
                "and is not claimed to be a probability.",
                "Additive (Laplace) smoothing with alpha as configured, backing off to "
                "the longest context the training data actually showed.",
            ],
            "independence_note": (
                "Candidate generation and ordering use the dictionary's romanized "
                "spellings and nothing else. No IndicPass score, no PCFG probability and "
                "no zxcvbn output of any kind is read anywhere in this module, which "
                "imports only the standard library. The indicdict model nevertheless "
                "SHARES TRAINING EVIDENCE with the PCFG's own character n-gram -- same "
                "spellings, different order, smoothing and implementation -- so a result "
                "that appears only under that arm is partly a statement about shared "
                "data. The uniform arm shares none."
            ),
            "coverage_note": (
                "An unreachable password is given no rank and a named reason. It is "
                "never assigned the universe size, a censored bound, or any substituted "
                "value. unreachable != universe_size."
            ),
        }


def coverage(ranks: Sequence[CharacterAttackRank]) -> dict[str, Any]:
    """Reachable share of *ranks*, the shapes used, and why the rest failed."""
    if not ranks:
        return {"targets": 0, "reachable": 0, "coverage": 0.0, "shapes": {}, "reasons": {}}
    shapes: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for entry in ranks:
        if entry.shape:
            shapes[entry.shape] = shapes.get(entry.shape, 0) + 1
        if entry.reason:
            reasons[entry.reason] = reasons.get(entry.reason, 0) + 1
    reached = sum(1 for entry in ranks if entry.reachable)
    return {
        "targets": len(ranks),
        "reachable": reached,
        "coverage": round(reached / len(ranks), 4),
        "shapes": dict(sorted(shapes.items(), key=lambda item: (-item[1], item[0]))),
        "reasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
    }
