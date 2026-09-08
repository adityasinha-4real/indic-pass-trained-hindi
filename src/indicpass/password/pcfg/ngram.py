"""A character n-gram over Romanized Indic spellings.

This is the PCFG's answer to the largest limitation Milestone 2 measured: the
dictionary covers 38% of the probe bank, so the words that matter most --
``namaste``, ``sharma``, ``ghar`` -- are absent from Aksharantar's Hindi split
*at source* and score as unexplained text. A wordlist can only recognise what is
in it. A character model can recognise the *shape* of the language, so a Hindi
spelling the dictionary never saw is still cheaper to reach than a random
string of the same length.

That is the whole reason this module exists, and it is why the model is trained
on the dictionary's **keys** -- the Romanized spellings -- rather than on
anything else in the repository. No word is added by hand; the model learns what
Romanized Hindi looks like from the 297,747 spellings that are already there.

Smoothing
---------
Witten-Bell interpolation, recursively from the unigram up:

    P(c | h) = ( N(h,c) + T(h) · P(c | h') ) / ( N(h) + T(h) )

where ``N(h)`` is how often the context was seen, ``T(h)`` how many *distinct*
characters followed it, and ``h'`` is ``h`` with its oldest character dropped.
The base case is uniform over the alphabet.

Witten-Bell rather than add-k because it has **no free parameter**: the
interpolation weight ``T(h)/(N(h)+T(h))`` is read off the training counts. A
context seen many times with few continuations trusts itself; a context seen
once backs off almost entirely. That matters here because every knob the guess
model carries has to be defended, and this is one that does not need to be.

The distribution is over strings, not characters: an end-of-word symbol is
part of the alphabet, so ``log10_probability`` returns the log probability of
the whole spelling and the model supplies its own length distribution rather
than borrowing one.

What this is not
----------------
The n-gram is trained on a **type** distribution -- each dictionary spelling
counted once -- not on a token distribution over running text. It therefore
models "what a Romanized Hindi word looks like", not "how often one is written".
Word frequency is carried separately, by the wordfreq join; the two are not
mixed. See ``docs/password_strength_design.md`` §14.
"""

from __future__ import annotations

import math
import random
import string
from collections.abc import Iterable, Sequence
from typing import Any

__all__ = ["END_OF_WORD", "NGRAM_ALPHABET", "CharacterNgram"]

#: Emitted after the last character of a spelling. Being part of the alphabet
#: is what makes the model a distribution over *strings*: the probability of
#: stopping is learned from how often words ended in each context, so the model
#: does not need a separate length prior bolted on.
END_OF_WORD = "\x00"

#: The dictionary build filters its keys to ASCII lower-case letters, so this is
#: the complete symbol set and no character can fall outside it.
NGRAM_ALPHABET: tuple[str, ...] = (*string.ascii_lowercase, END_OF_WORD)

#: Padding for the left edge of a word. Outside the alphabet, so it can never be
#: predicted -- it only ever appears in a context.
_PAD = "\x01"

_UNIFORM = 1.0 / len(NGRAM_ALPHABET)


class CharacterNgram:
    """An order-*n* character model with Witten-Bell backoff.

    Deterministic in its training data: the counts depend on the set of words
    and not on their order, and every derived quantity is computed from the
    counts alone. Two runs over the same dictionary give bit-identical
    probabilities, which is what lets the trained artefact carry a fingerprint.
    """

    def __init__(
        self,
        order: int,
        counts: dict[str, dict[str, int]],
        *,
        training_words: int = 0,
        training_characters: int = 0,
    ) -> None:
        if order < 1:
            raise ValueError(f"An n-gram needs order >= 1, got {order}.")
        self.order = order
        self.counts = counts
        self.training_words = training_words
        self.training_characters = training_characters

        self._totals = {context: sum(row.values()) for context, row in counts.items()}
        self._distinct = {context: len(row) for context, row in counts.items()}
        # Lazily built per-context tables. There are only a few thousand
        # distinct contexts even at order 5, so caching them outright turns
        # scoring and sampling from a recursive walk into a dict lookup.
        self._table: dict[str, dict[str, float]] = {}
        self._log_table: dict[str, dict[str, float]] = {}

    # -- training ----------------------------------------------------------

    @classmethod
    def train(cls, words: Iterable[str], *, order: int = 4) -> CharacterNgram:
        """Count every context length from 0 to ``order - 1`` in one pass.

        The lower orders are not an afterthought: Witten-Bell backs off through
        all of them, so they have to be counted from the same data or the
        interpolation would mix models fitted to different corpora.
        """
        if order < 1:
            raise ValueError(f"An n-gram needs order >= 1, got {order}.")

        counts: dict[str, dict[str, int]] = {}
        seen_words = 0
        seen_characters = 0

        pad = _PAD * (order - 1)
        for word in words:
            if not word:
                continue
            seen_words += 1
            seen_characters += len(word) + 1  # the end-of-word symbol counts
            padded = pad + word + END_OF_WORD
            for index in range(order - 1, len(padded)):
                char = padded[index]
                for back in range(order):
                    context = padded[index - back : index]
                    row = counts.get(context)
                    if row is None:
                        row = counts[context] = {}
                    row[char] = row.get(char, 0) + 1

        return cls(
            order,
            counts,
            training_words=seen_words,
            training_characters=seen_characters,
        )

    # -- the distribution --------------------------------------------------

    def distribution(self, context: str) -> dict[str, float]:
        """``P(· | context)`` over the whole alphabet. Sums to 1."""
        context = context[-(self.order - 1) :] if self.order > 1 else ""
        cached = self._table.get(context)
        if cached is not None:
            return cached

        # Walk from the unigram outwards, each order interpolating with what the
        # shorter context already produced.
        probabilities = dict.fromkeys(NGRAM_ALPHABET, _UNIFORM)
        for length in range(len(context) + 1):
            history = context[len(context) - length :] if length else ""
            row = self.counts.get(history)
            if row is None:
                # Context never seen: the shorter model stands unchanged. This
                # is the case Witten-Bell handles for free -- there is no count
                # to interpolate towards, so no weight is given to one.
                continue
            total = self._totals[history]
            distinct = self._distinct[history]
            denominator = total + distinct
            probabilities = {
                char: (row.get(char, 0) + distinct * probabilities[char]) / denominator
                for char in NGRAM_ALPHABET
            }

        self._table[context] = probabilities
        return probabilities

    def _log_distribution(self, context: str) -> dict[str, float]:
        context = context[-(self.order - 1) :] if self.order > 1 else ""
        cached = self._log_table.get(context)
        if cached is None:
            cached = self._log_table[context] = {
                char: math.log10(value) if value > 0 else -math.inf
                for char, value in self.distribution(context).items()
            }
        return cached

    def log10_probability(self, word: str) -> float:
        """``log10 P(word)`` as a complete string, end-of-word included.

        Returns ``-inf`` for a spelling containing something outside the
        alphabet, which the caller reads as "this category cannot explain this
        span" rather than as a very small number.
        """
        if not word:
            return -math.inf

        padded = _PAD * (self.order - 1) + word + END_OF_WORD
        total = 0.0
        for index in range(self.order - 1, len(padded)):
            char = padded[index]
            if char not in _ALPHABET_SET:
                return -math.inf
            total += self._log_distribution(padded[index - self.order + 1 : index])[char]
        return total

    def log10_probability_per_character(self, words: Sequence[str]) -> float:
        """Mean ``log10 P`` per character over *words*: the model's own fit.

        Reported in the artefact so a later run can see whether a change to the
        order or the training set made the model better or worse at the thing it
        is for, rather than only whether the benchmark moved.
        """
        characters = 0
        total = 0.0
        for word in words:
            value = self.log10_probability(word)
            if value == -math.inf:
                continue
            total += value
            characters += len(word) + 1
        return total / characters if characters else 0.0

    # -- sampling ----------------------------------------------------------

    def sample(self, rng: random.Random, *, max_length: int = 32) -> str:
        """Draw one spelling from the model.

        Used only to build the guess curve, and the string is discarded the
        moment its probability has been taken -- see
        :mod:`indicpass.password.pcfg.estimator`. Nothing sampled is ever
        written down.

        *max_length* truncates the rare runaway draw. Truncation loses a
        vanishing amount of probability mass and cannot make a sampled string
        look *more* likely than it is, so it cannot bias the curve downwards.
        """
        out: list[str] = []
        while len(out) < max_length:
            context = (_PAD * (self.order - 1) + "".join(out))[-(self.order - 1) :]
            probabilities = self.distribution(context)
            roll = rng.random()
            cumulative = 0.0
            chosen = END_OF_WORD
            for char in NGRAM_ALPHABET:
                cumulative += probabilities[char]
                if roll < cumulative:
                    chosen = char
                    break
            if chosen == END_OF_WORD:
                break
            out.append(chosen)
        return "".join(out)

    # -- provenance --------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """What went into the model. Carries no spelling from the training set."""
        return {
            "order": self.order,
            "contexts": len(self.counts),
            "training_words": self.training_words,
            "training_characters": self.training_characters,
            "alphabet": len(NGRAM_ALPHABET),
            "smoothing": "witten-bell (interpolated, no free parameter)",
        }

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<CharacterNgram order={self.order} contexts={len(self.counts):,} "
            f"words={self.training_words:,}>"
        )


_ALPHABET_SET = frozenset(NGRAM_ALPHABET)
